"""Contracts for query evidence, graph expansion, and non-reinforcing recall."""

import hashlib
import sqlite3
from datetime import UTC, datetime

import numpy as np
import pytest

from fravenir.core.activation import base_activation
from fravenir.core.graph import expand_episode_candidates
from fravenir.core.lexical import lexical_scores, tokenize
from fravenir.core.search import memory_search
from fravenir.core.write import memory_write
from fravenir.storage.vector import episode_cosines
from tests.unit.test_search import (
    _make_character,
    _make_config,
    _make_embedder,
    _open_vec,
)


def _write(tmp_project, embedder, text, cosine, importance=1, kind="facts"):
    vector = np.zeros(768, dtype=np.float32)
    vector[0], vector[1] = cosine, np.sqrt(1 - cosine**2)
    embedder.encode_document.return_value = vector
    return int(
        memory_write(
            text,
            kind,
            importance,
            None,
            character_id="test_char",
            config=_make_config(),
            embedder=embedder,
        )["episode_id"]
    )


def _fixture(tmp_project):
    _make_character(tmp_project)
    embedder = _make_embedder()
    query = np.zeros(768, dtype=np.float32)
    query[0] = 1
    embedder.encode_query.return_value = query
    return embedder, tmp_project / "data/test_char/kv.sqlite"


def _search(embedder, query="unmatched_query", **kwargs):
    return memory_search(
        query, character_id="test_char", config=_make_config(), embedder=embedder, **kwargs
    )


def _edge(conn, src, dst, predicate="related_to", strength=1.0, valid_to=None):
    cur = conn.execute(
        "INSERT INTO relations(src_type,src_id,dst_type,dst_id,predicate,strength,"
        "description,valid_from,valid_to) VALUES('episode',?,'episode',?,?,?,?,?,?)",
        (src, dst, predicate, strength, "preserved evidence", "2026-01-01", valid_to),
    )
    conn.commit()
    return cur.lastrowid


@pytest.mark.parametrize("source", ["direct", "associative", "self_boost", "explore"])
def test_history_cannot_overturn_clear_query_relevance(tmp_project, source):
    embedder, db = _fixture(tmp_project)
    relevant = _write(tmp_project, embedder, "target", 0.85)
    noisy = _write(tmp_project, embedder, "unrelated popular memory", 0.35, importance=3)
    now = datetime.now(UTC)
    with sqlite3.connect(db) as conn:
        conn.executemany(
            "INSERT INTO access_history(node_type,node_id,accessed_at,source) "
            "VALUES('episode',?,?,?)",
            [(noisy, now.isoformat(), source)] * 2000,
        )
    results = _search(embedder)
    assert results[0]["episode_id"] == relevant
    for result in results:
        assert 0 <= result["score_components"]["context"] <= 0.02


def test_search_impressions_are_excluded_before_history_limit(tmp_project):
    _, db = _fixture(tmp_project)
    now = datetime(2026, 10, 16, tzinfo=UTC)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO access_history(node_type,node_id,accessed_at,source) "
            "VALUES('episode',1,'2026-10-15T23:59:59+00:00','explore')"
        )
        conn.executemany(
            "INSERT INTO access_history(node_type,node_id,accessed_at,source) "
            "VALUES('episode',1,?,'direct')",
            [(now.isoformat(),)] * 200,
        )
        value = base_activation(conn, "episode", 1, 0.5, now, 100, include_search_results=False)
        assert value == pytest.approx(0)
        assert base_activation(conn, "episode", 1, 0.5, now) > value
        assert conn.execute("SELECT count(*) FROM access_history").fetchone()[0] == 201


def test_repeated_search_leaves_all_db_bytes_and_order_unchanged(tmp_project):
    embedder, _ = _fixture(tmp_project)
    _write(tmp_project, embedder, "a target", 0.8)
    _write(tmp_project, embedder, "another", 0.6)
    files = list((tmp_project / "data/test_char").iterdir())

    def fingerprint():
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}

    before = fingerprint()
    first = [r["episode_id"] for r in _search(embedder)]
    for _ in range(8):
        assert [r["episode_id"] for r in _search(embedder)] == first
    assert fingerprint() == before


def test_lexical_candidate_outside_knn_keeps_identifier_identity(tmp_project):
    embedder, _ = _fixture(tmp_project)
    for i in range(24):
        _write(tmp_project, embedder, f"unrelated {i}", 0.7)
    target = _write(tmp_project, embedder, "Ｎｉｃｏｂｏｘのデスクトップ化が発端", 0.6)
    result = _search(embedder, "nicobox")[0]
    assert result["episode_id"] == target
    assert result["score_components"]["lexical_candidate"]
    assert not result["score_components"]["vector_candidate"]


