"""Activity must preserve provenance, time ordering and read-only pagination."""

import base64
import hashlib
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fravenir.admin.activity import get_activity
from fravenir.admin.server import create_app
from fravenir.storage.sqlite_init import init_kv


@pytest.fixture
def db(tmp_project: Path) -> Path:
    path = tmp_project / "data" / "timeline" / "kv.sqlite"
    path.parent.mkdir()
    init_kv(path)
    with sqlite3.connect(path) as conn:
        conn.executescript("""
          INSERT INTO actors(id,kind,display_name) VALUES(1,'human','Alice'),(2,'agent','Bot');
          INSERT INTO spaces(id,name,created_at) VALUES(1,'Research','2026-01-01 00:00:00');
          INSERT INTO threads(id,space_id,title,created_by,created_at)
            VALUES(1,1,'WorldWindow origin',1,'2026-01-01T12:00:00Z');
          INSERT INTO posts(id,thread_id,author_id,body,revision,created_at,edited_at)
            VALUES(1,1,1,'third version',3,'2026-01-02 00:00:00','2026-01-04T00:00:00Z');
          INSERT INTO posts(id,thread_id,author_id,body,created_at)
            VALUES(2,1,2,'PrintSwift 静かな世界','2026-01-05T00:00:00Z');
          INSERT INTO post_revisions(post_id,revision,body,edited_at,editor_id) VALUES
            (1,1,'first version','2026-01-03T00:00:00Z',2),
            (1,2,'second version','2026-01-04T00:00:00Z',1);
          INSERT INTO episodes(id,content,kind,valid_from,valid_to,is_suppressed,created_at)
            VALUES(1,'WorldWindow 静かな世界','facts','2026-01-01',NULL,0,
                     '2026-01-05T09:00:00+09:00'),
                  (2,'hidden memory','facts','2026-01-01',NULL,1,'2026-01-06'),
                  (3,'old memory','facts','2026-01-01','2026-01-06',0,'2026-01-01');
          INSERT INTO entities(id,canonical_name,entity_type,valid_from,created_at)
            VALUES(1,'WorldWindow','concept','2026-01-01','2026-01-04');
          INSERT INTO relations(id,src_type,src_id,dst_type,dst_id,predicate,strength,
                               description,valid_from,valid_to,created_at) VALUES
            (1,'episode',1,'post',1,'derived_from',0.9,'evidence','2026-01-01',
             '2026-01-07T09:00:00+09:00','2026-01-06 00:00:00'),
            (2,'episode',999,'entity',1,'part_of',1,'dangling','2026-01-01',NULL,'2026-01-06'),
            (3,'episode',2,'post',1,'part_of',1,'suppressed','2026-01-01',NULL,'2026-01-06');
        """)
    return path


def test_all_event_streams_and_historical_revision_bodies(db: Path) -> None:
    page = get_activity(db)
    events = {e.id: e for e in page.events}
    assert {e.action for e in page.events} == {
        'post.created', 'post.edited', 'thread.created', 'space.created',
        'episode.created', 'episode.expired', 'entity.created',
        'relation.created', 'relation.expired',
    }
    assert events['post:1:created'].preview == 'first version'
    assert events['post:1:created'].actor == 'Alice'
    assert events['post:1:edit:2'].preview == 'second version'
    assert events['post:1:edit:2'].actor == 'Bot'
    assert events['post:1:edit:3'].preview == 'third version'
    assert events['post:1:edit:3'].actor == 'Alice'
    assert events['post:1:edit:3'].revision == 3
    assert events['relation:1:created'].actor is None
    assert events['relation:1:created'].note == 'episode:1 → post:1 · strength 0.9'
    assert 'episode:2:created' not in events
    assert not any(e.target_id in (2, 3) for e in page.events if e.category == 'graph')


def test_mixed_timezone_formats_and_equal_timestamp_pagination(db: Path) -> None:
    expected = get_activity(db, limit=100).events
    assert [e.occurred_at for e in expected] == sorted(
        (e.occurred_at for e in expected), reverse=True
    )
    cursor = None
    actual = []
    while True:
        page = get_activity(db, limit=1, cursor=cursor)
        actual.extend(e.id for e in page.events)
        cursor = page.next_cursor
        if not cursor:
            assert not page.has_more
            break
    assert actual == [e.id for e in expected]
    assert len(actual) == len(set(actual))
    assert next(e for e in expected if e.id == 'episode:1:created').occurred_at == (
        '2026-01-05T00:00:00+00:00'
    )


