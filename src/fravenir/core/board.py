"""Source-board domain operations.

The board is the human-facing projection of fravenir's source layer. Posts are
source material; later graph/provenance phases may derive memories and summaries
from them without rewriting the original posts.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import Literal

from fravenir.storage.paths import kv_db_path
from fravenir.storage.sqlite_init import init_kv

ActorKind = Literal["human", "agent", "system"]
PostKind = Literal["message", "summary", "decision", "note"]


def _connect(character_id: str) -> sqlite3.Connection:
    path = kv_db_path(character_id)
    init_kv(path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _actor_id(
    conn: sqlite3.Connection,
    *,
    kind: ActorKind,
    display_name: str,
    external_subject: str | None,
) -> int:
    if not display_name.strip():
        raise ValueError("display_name must not be empty")
    if external_subject is not None:
        row = conn.execute(
            "SELECT id FROM actors WHERE external_subject = ? LIMIT 1",
            (external_subject,),
        ).fetchone()
        if row is not None:
            return int(row["id"])
    else:
        row = conn.execute(
            "SELECT id FROM actors"
            " WHERE kind = ? AND display_name = ? AND external_subject IS NULL"
            " LIMIT 1",
            (kind, display_name),
        ).fetchone()
        if row is not None:
            return int(row["id"])

    cur = conn.execute(
        "INSERT INTO actors (kind, display_name, external_subject) VALUES (?, ?, ?)",
        (kind, display_name.strip(), external_subject),
    )
    return int(cur.lastrowid)


def create_space(
    *,
    character_id: str,
    name: str,
    description: str | None = None,
) -> dict[str, object]:
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("space name must not be empty")

    conn = _connect(character_id)
    try:
        cur = conn.execute(
            "INSERT INTO spaces (name, description) VALUES (?, ?)",
            (clean_name, description),
        )
        conn.commit()
        return {
            "space_id": int(cur.lastrowid),
            "name": clean_name,
            "description": description,
        }
    except sqlite3.IntegrityError as exc:
        raise ValueError(f"space already exists: {clean_name}") from exc
    finally:
        conn.close()


def list_spaces(*, character_id: str) -> list[dict[str, object]]:
    conn = _connect(character_id)
    try:
        rows = conn.execute(
            """
            SELECT s.id, s.name, s.description, s.created_at,
                   COUNT(t.id) AS thread_count
            FROM spaces s
            LEFT JOIN threads t ON t.space_id = s.id
            GROUP BY s.id
            ORDER BY s.name COLLATE NOCASE
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def create_thread(
    *,
    character_id: str,
    space_id: int,
    title: str,
    author_kind: ActorKind,
    author_display_name: str,
    author_external_subject: str | None = None,
    initial_post: str | None = None,
) -> dict[str, object]:
    clean_title = title.strip()
    if not clean_title:
        raise ValueError("thread title must not be empty")

    conn = _connect(character_id)
    try:
        space = conn.execute("SELECT id FROM spaces WHERE id = ?", (space_id,)).fetchone()
        if space is None:
            raise ValueError(f"space not found: {space_id}")
        actor_id = _actor_id(
            conn,
            kind=author_kind,
            display_name=author_display_name,
            external_subject=author_external_subject,
        )
        now = datetime.now(UTC).isoformat()
        cur = conn.execute(
            """
            INSERT INTO threads
                (space_id, title, created_by, version, created_at, updated_at)
            VALUES (?, ?, ?, 1, ?, ?)
            """,
            (space_id, clean_title, actor_id, now, now),
        )
        thread_id = int(cur.lastrowid)

        post_id: int | None = None
        if initial_post is not None and initial_post.strip():
            pcur = conn.execute(
                """
                INSERT INTO posts
                    (thread_id, author_id, kind, body, revision, created_at)
                VALUES (?, ?, 'message', ?, 1, ?)
                """,
                (thread_id, actor_id, initial_post.strip(), now),
            )
            post_id = int(pcur.lastrowid)
        conn.commit()
        return {
            "thread_id": thread_id,
            "space_id": space_id,
            "title": clean_title,
            "version": 1,
            "initial_post_id": post_id,
        }
    finally:
        conn.close()


