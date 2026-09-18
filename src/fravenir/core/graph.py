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
from datetime import UTC, datetime
from typing import Literal

import networkx as nx

from fravenir.storage import paths


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
              AND dst_type IN ('entity', 'episode')
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
          AND dst_type IN ('entity', 'episode')
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

# ---------------------------------------------------------------------------
# Generic graph surface for the collaborative board.
#
# The original helpers above deliberately stay entity/episode-specific because
# ACT-R search semantics depend on those node classes. The API below is a
# separate, generic projection over the same relations table. It lets agents
# inspect and curate board + memory topology without changing the ACT-R path.
# ---------------------------------------------------------------------------

NodeType = Literal["episode", "entity", "space", "thread", "post"]
Direction = Literal["incoming", "outgoing", "both"]

RESERVED_PREDICATES = frozenset(
    {
        "contains",
        "reply_to",
        "part_of",
        "about",
        "mentions",
        "related_to",
        "depends_on",
        "supports",
        "contradicts",
        "evidence_for",
        "derived_from",
        "supersedes",
        "resolves",
    }
)


def _graph_connect(character_id: str) -> sqlite3.Connection:
    conn = sqlite3.connect(paths.kv_db_path(character_id))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _graph_now() -> str:
    return datetime.now(UTC).isoformat()


_RELATION_COLUMNS = (
    "id",
    "src_type",
    "src_id",
    "dst_type",
    "dst_id",
    "predicate",
    "strength",
    "fan_out",
    "description",
    "valid_from",
    "valid_to",
    "supersedes",
    "created_at",
)


def _relation_to_dict(row: sqlite3.Row | tuple[object, ...]) -> dict[str, object]:
    if isinstance(row, sqlite3.Row):
        return dict(row)
    if len(row) != len(_RELATION_COLUMNS):
        raise ValueError("unexpected relations row shape")
    return dict(zip(_RELATION_COLUMNS, row, strict=True))


def _assert_node_type(node_type: str) -> NodeType:
    if node_type not in {"episode", "entity", "space", "thread", "post"}:
        raise ValueError(f"unsupported node type: {node_type!r}")
    return node_type  # type: ignore[return-value]


def _node_exists(conn: sqlite3.Connection, node_type: NodeType, node_id: int) -> bool:
    table = {
        "episode": "episodes",
        "entity": "entities",
        "space": "spaces",
        "thread": "threads",
        "post": "posts",
    }[node_type]
    return conn.execute(
        f"SELECT 1 FROM {table} WHERE id = ?",  # noqa: S608 - table is a closed mapping.
        (node_id,),
    ).fetchone() is not None


def _get_graph_node_in_conn(
    conn: sqlite3.Connection,
    node_type: NodeType,
    node_id: int,
) -> dict[str, object]:
    if node_type == "episode":
        row = conn.execute(
            """SELECT id, content, kind, importance, valid_from, valid_to,
                      supersedes, derived_from, session_id, is_suppressed, created_at
               FROM episodes WHERE id = ?""",
            (node_id,),
        ).fetchone()
    elif node_type == "entity":
        row = conn.execute(
            """SELECT id, canonical_name, entity_type, description, is_self,
                      self_weight, decay_rate, valid_from, valid_to, supersedes,
                      curated_at, created_at
               FROM entities WHERE id = ?""",
            (node_id,),
        ).fetchone()
    elif node_type == "space":
        row = conn.execute(
            """SELECT id, slug, name, description, created_by, created_at
               FROM spaces WHERE id = ?""",
            (node_id,),
        ).fetchone()
    elif node_type == "thread":
        row = conn.execute(
            """SELECT id, space_id, title, status, created_by, version,
                      created_at, updated_at
               FROM threads WHERE id = ?""",
            (node_id,),
        ).fetchone()
    else:
        row = conn.execute(
            """SELECT id, thread_id, parent_post_id, author_id, kind, body,
                      revision, created_at, edited_at
               FROM posts WHERE id = ?""",
            (node_id,),
        ).fetchone()
    if row is None:
        raise ValueError(f"{node_type} {node_id} not found")
    result = dict(row)
    result["type"] = node_type
    return result