def test_filters_use_full_normalized_text_and_utc_date_boundaries(db: Path) -> None:
    found = get_activity(db, category='board', query='ＰＲＩＮＴＳＷＩＦＴ 静かな世界')
    assert [e.id for e in found.events] == ['post:2:created']
    assert all(e.actor == 'Alice' for e in get_activity(db, query='ALICE').events)
    found = get_activity(db, start=datetime(2026, 1, 5), end=datetime(2026, 1, 6))
    assert {e.id for e in found.events} == {'post:2:created', 'episode:1:created'}
    assert get_activity(db, query="%' OR 1=1 --").events == []


def test_paging_anchor_excludes_newer_events(db: Path) -> None:
    page = get_activity(db, limit=1)
    assert page.next_cursor
    future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO posts(id,thread_id,body,created_at) VALUES(10,1,'new',?)", (future,)
        )
    assert 'post:10:created' not in {
        e.id for e in get_activity(db, limit=100, cursor=page.next_cursor).events
    }


@pytest.mark.parametrize('table', ['spaces', 'threads', 'posts'])
def test_deleted_parents_hide_posts_revisions_and_graph_sources(db: Path, table: str) -> None:
    with sqlite3.connect(db) as conn:
        if 'deleted_at' not in {r[1] for r in conn.execute(f'PRAGMA table_info({table})')}:
            conn.execute(f'ALTER TABLE {table} ADD COLUMN deleted_at TEXT')
        conn.execute(f"UPDATE {table} SET deleted_at='2026-01-08' WHERE id=1")
    events = get_activity(db).events
    assert not any(e.target_type == 'post' and e.target_id == 1 for e in events)
    assert not any(e.category == 'graph' for e in events)


def test_missing_revision_is_labeled_without_claiming_historical_content(db: Path) -> None:
    with sqlite3.connect(db) as conn:
        conn.execute('DELETE FROM post_revisions WHERE post_id=1 AND revision=2')
    event = next(e for e in get_activity(db).events if e.id == 'post:1:edit:2')
    assert event.preview == '' and event.note == '改訂後の本文の記録なし'
    with sqlite3.connect(db) as conn:
        conn.execute('DELETE FROM post_revisions WHERE post_id=1 AND revision=1')
    event = next(e for e in get_activity(db).events if e.id == 'post:1:created')
    assert event.note and '現在の本文' in event.note


@pytest.mark.parametrize('cursor', ['%%%', base64.b64encode(b'[]').decode(), 'x' * 513])
def test_bad_cursors_fail_clearly(db: Path, cursor: str) -> None:
    with pytest.raises(ValueError, match='カーソル'):
        get_activity(db, cursor=cursor)


def test_cursor_cannot_be_reused_with_different_filters(db: Path) -> None:
    cursor = get_activity(db, limit=1).next_cursor
    with pytest.raises(ValueError, match='カーソル'):
        get_activity(db, cursor=cursor, category='graph')
    for limit in (0, 101):
        with pytest.raises(ValueError):
            get_activity(db, limit=limit)
    with pytest.raises(ValueError):
        get_activity(db, query='x' * 201)
    with pytest.raises(ValueError):
        get_activity(db, start=datetime(2026, 1, 2), end=datetime(2026, 1, 1))


def test_viewing_pages_never_changes_database(db: Path) -> None:
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    page = get_activity(db, limit=1)
    get_activity(db, cursor=page.next_cursor, limit=100)
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before


def test_authenticated_api_validation_and_empty_result(db: Path, monkeypatch) -> None:
    monkeypatch.setenv('FRAVENIR_ADMIN_USER', 'reader')
    monkeypatch.setenv('FRAVENIR_ADMIN_PASSWORD', 'test-only-password')
    with TestClient(create_app('timeline')) as client:
        assert client.get('/api/activity').status_code == 401
        auth = ('reader', 'test-only-password')
        assert client.get('/api/activity?category=bad', auth=auth).status_code == 422
        assert client.get('/api/activity?limit=1000', auth=auth).status_code == 422
        assert client.get('/api/activity?cursor=bad', auth=auth).status_code == 400
        assert client.get('/api/activity?start=bad', auth=auth).status_code == 422
        result = client.get('/api/activity?q=absent', auth=auth)
        assert result.status_code == 200
        assert result.json()['events'] == []
        assert result.json()['has_more'] is False
        assert result.headers['X-Frame-Options'] == 'DENY'
