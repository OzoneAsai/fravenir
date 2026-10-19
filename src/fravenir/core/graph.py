r"""Graph traversal helpers (Phase3+).

memory_search の Step 3 で使う 2ホップ探索と連想強度 $S_{ji}$ 計算を提供する。

設計書 §5.3 / §6.1 Step 3 に対応:
- relations は valid_to IS NULL のみを辿る（論理削除されたエッジは無視）
- fan_out は「ノード j から出る有効なエッジ数」
- $S_{ji} = S_{\max} - \ln(\mathrm{fan}_j)$

NetworkX を使う理由は 2ホップ BFS を素直に書けることと fan 計算 API。
全relations をメモリ常駐させず、seed とその近傍だけ SQL で引いて部分グラフを組む。
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass

import networkx as nx


@dataclass(frozen=True)
class RelationPolicy:
    """Traversal confidence by direction, without rewriting the stored relation."""

    outgoing: float
    incoming: float


# Hierarchy is not symmetric: going up collects context; going down selects one
# detail among many. Derivation follows evidence toward its source, never every
# derivative of a source. Unknown predicates are intentionally not traversed.
_SEARCH_RELATIONS = {
    "part_of": RelationPolicy(0.8, 0.4),
    "related_to": RelationPolicy(0.6, 0.6),
    "derived_from": RelationPolicy(0.8, 0.0),
}


@dataclass(frozen=True)
class EpisodePath:
    seed_id: int
    confidence: float
    edges: tuple[dict[str, object], ...]


def expand_episode_candidates(
    conn: sqlite3.Connection,
    seeds: dict[int, float],
    eligible_ids: set[int],
    *,
    max_hops: int = 2,
    fan_limit: int = 12,
    max_candidates: int = 64,
) -> dict[int, EpisodePath]:
    """Bounded, typed episode traversal, preserving edge direction and evidence.

    Keep the strongest path per node rather than accumulating arbitrary hub/cycle
    counts. Neither an archived/suppressed node nor an excluded kind can relay a
    path. Candidate confidence still requires query relevance at ranking time.
    """
    if max_candidates <= 0 or not seeds:
        return {}
    frontier = {
        ep: EpisodePath(ep, score, ())
        for ep, score in seeds.items()
        if ep in eligible_ids and score > 0
    }
    best = dict(frontier)
    reached: dict[int, EpisodePath] = {}
    for _ in range(min(max_hops, 2)):
        following: dict[int, EpisodePath] = {}
        for node, path in sorted(frontier.items(), key=lambda p: (-p[1].confidence, p[0])):
            rows = conn.execute(
                """SELECT id, src_id, dst_id, predicate, strength, description,
                          valid_from, supersedes
                   FROM relations
                   WHERE valid_to IS NULL AND src_type='episode' AND dst_type='episode'
                     AND (src_id=? OR dst_id=?)
                   ORDER BY strength DESC, id ASC""",
                (node, node),
            )
            neighbors: list[tuple[float, int, dict[str, object]]] = []
            for rid, src, dst, predicate, strength, description, valid_from, supersedes in rows:
                policy = _SEARCH_RELATIONS.get(predicate)
                if policy is None or src not in eligible_ids or dst not in eligible_ids:
                    continue
                outgoing = src == node
                weight = policy.outgoing if outgoing else policy.incoming
                confidence = path.confidence * weight * max(0.0, min(float(strength), 1.0))
                if confidence <= 0:
                    continue
                edge: dict[str, object] = {
                    "relation_id": rid,
                    "src_type": "episode",
                    "src_id": src,
                    "dst_type": "episode",
                    "dst_id": dst,
                    "predicate": predicate,
                    "strength": strength,
                    "description": description,
                    "valid_from": valid_from,
                    "supersedes": supersedes,
                    "direction": "outgoing" if outgoing else "incoming",
                }
                neighbors.append((confidence, dst if outgoing else src, edge))
            neighbors.sort(key=lambda item: (-item[0], item[1], int(str(item[2]["relation_id"]))))
            for confidence, neighbor, edge in neighbors[:fan_limit]:
                if neighbor == path.seed_id:
                    continue
                if neighbor not in reached and len(reached) >= max_candidates:
                    continue
                candidate = EpisodePath(path.seed_id, confidence, (*path.edges, edge))
                evidence = reached.get(neighbor)
                if evidence is None or confidence > evidence.confidence:
                    reached[neighbor] = candidate
                previous = best.get(neighbor)
                if previous and previous.confidence >= confidence:
                    continue
                best[neighbor] = candidate
                following[neighbor] = candidate
        frontier = following
        if not frontier:
            break
    return reached


def build_subgraph_from_seeds(
    conn: sqlite3.Connection,
    seed_entity_ids: list[int],
    max_hops: int = 2,
) -> nx.DiGraph:
    """Seed entities から最大 `max_hops` ホップ以内の有効エッジを持つ部分グラフを構築。

    ノード識別子は `(type, id)` タプル（type は 'entity' または 'episode'）。
    各エッジには `predicate` 属性のみを付与する（fan_out は後段で `fan_out_of` から取得）。
    """
    graph: nx.DiGraph = nx.DiGraph()
    frontier: set[tuple[str, int]] = {("entity", eid) for eid in seed_entity_ids}
    visited: set[tuple[str, int]] = set()

    for _ in range(max_hops):
        if not frontier:
            break
        entity_frontier = [nid for ntype, nid in frontier if ntype == "entity"]
        visited.update(frontier)
        frontier = set()
        if not entity_frontier:
            continue

        placeholders = ",".join("?" * len(entity_frontier))
        # entity を src とする有効エッジのみを展開する（episode は終端）。
        rows = conn.execute(
            f"""
            SELECT src_type, src_id, dst_type, dst_id, predicate
            FROM relations
            WHERE valid_to IS NULL
              AND src_type = 'entity'
              AND src_id IN ({placeholders})
            """,
            entity_frontier,
        ).fetchall()

        for src_type, src_id, dst_type, dst_id, predicate in rows:
            src_node = (src_type, src_id)
            dst_node = (dst_type, dst_id)
            graph.add_edge(src_node, dst_node, predicate=predicate)
            if dst_node not in visited:
                frontier.add(dst_node)

    return graph


def fan_out_of(conn: sqlite3.Connection, entity_id: int) -> int:
    """Entity から出る `valid_to IS NULL` の relations 件数。

    `relations.fan_out` カラムが存在するが、compact 未実行時はその値が
    古いままになりうるため、ライブカウント (COUNT(*)) で精度を確保する。
    """
    row = conn.execute(
        """
        SELECT COUNT(*) FROM relations
        WHERE valid_to IS NULL
          AND src_type = 'entity'
          AND src_id = ?
        """,
        (entity_id,),
    ).fetchone()
    return int(row[0]) if row is not None else 0


def s_ji(fan_j: int, s_max: float) -> float:
    r"""連想強度 $S_{ji} = S_{\max} - \ln(\mathrm{fan}_j)$。

    fan_j=0 は「到達元として使われていない」状況だが、安全のため 1 に丸めて
    ln を安定化する（$S_{ji} = S_{\max}$ になる）。
    """
    safe_fan = max(fan_j, 1)
    value = s_max - math.log(safe_fan)
    return max(value, 0.0)


def reach_episodes(graph: nx.DiGraph, seed_entity_id: int) -> set[int]:
    """Seed entity から 2ホップ以内で到達できる episode の id 集合。"""
    seed_node = ("entity", seed_entity_id)
    if seed_node not in graph:
        return set()
    episodes: set[int] = set()
    for node in nx.descendants(graph, seed_node):
        node_type, node_id = node
        if node_type == "episode":
            episodes.add(int(node_id))
    return episodes
