"""Read-only projection of the typed relation graph for the admin canvas.

Memory nodes form the overview. Board nodes are included only when they are
endpoints of stored relations; no synthetic edges or unreferenced posts are added.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Literal

PREFIXES = {"episode": "ep", "entity": "en", "thread": "th", "post": "po"}


def get_graph(kv_path: Path, scope: Literal["active", "archived", "all"]) -> dict[str, Any]:
    conn = sqlite3.connect(f"{kv_path.resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("BEGIN")  # Nodes and edges must come from the same snapshot.
        relations = conn.execute("SELECT * FROM relations ORDER BY id").fetchall()
        endpoints = {
            (r[f"{side}_type"], r[f"{side}_id"])
            for r in relations
            if scope != "active" or r["valid_to"] is None
            for side in ("src", "dst")
        }
        nodes = []
        for kind, table, field in (
            ("episode", "episodes", "content"),
            ("entity", "entities", "canonical_name"),
            ("thread", "threads", "title"),
            ("post", "posts", "body"),
        ):
            query = f"SELECT * FROM {table}"
            params: tuple[str, ...] = ()
            if kind in ("thread", "post"):
                query += (
                    " WHERE id IN (SELECT src_id FROM relations WHERE src_type = ?"
                    " UNION SELECT dst_id FROM relations WHERE dst_type = ?)"
                )
                params = (kind, kind)
            for row in conn.execute(query + " ORDER BY id", params):
                data = dict(row)
                active = data.get("valid_to") is None
                if kind in ("thread", "post"):
                    if (kind, row["id"]) not in endpoints:
                        continue
                    # The board trash extension is optional on older installations.
                    # Trashed board content stays out of this read-only surface.
                    if data.get("deleted_at") is not None:
                        continue
                    if kind == "thread":
                        parent = conn.execute(
                            "SELECT * FROM spaces WHERE id = ?", (row["space_id"],)
                        ).fetchone()
                        active = row["status"] != "archived"
                    else:
                        parent = conn.execute(
                            "SELECT * FROM threads WHERE id = ?", (row["thread_id"],)
                        ).fetchone()
                        active = parent is not None and parent["status"] != "archived"
                        if parent is not None:
                            space = conn.execute(
                                "SELECT * FROM spaces WHERE id = ?", (parent["space_id"],)
                            ).fetchone()
                            if space is None or dict(space).get("deleted_at") is not None:
                                continue
                    if parent is None or dict(parent).get("deleted_at") is not None:
                        continue
                if scope == "active" and not active:
                    continue
                if scope != "all" and data.get("is_suppressed", False):
                    continue
                text = str(row[field])
                node = {
                    "id": f"{PREFIXES[kind]}_{row['id']}",
                    "label": text[:30] + ("…" if len(text) > 30 else ""),
                    "search_text": text,
                    "type": kind,
                    "is_active": active,
                    "supersedes": data.get("supersedes"),
                }
                for key in ("kind", "importance", "is_suppressed", "entity_type", "is_self"):
                    if key in data:
                        node[key] = (
                            bool(data[key]) if key in ("is_self", "is_suppressed") else data[key]
                        )
                if kind == "entity":
                    node["label"] = text
                nodes.append({"data": node})

        node_ids = {node["data"]["id"] for node in nodes}
        edges = []
        for row in relations:
            if scope == "active" and row["valid_to"] is not None:
                continue
            if row["src_type"] not in PREFIXES or row["dst_type"] not in PREFIXES:
                continue
            source = f"{PREFIXES[row['src_type']]}_{row['src_id']}"
            target = f"{PREFIXES[row['dst_type']]}_{row['dst_id']}"
            if source not in node_ids or target not in node_ids:
                continue
            mentions = (
                row["src_type"] == "episode" and row["dst_type"] == "entity"
                and row["predicate"] == "mentions"
            )
            edges.append({"data": {
                "id": f"{'men' if mentions else 'rel'}_{row['id']}",
                "relation_id": row["id"],
                "source": source,
                "target": target,
                "type": "mentions" if mentions else "relation",
                "predicate": row["predicate"],
                "strength": row["strength"],
                "description": row["description"],
                "is_active": row["valid_to"] is None,
            }})
        return {
            "scope": scope,
            "stats": {"nodes": len(nodes), "edges": len(edges)},
            "elements": {"nodes": nodes, "edges": edges},
        }
    finally:
        conn.close()