def add_post(
    *,
    character_id: str,
    thread_id: int,
    body: str,
    author_kind: ActorKind,
    author_display_name: str,
    author_external_subject: str | None = None,
    kind: PostKind = "message",
    parent_post_id: int | None = None,
) -> dict[str, object]:
    clean_body = body.strip()
    if not clean_body:
        raise ValueError("post body must not be empty")

    conn = _connect(character_id)
    try:
        thread = conn.execute(
            "SELECT id, version FROM threads WHERE id = ?",
            (thread_id,),
        ).fetchone()
        if thread is None:
            raise ValueError(f"thread not found: {thread_id}")

        if parent_post_id is not None:
            parent = conn.execute(
                "SELECT thread_id FROM posts WHERE id = ?",
                (parent_post_id,),
            ).fetchone()
            if parent is None:
                raise ValueError(f"parent post not found: {parent_post_id}")
            if int(parent["thread_id"]) != thread_id:
                raise ValueError("parent post belongs to a different thread")

        actor_id = _actor_id(
            conn,
            kind=author_kind,
            display_name=author_display_name,
            external_subject=author_external_subject,
        )
        now = datetime.now(UTC).isoformat()
        cur = conn.execute(
            """
            INSERT INTO posts
                (thread_id, parent_post_id, author_id, kind, body, revision, created_at)
            VALUES (?, ?, ?, ?, ?, 1, ?)
            """,
            (thread_id, parent_post_id, actor_id, kind, clean_body, now),
        )
        next_version = int(thread["version"]) + 1
        conn.execute(
            "UPDATE threads SET version = ?, updated_at = ? WHERE id = ?",
            (next_version, now, thread_id),
        )
        conn.commit()
        return {
            "post_id": int(cur.lastrowid),
            "thread_id": thread_id,
            "thread_version": next_version,
            "revision": 1,
        }
    finally:
        conn.close()


def get_thread(*, character_id: str, thread_id: int) -> dict[str, object]:
    conn = _connect(character_id)
    try:
        thread = conn.execute(
            """
            SELECT t.id, t.space_id, t.title, t.status, t.version,
                   t.created_at, t.updated_at,
                   a.id AS created_by_id, a.kind AS created_by_kind,
                   a.display_name AS created_by_name
            FROM threads t
            LEFT JOIN actors a ON a.id = t.created_by
            WHERE t.id = ?
            """,
            (thread_id,),
        ).fetchone()
        if thread is None:
            raise ValueError(f"thread not found: {thread_id}")

        posts = conn.execute(
            """
            SELECT p.id, p.parent_post_id, p.kind, p.body, p.revision,
                   p.created_at, p.edited_at,
                   a.id AS author_id, a.kind AS author_kind,
                   a.display_name AS author_name
            FROM posts p
            LEFT JOIN actors a ON a.id = p.author_id
            WHERE p.thread_id = ?
            ORDER BY p.id
            """,
            (thread_id,),
        ).fetchall()
        return {
            "thread": dict(thread),
            "posts": [dict(row) for row in posts],
        }
    finally:
        conn.close()


def list_threads(
    *,
    character_id: str,
    space_id: int | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[dict[str, object]]:
    if not 1 <= limit <= 200:
        raise ValueError("limit must be between 1 and 200")

    where: list[str] = []
    params: list[object] = []
    if space_id is not None:
        where.append("t.space_id = ?")
        params.append(space_id)
    if status is not None:
        where.append("t.status = ?")
        params.append(status)

    clause = f"WHERE {' AND '.join(where)}" if where else ""
    conn = _connect(character_id)
    try:
        rows = conn.execute(
            f"""
            SELECT t.id, t.space_id, t.title, t.status, t.version,
                   t.created_at, t.updated_at,
                   COUNT(p.id) AS post_count
            FROM threads t
            LEFT JOIN posts p ON p.thread_id = t.id
            {clause}
            GROUP BY t.id
            ORDER BY t.updated_at DESC, t.id DESC
            LIMIT ?
            """,
            (*params, limit),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def search_board(
    *,
    character_id: str,
    query: str,
    limit: int = 20,
) -> list[dict[str, object]]:
    clean = query.strip()
    if not clean:
        raise ValueError("query must not be empty")
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")

    pattern = f"%{clean}%"
    conn = _connect(character_id)
    try:
        rows = conn.execute(
            """
            SELECT 'thread' AS result_type, t.id AS id, t.id AS thread_id,
                   t.title AS title, NULL AS body, t.updated_at AS timestamp
            FROM threads t
            WHERE t.title LIKE ? ESCAPE '\\'
            UNION ALL
            SELECT 'post' AS result_type, p.id AS id, p.thread_id AS thread_id,
                   t.title AS title, p.body AS body, p.created_at AS timestamp
            FROM posts p
            JOIN threads t ON t.id = p.thread_id
            WHERE p.body LIKE ? ESCAPE '\\'
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (pattern, pattern, limit),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()
