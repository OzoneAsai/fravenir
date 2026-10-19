"""Read-only hybrid episode retrieval with bounded graph/context re-ranking."""

from __future__ import annotations

import math
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from fravenir.core.activation import base_activation
from fravenir.core.graph import (
    build_subgraph_from_seeds,
    expand_episode_candidates,
    fan_out_of,
    reach_episodes,
    s_ji,
)
from fravenir.core.lexical import lexical_scores
from fravenir.core.self_cue import self_cue_terms
from fravenir.embedding import Embedder
from fravenir.schemas.config import AppConfig
from fravenir.storage import paths
from fravenir.storage.vector import (
    episode_cosines,
    search_entities_by_vector,
    search_episodes_by_vector,
)


def _open_readonly(db_path: str) -> sqlite3.Connection:
    return sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)


def _open_vdb(db_path: str) -> sqlite3.Connection:
    import sqlite_vec

    conn = _open_readonly(db_path)
    try:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
    except (sqlite3.Error, OSError):
        conn.close()
        raise
    return conn


def memory_search(
    query: str,
    limit: int = 5,
    kind_filter: list[str] | None = None,
    min_importance: int = 1,
    include_archived: bool = False,
    include_suppressed: bool = False,
    *,
    character_id: str,
    config: AppConfig,
    embedder: Embedder,
) -> list[dict[str, object]]:
    """Retrieve by query evidence; use context only within its bounded budget.

    Search impressions never update access history or activation counters.
    Explicit memory_explore accesses remain available to ACT-R. Historical
    search rows are preserved but excluded from search's recall signal.
    """
    if limit < 1:
        raise ValueError("limit must be >= 1")
    if not query.strip():
        return []
    actr, retrieval = config.act_r, config.search
    top_k = max(limit * 4, 20)
    kv = _open_readonly(str(paths.kv_db_path(character_id)))
    vdb = None
    try:
        kv.row_factory = sqlite3.Row
        # One SQLite read transaction gives filters, graph and contents a common snapshot.
        kv.execute("BEGIN")
        rows = kv.execute(
            "SELECT id, content, kind, importance, valid_from, valid_to, supersedes, "
            "is_suppressed, created_at FROM episodes ORDER BY id"
        ).fetchall()
        episodes = {
            int(r["id"]): dict(r)
            for r in rows
            if (include_archived or r["valid_to"] is None)
            and (
                not r["is_suppressed"] or (include_suppressed and r["importance"] >= min_importance)
            )
            and (not kind_filter or r["kind"] in kind_filter)
        }
        if not episodes:
            return []
        eligible = set(episodes)
        lexical = lexical_scores(query, {ep: str(r["content"]) for ep, r in episodes.items()})
        lex_ids = set(sorted(lexical, key=lambda ep: (-lexical[ep], ep))[:top_k])
        query_vector = embedder.encode_query(query)
        vdb = _open_vdb(str(paths.vdb_memories_path(character_id)))
        vdb.execute("BEGIN")
        # Filtered-out nearest neighbors must not consume the candidate window.
        k = min(top_k, 4096)
        while True:
            hits = search_episodes_by_vector(vdb, query_vector, k)
            direct = [ep for ep, _ in hits if ep in eligible][:top_k]
            if len(direct) >= top_k or len(hits) < k or k == 4096:
                break
            k = min(k * 2, 4096)
        direct_ids = set(direct)
        initial_ids = direct_ids | lex_ids
        cosine = episode_cosines(vdb, query_vector, initial_ids)

        def relevance(ep: int) -> float:
            weight = retrieval.lexical_weight
            return (1 - weight) * cosine.get(ep, 0.0) + weight * lexical.get(ep, 0.0)

        seeds = sorted(initial_ids, key=lambda ep: (-relevance(ep), ep))
        seed_scores = {
            ep: relevance(ep) for ep in seeds[: retrieval.graph_seed_limit] if relevance(ep) > 0
        }
        graph_paths = expand_episode_candidates(
            kv,
            seed_scores,
            eligible,
            max_hops=retrieval.graph_max_hops,
            fan_limit=retrieval.graph_fan_limit,
            max_candidates=retrieval.graph_max_candidates,
        )

        # Retain entity/self-hub recall for compatibility, but do not let entity
        # activation replace the candidate episode's query evidence.
        entity_ids: list[int] = []
        ent_path = paths.vdb_entities_path(character_id)
        if ent_path.exists():
            entities = _open_vdb(str(ent_path))
            try:
                entity_ids = [
                    ep
                    for ep, _ in search_entities_by_vector(
                        entities, embedder.encode_topic(query), 10
                    )
                ]
                entity_ids = [
                    ep
                    for ep in entity_ids
                    if kv.execute(
                        "SELECT 1 FROM entities WHERE id=? AND valid_to IS NULL", (ep,)
                    ).fetchone()
                ]
            finally:
                entities.close()
        self_ids = (
            _fetch_self_entity_ids(kv)
            if any(term and term in query for term in self_cue_terms(kv))
            else []
        )
        assoc, assoc_ids, boost_ids = _graph_contributions(
            kv,
            list(dict.fromkeys(entity_ids + self_ids)),
            s_max=actr.s_max,
            boost_seed_ids=set(self_ids),
            boost_beta=actr.self_boost_beta,
        )
        candidates = initial_ids | set(graph_paths) | (assoc_ids & eligible)
        cosine.update(episode_cosines(vdb, query_vector, candidates - initial_ids))
        now = datetime.now(UTC)
        ranked: list[dict[str, object]] = []
        # A neighbor needs its own query evidence; a path alone cannot promote
        # an unrelated high-degree hub. The floor scales with the query's seeds.
        graph_floor = max(seed_scores.values(), default=0.0) / 2
        for ep in sorted(candidates):
            row = episodes[ep]
            rel = relevance(ep)
            if ep not in initial_ids and ep not in assoc_ids and rel < graph_floor:
                continue
            base = base_activation(
                kv,
                "episode",
                ep,
                actr.base_decay,
                now,
                actr.access_history_limit,
                include_search_results=False,
            )
            activation = base + assoc.get(ep, 0.0)
            recall = (math.tanh(base / 2) + 1) / 2
            importance = max(0.0, min((int(row["importance"]) - 1) / 2, 1.0))
            path = graph_paths.get(ep)
            graph = min(rel, path.confidence) if path else 0.0
            entity_context = min(assoc.get(ep, 0.0) / max(actr.s_max, 1.0), 1.0)
            graph = max(graph, entity_context * rel)
            self_context = float(ep in boost_ids) * actr.self_boost_beta
            context = (
                retrieval.context_budget
                * (recall + actr.alpha_importance * importance + graph + self_context)
                / (2 + actr.alpha_importance + actr.self_boost_beta)
            )
            source = (
                "self_boost"
                if ep in boost_ids
                else ("direct" if ep in direct_ids or ep in lex_ids else "associative")
            )
            ranked.append(
                {
                    "episode_id": ep,
                    "content": row["content"],
                    "kind": row["kind"],
                    "importance": row["importance"],
                    "activation": activation,
                    "score": rel + context,
                    "valid_from": row["valid_from"],
                    "valid_to": row["valid_to"],
                    "supersedes": row["supersedes"],
                    "created_at": row["created_at"],
                    "source": source,
                    "score_components": {
                        "cosine": cosine.get(ep, 0.0),
                        "has_vector": ep in cosine,
                        "lexical": lexical.get(ep, 0.0),
                        "relevance": rel,
                        "base_activation": base,
                        "association_activation": assoc.get(ep, 0.0),
                        "bounded_activation": recall,
                        "normalized_importance": importance,
                        "graph": graph,
                        "context": context,
                        "vector_candidate": ep in direct_ids,
                        "lexical_candidate": ep in lex_ids,
                        "graph_candidate": path is not None,
                    },
                    "graph_paths": [
                        {
                            "seed_episode_id": path.seed_id,
                            "confidence": path.confidence,
                            "edges": list(path.edges),
                        }
                    ]
                    if path
                    else [],
                }
            )
        ranked.sort(key=lambda row: (-float(str(row["score"])), int(str(row["episode_id"]))))
        results = ranked[:limit]
        for result in results:
            result["episode_sources"] = [
                dict(row)
                for row in kv.execute(
                    "SELECT source_type, source_id, source_revision, relation, actor_id, "
                    "created_at FROM episode_sources WHERE episode_id=? "
                    "ORDER BY source_type,source_id,relation",
                    (result["episode_id"],),
                )
            ]
        return results
    finally:
        if vdb is not None:
            vdb.close()
        kv.close()


