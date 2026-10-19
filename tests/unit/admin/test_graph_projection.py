"""Regressions for the actual typed graph returned to the browser."""

import hashlib
import sqlite3
from pathlib import Path

import pytest

from fravenir.admin.queries import get_graph, get_relation_detail
from fravenir.admin.schemas import GraphResponse
from tests.unit.admin.test_queries import NOW, _seed


@pytest.fixture
def graph_db(tmp_path: Path) -> Path:
    db = _seed(tmp_path)
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO spaces(id, name) VALUES(1, 'Research')")
        conn.executemany(
            "INSERT INTO threads(id, space_id, title, status) VALUES(?, 1, ?, ?)",
            [(1, 'source thread', 'open'), (2, 'old thread', 'archived'),
             (3, 'unconnected thread', 'open')],
        )
        conn.executemany(
            "INSERT INTO posts(id, thread_id, body) VALUES(?, ?, ?)",
            [(1, 1, 'exact evidence PrintSwift'), (2, 2, 'archived evidence'),
             (3, 1, 'unconnected post')],
        )
        for rid, src, sid, dst, did, predicate, end in [
            (10, 'episode', 1, 'episode', 4, 'part_of', None),
            (11, 'entity', 1, 'episode', 1, 'supports', None),
            (12, 'episode', 1, 'thread', 1, 'part_of', None),
            (13, 'thread', 1, 'post', 1, 'contains', None),
            (14, 'post', 1, 'episode', 4, 'evidence_for', None),
            (15, 'thread', 1, 'entity', 1, 'about', None),
            (16, 'episode', 1, 'thread', 2, 'related_to', None),
            (17, 'unsupported', 1, 'episode', 1, 'related_to', None),
            (18, 'episode', 1, 'episode', 999, 'related_to', None),
            (19, 'episode', 4, 'episode', 1, 'derived_from', NOW),
            (20, 'post', 2, 'episode', 4, 'derived_from', None),
        ]:
            conn.execute(
                "INSERT INTO relations(id,src_type,src_id,dst_type,dst_id,predicate,"
                "strength,description,valid_from,valid_to) VALUES(?,?,?,?,?,?,0.7,?,?,?)",
                (rid, src, sid, dst, did, predicate, 'source-backed evidence', NOW, end),
            )
    return db


def test_all_supported_endpoints_and_exact_edge_identity(graph_db: Path) -> None:
    raw = get_graph(graph_db, 'active')
    graph = GraphResponse.model_validate(raw).model_dump()
    nodes = {n['data']['id']: n['data'] for n in graph['elements']['nodes']}
    edges = {e['data']['id']: e['data'] for e in graph['elements']['edges']}
    assert set(nodes) == {'ep_1', 'ep_4', 'en_1', 'en_2', 'en_3', 'th_1', 'po_1'}
    for rid in range(10, 16):
        assert f'rel_{rid}' in edges
    assert edges['rel_10'] == {
        'id': 'rel_10', 'source': 'ep_1', 'target': 'ep_4', 'type': 'relation',
        'predicate': 'part_of', 'strength': 0.7, 'is_active': True,
        'relation_id': 10, 'description': 'source-backed evidence',
    }
    assert edges['rel_11']['source'] == 'en_1'
    assert edges['rel_11']['target'] == 'ep_1'
    assert nodes['ep_1']['search_text'].endswith('参照のこと')
    assert nodes['po_1']['search_text'] == 'exact evidence PrintSwift'
    assert edges['men_1']['predicate'] == 'mentions'
    assert edges['men_1']['relation_id'] == 1
    assert all(e['source'] in nodes and e['target'] in nodes for e in edges.values())


def test_active_edges_are_not_archived_or_dangling(graph_db: Path) -> None:
    graph = get_graph(graph_db, 'active')
    ids = {e['data']['id'] for e in graph['elements']['edges']}
    assert ids.isdisjoint({'men_2', 'rel_16', 'rel_17', 'rel_18', 'rel_19', 'rel_20'})
    for scope in ('archived', 'all'):
        graph = get_graph(graph_db, scope)
        edges = {e['data']['id']: e['data'] for e in graph['elements']['edges']}
        assert edges['rel_19']['is_active'] is False
        assert 'rel_16' in edges and 'rel_20' in edges
        assert 'rel_17' not in edges and 'rel_18' not in edges


@pytest.mark.parametrize('table,node', [('spaces', 'th_1'), ('threads', 'th_1'), ('posts', 'po_1')])
def test_trash_and_its_children_stay_out_of_canvas(graph_db: Path, table: str, node: str) -> None:
    with sqlite3.connect(graph_db) as conn:
        columns = {row[1] for row in conn.execute(f'PRAGMA table_info({table})')}
        if 'deleted_at' not in columns:
            conn.execute(f'ALTER TABLE {table} ADD COLUMN deleted_at TEXT')
        conn.execute(f'UPDATE {table} SET deleted_at = ? WHERE id = 1', (NOW,))
    for scope in ('active', 'archived', 'all'):
        graph = get_graph(graph_db, scope)
        ids = {n['data']['id'] for n in graph['elements']['nodes']}
        assert node not in ids
        if table != 'posts':
            assert 'po_1' not in ids


def test_graph_projection_never_writes_database(graph_db: Path) -> None:
    before = hashlib.sha256(graph_db.read_bytes()).hexdigest()
    for scope in ('active', 'archived', 'all'):
        get_graph(graph_db, scope)
    assert hashlib.sha256(graph_db.read_bytes()).hexdigest() == before


def test_relation_detail_labels_board_endpoints(graph_db: Path) -> None:
    detail = get_relation_detail(graph_db, 13)
    assert detail is not None
    assert detail['src_label'] == 'source thread'
    assert detail['dst_label'] == 'exact evidence PrintSwift'
