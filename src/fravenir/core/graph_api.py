"""Generic graph API for human/AI organization.

This layer exposes the relation graph without changing the ACT-R/search-specific
helpers in core.graph. It deliberately supports only known local node types.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import Literal

from fravenir.storage.paths import kv_db_path
from fravenir.storage.sqlite_init import init_kv

NodeType = Literal["episode", "entity", "thread", "post"]
Direction = Literal["incoming", "outgoing", "both"]

_RESERVED_PREDICATES = {
    "contains",
    "reply_to",
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
    "part_of",
    "likes",
}

_TABLE_BY_NODE_TYPE: dict[str, str] = {
    "episode": "episodes",
    "entity": "entities",
    "thread": "threads",
    "post": "posts",
}


def _connect(character_id: str) -> sqlite3.Connection:
    path = kv_db_path(character_id)
    init_kv(path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _ensure_node(conn: sqlite3.Connection, node_type: NodeType, node_id: int) -> None:
    table = _TABLE_BY_NODE_TYPE[node_type]
    row = conn.execute(f"SELECT 1 FROM {table} WHERE id = ?", (node_id,)).fetchone()
    if row is None:
        raise ValueError(f"{node_type} with id={node_id} not found")


def _node_payload(
    conn: sqlite3.Connection,
    node_type: NodeType,
    node_id: int,
) -> dict[str, object]:
    _ensure_node(conn, node_type, node_id)
    if node_type == "entity":
        row = conn.execute(
            """
            SELECT id, canonical_name, entity_type, description, is_self,
                   valid_from, valid_to
            FROM entities WHERE id = ?
            """,
            (node_id,),
        ).fetchone()
        assert row is not None
        return {
            "type": node_type,
            "id": node_id,
            "name": row["canonical_name"],
            "entity_type": row["entity_type"],
            "description": row["description"],
            "is_self": bool(row["is_self"]),
            "valid_from": row["valid_from"],
            "valid_to": row["valid_to"],
        }
    if node_type == "episode":
        row = conn.execute(
            """
            SELECT id, content, kind, importance, valid_from, valid_to,
                   is_suppressed
            FROM episodes WHERE id = ?
            """,
            (node_id,),
        ).fetchone()
        assert row is not None
        return {
            "type": node_type,
            "id": node_id,
            "content": row["content"],
            "kind": row["kind"],
            "importance": row["importance"],
            "valid_from": row["valid_from"],
            "valid_to": row["valid_to"],
            "is_suppressed": bool(row["is_suppressed"]),
        }
    if node_type == "thread":
        row = conn.execute(
            """
            SELECT id, space_id, title, status, version, created_at, updated_at
            FROM threads WHERE id = ?
            """,
            (node_id,),
        ).fetchone()
        assert row is not None
        return {"type": node_type, **dict(row)}

    row = conn.execute(
        """
        SELECT id, thread_id, parent_post_id, author_id, kind, body,
               revision, created_at, edited_at
        FROM posts WHERE id = ?
        """,
        (node_id,),
    ).fetchone()
    assert row is not None
    return {"type": node_type, **dict(row)}


def get_node(
    *,
    character_id: str,
    node_type: NodeType,
    node_id: int,
) -> dict[str, object]:
    conn = _connect(character_id)
    try:
        return _node_payload(conn, node_type, node_id)
    finally:
        conn.close()


def get_neighbors(
    *,
    character_id: str,
    node_type: NodeType,
    node_id: int,
    direction: Direction = "both",
    predicates: list[str] | None = None,
    include_archived: bool = False,
    limit: int = 100,
) -> dict[str, object]:
    if not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")

    conn = _connect(character_id)
    try:
        node = _node_payload(conn, node_type, node_id)
        clauses = ["1 = 1"]
        params: list[object] = []

        if not include_archived:
            clauses.append("valid_to IS NULL")
        if predicates:
            placeholders = ",".join("?" for _ in predicates)
            clauses.append(f"predicate IN ({placeholders})")
            params.extend(predicates)

        endpoint: str
        if direction == "outgoing":
            endpoint = "src_type = ? AND src_id = ?"
            params.extend([node_type, node_id])
        elif direction == "incoming":
            endpoint = "dst_type = ? AND dst_id = ?"
            params.extend([node_type, node_id])
        else:
            endpoint = "((src_type = ? AND src_id = ?) OR (dst_type = ? AND dst_id = ?))"
            params.extend([node_type, node_id, node_type, node_id])

        clauses.append(endpoint)
        rows = conn.execute(
            f"""
            SELECT id, src_type, src_id, dst_type, dst_id, predicate,
                   strength, description, valid_from, valid_to
            FROM relations
            WHERE {" AND ".join(clauses)}
            ORDER BY id
            LIMIT ?
            """,
            (*params, limit),
        ).fetchall()

        neighbors: list[dict[str, object]] = []
        for row in rows:
            src = (str(row["src_type"]), int(row["src_id"]))
            dst = (str(row["dst_type"]), int(row["dst_id"]))
            current = (node_type, node_id)
            other = dst if src == current else src
            if other[0] not in _TABLE_BY_NODE_TYPE:
                payload: dict[str, object] = {"type": other[0], "id": other[1]}
            else:
                payload = _node_payload(
                    conn,
                    other[0],  # type: ignore[arg-type]
                    other[1],
                )
            neighbors.append(
                {
                    "relation_id": int(row["id"]),
                    "predicate": row["predicate"],
                    "direction": "outgoing" if src == current else "incoming",
                    "strength": row["strength"],
                    "description": row["description"],
                    "valid_from": row["valid_from"],
                    "valid_to": row["valid_to"],
                    "node": payload,
                }
            )

        return {"node": node, "neighbors": neighbors}
    finally:
        conn.close()


def add_relation(
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
    clean_predicate = predicate.strip()
    if not clean_predicate:
        raise ValueError("predicate must not be empty")
    if not allow_custom_predicate and clean_predicate not in _RESERVED_PREDICATES:
        raise ValueError(f"unsupported predicate: {clean_predicate}")
    if not 0.0 <= strength <= 1.0:
        raise ValueError("strength must be between 0.0 and 1.0")
    if src_type == dst_type and src_id == dst_id:
        raise ValueError("self-referential relations are not allowed")

    conn = _connect(character_id)
    try:
        _ensure_node(conn, src_type, src_id)
        _ensure_node(conn, dst_type, dst_id)
        existing = conn.execute(
            """
            SELECT id FROM relations
            WHERE src_type = ? AND src_id = ?
              AND dst_type = ? AND dst_id = ?
              AND predicate = ? AND valid_to IS NULL
            LIMIT 1
            """,
            (src_type, src_id, dst_type, dst_id, clean_predicate),
        ).fetchone()
        if existing is not None:
            raise ValueError(f"active relation already exists: {int(existing['id'])}")

        now = datetime.now(UTC).isoformat()
        cur = conn.execute(
            """
            INSERT INTO relations
                (src_type, src_id, dst_type, dst_id, predicate, strength,
                 description, valid_from)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                src_type,
                src_id,
                dst_type,
                dst_id,
                clean_predicate,
                strength,
                description,
                now,
            ),
        )
        relation_id = cur.lastrowid
        if relation_id is None:
            raise RuntimeError("sqlite insert did not return a relation id")
        conn.commit()
        return {
            "relation_id": int(relation_id),
            "src_type": src_type,
            "src_id": src_id,
            "dst_type": dst_type,
            "dst_id": dst_id,
            "predicate": clean_predicate,
            "strength": strength,
            "valid_from": now,
        }
    finally:
        conn.close()


def invalidate_relation(
    *,
    character_id: str,
    relation_id: int,
) -> dict[str, object]:
    conn = _connect(character_id)
    try:
        row = conn.execute(
            "SELECT valid_to FROM relations WHERE id = ?",
            (relation_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"relation not found: {relation_id}")
        if row["valid_to"] is not None:
            return {"relation_id": relation_id, "valid_to": row["valid_to"], "changed": False}

        now = datetime.now(UTC).isoformat()
        conn.execute(
            "UPDATE relations SET valid_to = ? WHERE id = ?",
            (now, relation_id),
        )
        conn.commit()
        return {"relation_id": relation_id, "valid_to": now, "changed": True}
    finally:
        conn.close()
