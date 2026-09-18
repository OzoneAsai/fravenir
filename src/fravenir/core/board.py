"""Board primitives for human/agent collaboration."""

from __future__ import annotations

import re
import sqlite3
from datetime import UTC, datetime
from typing import Literal

from fravenir.core.graph import link_relation_in_conn
from fravenir.storage import paths

ActorKind = Literal["human", "agent", "system"]
PostKind = Literal["message", "summary", "decision", "note"]
ThreadStatus = Literal["open", "resolved", "archived"]

_SPACE_SLUG = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


class BoardConflictError(ValueError):
    """Raised when optimistic concurrency detects a stale write."""


def _connect(character_id: str) -> sqlite3.Connection:
    conn = sqlite3.connect(paths.kv_db_path(character_id))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _as_dict(row: sqlite3.Row) -> dict[str, object]:
    return dict(row)


def _lastrowid(cursor: sqlite3.Cursor) -> int:
    value = cursor.lastrowid
    if value is None:
        raise RuntimeError("INSERT did not produce a row id")
    return value


def board_create_actor(
    *,
    character_id: str,
    display_name: str,
    kind: ActorKind = "agent",
    external_subject: str | None = None,
) -> dict[str, object]:
    name = display_name.strip()
    if not name:
        raise ValueError("display_name must not be empty")
    if kind not in ("human", "agent", "system"):
        raise ValueError(f"invalid actor kind: {kind!r}")

    conn = _connect(character_id)
    try:
        cur = conn.execute(
            """
            INSERT INTO actors (kind, display_name, external_subject)
            VALUES (?, ?, ?)
            """,
            (kind, name, external_subject),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM actors WHERE id = ?", (cur.lastrowid,)).fetchone()
        assert row is not None
        return _as_dict(row)
    finally:
        conn.close()


def board_create_space(
    *,
    character_id: str,
    slug: str,
    name: str,
    description: str | None = None,
    created_by: int | None = None,
) -> dict[str, object]:
    slug = slug.strip()
    name = name.strip()
    if not _SPACE_SLUG.fullmatch(slug):
        raise ValueError("slug must contain only letters, numbers, '_' or '-' (max 64)")
    if not name:
        raise ValueError("name must not be empty")

    conn = _connect(character_id)
    try:
        cur = conn.execute(
            """
            INSERT INTO spaces (slug, name, description, created_by)
            VALUES (?, ?, ?, ?)
            """,
            (slug, name, description, created_by),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM spaces WHERE id = ?", (cur.lastrowid,)).fetchone()
        assert row is not None
        return _as_dict(row)
    finally:
        conn.close()


def board_list_spaces(*, character_id: str) -> list[dict[str, object]]:
    conn = _connect(character_id)
    try:
        rows = conn.execute(
            """
            SELECT s.*, a.display_name AS creator_name
            FROM spaces s
            LEFT JOIN actors a ON a.id = s.created_by
            ORDER BY s.id
            """
        ).fetchall()
        return [_as_dict(row) for row in rows]
    finally:
        conn.close()


def board_create_thread(
    *,
    character_id: str,
    space_id: int,
    title: str,
    body: str | None = None,
    created_by: int | None = None,
) -> dict[str, object]:
    title = title.strip()
    if not title:
        raise ValueError("title must not be empty")
    if body is not None and not body.strip():
        raise ValueError("body must not be empty when provided")

    now = _now()
    conn = _connect(character_id)
    try:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM spaces WHERE id = ?", (space_id,)).fetchone() is None:
            raise ValueError(f"space {space_id} not found")
        cur = conn.execute(
            """
            INSERT INTO threads
                (space_id, title, status, created_by, version, created_at, updated_at)
            VALUES (?, ?, 'open', ?, 1, ?, ?)
            """,
            (space_id, title, created_by, now, now),
        )
        thread_id = _lastrowid(cur)
        link_relation_in_conn(
            conn,
            src_type="space",
            src_id=space_id,
            dst_type="thread",
            dst_id=thread_id,
            predicate="contains",
        )
        if body is not None:
            post_cur = conn.execute(
                """
                INSERT INTO posts
                    (thread_id, parent_post_id, author_id, kind, body, revision, created_at)
                VALUES (?, NULL, ?, 'message', ?, 1, ?)
                """,
                (thread_id, created_by, body.strip(), now),
            )
            post_id = _lastrowid(post_cur)
            link_relation_in_conn(
                conn,
                src_type="thread",
                src_id=thread_id,
                dst_type="post",
                dst_id=post_id,
                predicate="contains",
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return board_get_thread(character_id=character_id, thread_id=thread_id)


def board_list_threads(
    *,
    character_id: str,
    space_id: int | None = None,
    status: ThreadStatus | None = None,
    limit: int = 50,
) -> list[dict[str, object]]:
    if not 1 <= limit <= 200:
        raise ValueError("limit must be 1-200")
    if status is not None and status not in ("open", "resolved", "archived"):
        raise ValueError(f"invalid thread status: {status!r}")

    clauses: list[str] = []
    args: list[object] = []
    if space_id is not None:
        clauses.append("t.space_id = ?")
        args.append(space_id)
    if status is not None:
        clauses.append("t.status = ?")
        args.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    args.append(limit)

    conn = _connect(character_id)
    try:
        rows = conn.execute(
            f"""
            SELECT t.*, s.slug AS space_slug, s.name AS space_name,
                   a.display_name AS creator_name,
                   (SELECT COUNT(*) FROM posts p WHERE p.thread_id = t.id) AS post_count
            FROM threads t
            JOIN spaces s ON s.id = t.space_id
            LEFT JOIN actors a ON a.id = t.created_by
            {where}
            ORDER BY t.updated_at DESC, t.id DESC
            LIMIT ?
            """,
            args,
        ).fetchall()
        return [_as_dict(row) for row in rows]
    finally:
        conn.close()


def board_get_thread(*, character_id: str, thread_id: int) -> dict[str, object]:
    conn = _connect(character_id)
    try:
        thread = conn.execute(
            """
            SELECT t.*, s.slug AS space_slug, s.name AS space_name,
                   a.display_name AS creator_name
            FROM threads t
            JOIN spaces s ON s.id = t.space_id
            LEFT JOIN actors a ON a.id = t.created_by
            WHERE t.id = ?
            """,
            (thread_id,),
        ).fetchone()
        if thread is None:
            raise ValueError(f"thread {thread_id} not found")
        posts = conn.execute(
            """
            SELECT p.*, a.display_name AS author_name, a.kind AS author_kind
            FROM posts p
            LEFT JOIN actors a ON a.id = p.author_id
            WHERE p.thread_id = ?
            ORDER BY p.id
            """,
            (thread_id,),
        ).fetchall()
        result = _as_dict(thread)
        result["posts"] = [_as_dict(row) for row in posts]
        return result
    finally:
        conn.close()


def board_post(
    *,
    character_id: str,
    thread_id: int,
    body: str,
    author_id: int | None = None,
    parent_post_id: int | None = None,
    kind: PostKind = "message",
    expected_version: int | None = None,
) -> dict[str, object]:
    body = body.strip()
    if not body:
        raise ValueError("body must not be empty")
    if kind not in ("message", "summary", "decision", "note"):
        raise ValueError(f"invalid post kind: {kind!r}")

    now = _now()
    conn = _connect(character_id)
    try:
        conn.execute("BEGIN IMMEDIATE")
        thread = conn.execute(
            "SELECT version FROM threads WHERE id = ?", (thread_id,)
        ).fetchone()
        if thread is None:
            raise ValueError(f"thread {thread_id} not found")
        version = int(thread["version"])
        if expected_version is not None and expected_version != version:
            raise BoardConflictError(
                f"stale thread version: expected {expected_version}, current {version}"
            )
        if parent_post_id is not None:
            parent = conn.execute(
                "SELECT thread_id FROM posts WHERE id = ?", (parent_post_id,)
            ).fetchone()
            if parent is None or int(parent["thread_id"]) != thread_id:
                raise ValueError("parent_post_id must belong to the same thread")

        cur = conn.execute(
            """
            INSERT INTO posts
                (thread_id, parent_post_id, author_id, kind, body, revision, created_at)
            VALUES (?, ?, ?, ?, ?, 1, ?)
            """,
            (thread_id, parent_post_id, author_id, kind, body, now),
        )
        post_id = _lastrowid(cur)
        link_relation_in_conn(
            conn,
            src_type="thread",
            src_id=thread_id,
            dst_type="post",
            dst_id=post_id,
            predicate="contains",
        )
        if parent_post_id is not None:
            link_relation_in_conn(
                conn,
                src_type="post",
                src_id=post_id,
                dst_type="post",
                dst_id=parent_post_id,
                predicate="reply_to",
            )
        new_version = version + 1
        conn.execute(
            "UPDATE threads SET version = ?, updated_at = ? WHERE id = ?",
            (new_version, now, thread_id),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
        assert row is not None
        result = _as_dict(row)
        result["thread_version"] = new_version
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def board_edit_post(
    *,
    character_id: str,
    post_id: int,
    body: str,
    expected_revision: int,
    edited_by: int | None = None,
) -> dict[str, object]:
    body = body.strip()
    if not body:
        raise ValueError("body must not be empty")
    now = _now()

    conn = _connect(character_id)
    try:
        conn.execute("BEGIN IMMEDIATE")
        post = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
        if post is None:
            raise ValueError(f"post {post_id} not found")
        revision = int(post["revision"])
        if expected_revision != revision:
            raise BoardConflictError(
                f"stale post revision: expected {expected_revision}, current {revision}"
            )

        conn.execute(
            """
            INSERT INTO post_revisions (post_id, revision, body, edited_by, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (post_id, revision, post["body"], edited_by, now),
        )
        new_revision = revision + 1
        conn.execute(
            "UPDATE posts SET body = ?, revision = ?, edited_at = ? WHERE id = ?",
            (body, new_revision, now, post_id),
        )
        thread_id = int(post["thread_id"])
        conn.execute(
            "UPDATE threads SET version = version + 1, updated_at = ? WHERE id = ?",
            (now, thread_id),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
        assert row is not None
        result = _as_dict(row)
        thread = conn.execute("SELECT version FROM threads WHERE id = ?", (thread_id,)).fetchone()
        assert thread is not None
        result["thread_version"] = int(thread["version"])
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def board_search(
    *,
    character_id: str,
    query: str,
    limit: int = 20,
) -> list[dict[str, object]]:
    query = query.strip()
    if not query:
        raise ValueError("query must not be empty")
    if not 1 <= limit <= 100:
        raise ValueError("limit must be 1-100")
    pattern = f"%{query}%"

    conn = _connect(character_id)
    try:
        rows = conn.execute(
            """
            SELECT 'thread' AS node_type, t.id AS node_id, t.title AS title,
                   NULL AS body, t.updated_at AS matched_at
            FROM threads t
            WHERE t.title LIKE ?
            UNION ALL
            SELECT 'post' AS node_type, p.id AS node_id, t.title AS title,
                   p.body AS body, COALESCE(p.edited_at, p.created_at) AS matched_at
            FROM posts p
            JOIN threads t ON t.id = p.thread_id
            WHERE p.body LIKE ?
            ORDER BY matched_at DESC
            LIMIT ?
            """,
            (pattern, pattern, limit),
        ).fetchall()
        return [_as_dict(row) for row in rows]
    finally:
        conn.close()
