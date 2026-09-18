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


def _lastrowid(cursor: sqlite3.Cursor) -> int:
    value = cursor.lastrowid
    if value is None:
        raise RuntimeError("sqlite insert did not return a row id")
    return int(value)


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
    return _lastrowid(cur)


def ensure_actor(
    *,
    character_id: str,
    kind: ActorKind,
    display_name: str,
    external_subject: str | None = None,
) -> int:
    """Resolve or create an actor and return its stable local id."""
    conn = _connect(character_id)
    try:
        actor_id = _actor_id(
            conn,
            kind=kind,
            display_name=display_name,
            external_subject=external_subject,
        )
        conn.commit()
        return actor_id
    finally:
        conn.close()


def get_post_revision(
    *,
    character_id: str,
    post_id: int,
    revision: int | None = None,
) -> dict[str, object]:
    """Return the exact body for a post revision.

    If revision is omitted, the current revision is returned. Historical bodies
    are read from post_revisions, which are written before every edit.
    """
    conn = _connect(character_id)
    try:
        post = conn.execute(
            """
            SELECT p.id, p.thread_id, p.parent_post_id, p.author_id, p.kind,
                   p.body, p.revision, p.created_at, p.edited_at,
                   a.kind AS author_kind, a.display_name AS author_name
            FROM posts p
            LEFT JOIN actors a ON a.id = p.author_id
            WHERE p.id = ?
            """,
            (post_id,),
        ).fetchone()
        if post is None:
            raise ValueError(f"post not found: {post_id}")

        current_revision = int(post["revision"])
        target_revision = current_revision if revision is None else revision
        if target_revision < 1:
            raise ValueError("revision must be >= 1")
        if target_revision > current_revision:
            raise ValueError(
                f"post revision not found: post={post_id} revision={target_revision}"
            )

        if target_revision == current_revision:
            body = str(post["body"])
            edited_at = post["edited_at"]
        else:
            historical = conn.execute(
                """
                SELECT body, edited_at
                FROM post_revisions
                WHERE post_id = ? AND revision = ?
                """,
                (post_id, target_revision),
            ).fetchone()
            if historical is None:
                raise ValueError(
                    f"post revision not found: post={post_id} revision={target_revision}"
                )
            body = str(historical["body"])
            edited_at = historical["edited_at"]

        return {
            "post_id": int(post["id"]),
            "thread_id": int(post["thread_id"]),
            "parent_post_id": post["parent_post_id"],
            "kind": str(post["kind"]),
            "revision": target_revision,
            "current_revision": current_revision,
            "body": body,
            "author_id": post["author_id"],
            "author_kind": post["author_kind"],
            "author_name": post["author_name"],
            "created_at": post["created_at"],
            "edited_at": edited_at,
        }
    finally:
        conn.close()


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
            "space_id": _lastrowid(cur),
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
        thread_id = _lastrowid(cur)

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
            post_id = _lastrowid(pcur)
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
            "post_id": _lastrowid(cur),
            "thread_id": thread_id,
            "thread_version": next_version,
            "revision": 1,
        }
    finally:
        conn.close()