def _fetch_self_entity_ids(conn: sqlite3.Connection) -> list[int]:
    """is_self=1 かつ valid_to IS NULL の entity ids を返す。"""
    rows = conn.execute("SELECT id FROM entities WHERE is_self = 1 AND valid_to IS NULL").fetchall()
    return [int(r[0]) for r in rows]


def _graph_contributions(
    conn: sqlite3.Connection,
    seed_entity_ids: list[int],
    *,
    s_max: float,
    boost_seed_ids: set[int] | None = None,
    boost_beta: float = 0.0,
) -> tuple[dict[int, float], set[int], set[int]]:
    """seed entities から 2ホップ辿り、到達 episode ごとの Σ W_j·S_ji を集計する。

    boost_seed_ids に含まれる seed については、辿った先の episode に対して
    追加で boost_beta を加算する（設計書 §5.4 自己ブースト）。

    Returns:
        (episode_id -> 活性化加算値, reached_episode_ids, boost_reached_episode_ids)
    """
    if not seed_entity_ids:
        return {}, set(), set()

    graph = build_subgraph_from_seeds(conn, seed_entity_ids, max_hops=2)
    if graph.number_of_edges() == 0:
        return {}, set(), set()

    weight = 1.0 / len(seed_entity_ids)
    contrib: dict[int, float] = {}
    reached: set[int] = set()
    boost_reached: set[int] = set()

    for seed_id in seed_entity_ids:
        fan_j = fan_out_of(conn, seed_id)
        strength = s_ji(fan_j, s_max)
        if strength <= 0:
            continue
        episodes = reach_episodes(graph, seed_id)
        reached.update(episodes)
        for ep_id in episodes:
            contrib[ep_id] = contrib.get(ep_id, 0.0) + weight * strength
            if boost_seed_ids and seed_id in boost_seed_ids:
                contrib[ep_id] += boost_beta
                boost_reached.add(ep_id)

    return contrib, reached, boost_reached