def test_lexical_japanese_and_exact_technical_names():
    assert "printcpp" in tokenize("ＰｒｉｎｔＣｐｐ")
    scores = lexical_scores(
        "シェーダーを学びたい", {1: "シェーダーの実装を学びたい", 2: "サーバーの運用を続ける"}
    )
    assert scores[1] > scores.get(2, 0)
    assert lexical_scores("Edge0", {1: "edge0", 2: "edge01", 3: "someEdge0"}).keys() == {1}
    assert lexical_scores("   ", {1: "empty"}) == {}
    assert lexical_scores("猫", {}) == {}


def test_filtered_vectors_do_not_starve_eligible_candidates(tmp_project):
    embedder, _ = _fixture(tmp_project)
    for i in range(24):
        _write(tmp_project, embedder, f"irrelevant kind {i}", 0.9, kind="emo")
    target = _write(tmp_project, embedder, "relevant facts", 0.6)
    assert _search(embedder, kind_filter=["facts"])[0]["episode_id"] == target


def test_graph_adds_near_tie_outside_both_retrievers_and_rejects_unrelated(tmp_project):
    embedder, db = _fixture(tmp_project)
    seed = _write(tmp_project, embedder, "seed", 0.9)
    for i in range(24):
        _write(tmp_project, embedder, f"direct {i}", 0.6)
    neighbor = _write(tmp_project, embedder, "nearby query evidence", 0.5995)
    unrelated = _write(tmp_project, embedder, "unrelated hub", 0.01)
    with sqlite3.connect(db) as conn:
        rid = _edge(conn, seed, neighbor)
        _edge(conn, seed, unrelated, "part_of")
    results = _search(embedder)
    ids = [r["episode_id"] for r in results]
    assert neighbor in ids
    assert unrelated not in ids
    item = results[ids.index(neighbor)]
    assert item["source"] == "associative"
    assert not item["score_components"]["vector_candidate"]
    assert not item["score_components"]["lexical_candidate"]
    assert item["score_components"]["cosine"] == pytest.approx(0.5995)
    path = item["graph_paths"][0]
    assert path["seed_episode_id"] == seed
    assert path["edges"][0]["relation_id"] == rid
    assert path["edges"][0]["description"] == "preserved evidence"
    assert len(ids) == len(set(ids))


def test_graph_direction_types_evidence_cycles_and_bounds(tmp_project):
    _, db = _fixture(tmp_project)
    with sqlite3.connect(db) as conn:
        _edge(conn, 1, 2, "part_of")
        _edge(conn, 1, 3, "derived_from", strength=0.5)
        _edge(conn, 1, 4, "unknown_predicate")
        _edge(conn, 1, 5, valid_to="2026-01-02")
        _edge(conn, 2, 6)
        _edge(conn, 2, 7)
        _edge(conn, 6, 1)
        eligible = set(range(1, 8))
        paths = expand_episode_candidates(conn, {1: 1.0}, eligible)
        assert paths[2].confidence == 0.8
        assert paths[3].confidence == 0.4
        direct_evidence = expand_episode_candidates(conn, {1: 1.0, 2: 0.95}, eligible)
        assert direct_evidence[2].confidence == 0.8
        assert direct_evidence[2].seed_id == 1
        assert 4 not in paths and 5 not in paths
        reverse = expand_episode_candidates(conn, {2: 1.0}, eligible, max_hops=1)
        assert reverse[1].confidence == 0.4
        assert reverse[1].edges[0]["direction"] == "incoming"
        assert reverse[1].edges[0]["src_id"] == 1
        assert 1 not in expand_episode_candidates(conn, {3: 1.0}, eligible)
        assert (
            len(expand_episode_candidates(conn, {1: 1.0}, eligible, fan_limit=1, max_candidates=1))
            == 1
        )
        assert 7 not in expand_episode_candidates(conn, {1: 1.0}, {1, 7})
        assert expand_episode_candidates(conn, {1: 1.0}, eligible, max_candidates=0) == {}


def test_missing_vector_is_not_seed_similarity(tmp_project):
    embedder, db = _fixture(tmp_project)
    seed = _write(tmp_project, embedder, "seed", 0.9)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO episodes(id,content,kind,valid_from) "
            "VALUES(10,'missing embedding','facts','2026-01-01')"
        )
        _edge(conn, seed, 10)
    assert all(r["episode_id"] != 10 for r in _search(embedder))
    conn = _open_vec(tmp_project / "data/test_char/vdb_memories.db")
    assert episode_cosines(conn, embedder.encode_query.return_value, set()) == {}
    assert episode_cosines(conn, embedder.encode_query.return_value, {10}) == {}
    conn.close()


def test_blank_and_invalid_limit(tmp_project):
    embedder, _ = _fixture(tmp_project)
    assert _search(embedder, "   ") == []
    with pytest.raises(ValueError):
        _search(embedder, limit=0)