def edit_post(
    *,
    character_id: str,
    post_id: int,
    body: str,
    expected_revision: int,
    editor_kind: ActorKind,
    editor_display_name: str,
    editor_external_subject: str | None = None,
) -> dict[str, object]:
    """Edit a post with optimistic concurrency while retaining the old revision."""
    clean_body = body.strip()
    if not clean_body:
        raise ValueError("post body must not be empty")
    if expected_revision < 1:
        raise ValueError("expected_revision must be >= 1")

    conn = _connect(character_id)
    try:
        post = conn.execute(
            """
            SELECT id, thread_id, body, revision
            FROM posts
            WHERE id = ?
            """,
            (post_id,),
        ).fetchone()
        if post is None:
            raise ValueError(f"post not found: {post_id}")

        current_revision = int(post["revision"])
        if current_revision != expected_revision:
            raise ValueError(
                f"stale post revision: expected {expected_revision}, current {current_revision}"
            )
        if str(post["body"]) == clean_body:
            return {
                "post_id": post_id,
                "revision": current_revision,
                "changed": False,
            }

        editor_id = _actor_id(
            conn,
            kind=editor_kind,
            display_name=editor_display_name,
            external_subject=editor_external_subject,
        )
        now = datetime.now(UTC).isoformat()
        conn.execute(
            """
            INSERT INTO post_revisions
                (post_id, revision, body, edited_at, editor_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (post_id, current_revision, post["body"], now, editor_id),
        )
        next_revision = current_revision + 1
        conn.execute(
            """
            UPDATE posts
            SET body = ?, revision = ?, edited_at = ?
            WHERE id = ? AND revision = ?
            """,
            (clean_body, next_revision, now, post_id, current_revision),
        )
        thread_id = int(post["thread_id"])
        thread = conn.execute(
            "SELECT version FROM threads WHERE id = ?",
            (thread_id,),
        ).fetchone()
        if thread is None:
            raise RuntimeError(f"post {post_id} refers to missing thread {thread_id}")
        thread_version = int(thread["version"]) + 1
        conn.execute(
            "UPDATE threads SET version = ?, updated_at = ? WHERE id = ?",
            (thread_version, now, thread_id),
        )
        conn.commit()
        return {
            "post_id": post_id,
            "revision": next_revision,
            "thread_id": thread_id,
            "thread_version": thread_version,
            "changed": True,
        }
    finally:
        conn.close()


def organize_thread(
    *,
    character_id: str,
    thread_id: int,
    summary: str,
    source_post_ids: list[int],
    expected_thread_version: int,
    author_kind: ActorKind,
    author_display_name: str,
    author_external_subject: str | None = None,
) -> dict[str, object]:
    """Append a summary post derived from exact source post revisions.

    The operation is optimistic-concurrency guarded by the thread version and is
    additive: source posts are never changed or archived.
    """
    clean_summary = summary.strip()
    if not clean_summary:
        raise ValueError("summary must not be empty")
    if expected_thread_version < 1:
        raise ValueError("expected_thread_version must be >= 1")
    if not source_post_ids:
        raise ValueError("source_post_ids must not be empty")
    if len(set(source_post_ids)) != len(source_post_ids):
        raise ValueError("source_post_ids must not contain duplicates")

    conn = _connect(character_id)
    try:
        thread = conn.execute(
            "SELECT id, version FROM threads WHERE id = ?",
            (thread_id,),
        ).fetchone()
        if thread is None:
            raise ValueError(f"thread not found: {thread_id}")
        current_version = int(thread["version"])
        if current_version != expected_thread_version:
            raise ValueError(
                "stale thread version: "
                f"expected {expected_thread_version}, current {current_version}"
            )

        sources: list[tuple[int, int]] = []
        for post_id in source_post_ids:
            row = conn.execute(
                "SELECT id, thread_id, revision FROM posts WHERE id = ?",
                (post_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"source post not found: {post_id}")
            if int(row["thread_id"]) != thread_id:
                raise ValueError(f"source post belongs to a different thread: {post_id}")
            sources.append((int(row["id"]), int(row["revision"])))

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
                (thread_id, author_id, kind, body, revision, created_at)
            VALUES (?, ?, 'summary', ?, 1, ?)
            """,
            (thread_id, actor_id, clean_summary, now),
        )
        summary_post_id = _lastrowid(cur)

        conn.executemany(
            """
            INSERT INTO post_sources
                (post_id, source_post_id, source_revision, relation, actor_id)
            VALUES (?, ?, ?, 'derived_from', ?)
            """,
            [
                (summary_post_id, source_post_id, source_revision, actor_id)
                for source_post_id, source_revision in sources
            ],
        )

        conn.execute(
            """
            INSERT INTO relations
                (src_type, src_id, dst_type, dst_id, predicate, strength, valid_from)
            VALUES ('thread', ?, 'post', ?, 'contains', 1.0, ?)
            """,
            (thread_id, summary_post_id, now),
        )
        conn.executemany(
            """
            INSERT INTO relations
                (src_type, src_id, dst_type, dst_id, predicate, strength, valid_from)
            VALUES ('post', ?, 'post', ?, 'derived_from', 1.0, ?)
            """,
            [
                (summary_post_id, source_post_id, now)
                for source_post_id, _source_revision in sources
            ],
        )

        next_version = current_version + 1
        conn.execute(
            "UPDATE threads SET version = ?, updated_at = ? WHERE id = ?",
            (next_version, now, thread_id),
        )
        conn.commit()
        return {
            "thread_id": thread_id,
            "summary_post_id": summary_post_id,
            "thread_version": next_version,
            "source_posts": [
                {"post_id": source_post_id, "revision": source_revision}
                for source_post_id, source_revision in sources
            ],
        }
    finally:
        conn.close()


def get_post_sources(
    *,
    character_id: str,
    post_id: int,
) -> list[dict[str, object]]:
    """Return exact source post revisions used to derive a post."""
    conn = _connect(character_id)
    try:
        rows = conn.execute(
            """
            SELECT ps.source_post_id, ps.source_revision, ps.relation, ps.created_at,
                   a.id AS actor_id, a.kind AS actor_kind,
                   a.display_name AS actor_name
            FROM post_sources ps
            LEFT JOIN actors a ON a.id = ps.actor_id
            WHERE ps.post_id = ?
            ORDER BY ps.source_post_id
            """,
            (post_id,),
        ).fetchall()
        return [dict(row) for row in rows]
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