def graph_get_node(
    *,
    character_id: str,
    node_type: NodeType,
    node_id: int,
) -> dict[str, object]:
    node_type = _assert_node_type(node_type)
    conn = _graph_connect(character_id)
    try:
        return _get_graph_node_in_conn(conn, node_type, node_id)
    finally:
        conn.close()


def link_relation_in_conn(
    conn: sqlite3.Connection,
    *,
    src_type: NodeType,
    src_id: int,
    dst_type: NodeType,
    dst_id: int,
    predicate: str,
    strength: float = 1.0,
    description: str | None = None,
    allow_custom_predicate: bool = False,
) -> tuple[dict[str, object], bool]:
    """Insert one active relation, deduplicating the same edge + predicate."""
    src_type = _assert_node_type(src_type)
    dst_type = _assert_node_type(dst_type)
    predicate = predicate.strip()
    if not predicate:
        raise ValueError("predicate must not be empty")
    if predicate not in RESERVED_PREDICATES and not allow_custom_predicate:
        raise ValueError(
            f"predicate {predicate!r} is not reserved; "
            "set allow_custom_predicate=true explicitly"
        )
    if strength <= 0:
        raise ValueError("strength must be > 0")
    if src_type == dst_type and src_id == dst_id:
        raise ValueError("self-loop relations are not allowed")
    if not _node_exists(conn, src_type, src_id):
        raise ValueError(f"{src_type} {src_id} not found")
    if not _node_exists(conn, dst_type, dst_id):
        raise ValueError(f"{dst_type} {dst_id} not found")

    existing = conn.execute(
        """SELECT * FROM relations
           WHERE src_type = ? AND src_id = ? AND dst_type = ? AND dst_id = ?
             AND predicate = ? AND valid_to IS NULL
           ORDER BY id LIMIT 1""",
        (src_type, src_id, dst_type, dst_id, predicate),
    ).fetchone()
    if existing is not None:
        return _relation_to_dict(existing), False

    cur = conn.execute(
        """INSERT INTO relations
            (src_type, src_id, dst_type, dst_id, predicate, strength,
             description, valid_from)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            src_type,
            src_id,
            dst_type,
            dst_id,
            predicate,
            strength,
            description,
            _graph_now(),
        ),
    )
    row = conn.execute(
        "SELECT * FROM relations WHERE id = ?", (cur.lastrowid,)
    ).fetchone()
    assert row is not None
    return _relation_to_dict(row), True


def graph_link(
    *,
    character_id: str,
    src_type: NodeType,
    src_id: int,
    dst_type: NodeType,
    dst_id: int,
    predicate: str,
    strength: float = 1.0,
    description: str | None = None,
    allow_custom_predicate: bool = False,
) -> dict[str, object]:
    conn = _graph_connect(character_id)
    try:
        conn.execute("BEGIN IMMEDIATE")
        relation, created = link_relation_in_conn(
            conn,
            src_type=src_type,
            src_id=src_id,
            dst_type=dst_type,
            dst_id=dst_id,
            predicate=predicate,
            strength=strength,
            description=description,
            allow_custom_predicate=allow_custom_predicate,
        )
        conn.commit()
        relation["created"] = created
        return relation
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def graph_neighbors(
    *,
    character_id: str,
    node_type: NodeType,
    node_id: int,
    predicates: list[str] | None = None,
    direction: Direction = "both",
    include_archived: bool = False,
    limit: int = 100,
) -> dict[str, object]:
    node_type = _assert_node_type(node_type)
    if direction not in ("incoming", "outgoing", "both"):
        raise ValueError(f"invalid direction: {direction!r}")
    if not 1 <= limit <= 500:
        raise ValueError("limit must be 1-500")

    conn = _graph_connect(character_id)
    try:
        node = _get_graph_node_in_conn(conn, node_type, node_id)
        clauses: list[str] = []
        args: list[object] = []
        if direction in ("outgoing", "both"):
            clauses.append("(src_type = ? AND src_id = ?)")
            args.extend([node_type, node_id])
        if direction in ("incoming", "both"):
            clauses.append("(dst_type = ? AND dst_id = ?)")
            args.extend([node_type, node_id])
        where = "(" + " OR ".join(clauses) + ")"
        if not include_archived:
            where += " AND valid_to IS NULL"
        if predicates:
            clean = [p.strip() for p in predicates if p.strip()]
            if not clean:
                raise ValueError("predicates must contain at least one non-empty value")
            marks = ",".join("?" for _ in clean)
            where += f" AND predicate IN ({marks})"
            args.extend(clean)
        args.append(limit)

        rows = conn.execute(
            f"""SELECT * FROM relations
                WHERE {where}
                ORDER BY id DESC
                LIMIT ?""",  # noqa: S608 - dynamic fragments are placeholders/closed values.
            args,
        ).fetchall()

        neighbors: list[dict[str, object]] = []
        for row in rows:
            relation = dict(row)
            if relation["src_type"] == node_type and int(relation["src_id"]) == node_id:
                other_type = _assert_node_type(str(relation["dst_type"]))
                other_id = int(relation["dst_id"])
                edge_direction = "outgoing"
            else:
                other_type = _assert_node_type(str(relation["src_type"]))
                other_id = int(relation["src_id"])
                edge_direction = "incoming"
            neighbors.append(
                {
                    "relation": relation,
                    "direction": edge_direction,
                    "node": _get_graph_node_in_conn(conn, other_type, other_id),
                }
            )
        return {"node": node, "neighbors": neighbors, "count": len(neighbors)}
    finally:
        conn.close()


def graph_invalidate_relation(
    *,
    character_id: str,
    relation_id: int,
) -> dict[str, object]:
    conn = _graph_connect(character_id)
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM relations WHERE id = ?", (relation_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"relation {relation_id} not found")
        changed = row["valid_to"] is None
        if changed:
            conn.execute(
                "UPDATE relations SET valid_to = ? WHERE id = ?",
                (_graph_now(), relation_id),
            )
        conn.commit()
        current = conn.execute(
            "SELECT * FROM relations WHERE id = ?", (relation_id,)
        ).fetchone()
        assert current is not None
        result = dict(current)
        result["changed"] = changed
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def graph_search(
    *,
    character_id: str,
    query: str,
    limit: int = 30,
) -> list[dict[str, object]]:
    """Lexically search all first-class graph node kinds.

    Semantic memory retrieval remains the job of memory_search; this helper is
    for graph navigation and board organization.
    """
    query = query.strip()
    if not query:
        raise ValueError("query must not be empty")
    if not 1 <= limit <= 100:
        raise ValueError("limit must be 1-100")
    pattern = f"%{query}%"

    conn = _graph_connect(character_id)
    try:
        rows = conn.execute(
            """SELECT 'entity' AS node_type, id AS node_id,
                      canonical_name AS label, description AS detail
               FROM entities
               WHERE canonical_name LIKE ? OR description LIKE ?
               UNION ALL
               SELECT 'episode', id, substr(content, 1, 120), content
               FROM episodes
               WHERE content LIKE ?
               UNION ALL
               SELECT 'space', id, name, description
               FROM spaces
               WHERE name LIKE ? OR description LIKE ?
               UNION ALL
               SELECT 'thread', id, title, NULL
               FROM threads
               WHERE title LIKE ?
               UNION ALL
               SELECT 'post', id, substr(body, 1, 120), body
               FROM posts
               WHERE body LIKE ?
               LIMIT ?""",
            (pattern, pattern, pattern, pattern, pattern, pattern, pattern, limit),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()

