"""Derive structured memories from board source material with provenance."""

from __future__ import annotations

import sqlite3
from typing import Literal

from fravenir.core.board import ActorKind, ensure_actor
from fravenir.core.extraction import ExtractionClient
from fravenir.core.write import memory_write
from fravenir.embedding import Embedder
from fravenir.schemas.config import AppConfig
from fravenir.storage.paths import kv_db_path
from fravenir.storage.sqlite_init import init_kv


def derive_memory_from_posts(
    *,
    character_id: str,
    config: AppConfig,
    embedder: Embedder,
    extraction_client: ExtractionClient | None,
    content: str,
    source_post_ids: list[int],
    author_kind: ActorKind,
    author_display_name: str,
    author_external_subject: str | None = None,
    kind: Literal["facts", "state", "emo"] = "facts",
    importance: int = 1,
) -> dict[str, object]:
    """Create an episode derived from one or more board posts.

    Source posts are validated before the memory write and their current revision
    is snapshotted into episode_sources so later post edits do not erase the
    provenance context used for the derivation.
    """
    if not source_post_ids:
        raise ValueError("source_post_ids must not be empty")
    if len(set(source_post_ids)) != len(source_post_ids):
        raise ValueError("source_post_ids must not contain duplicates")

    path = kv_db_path(character_id)
    init_kv(path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        sources: list[tuple[int, int]] = []
        for post_id in source_post_ids:
            row = conn.execute(
                "SELECT id, revision FROM posts WHERE id = ?",
                (post_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"source post not found: {post_id}")
            sources.append((int(row["id"]), int(row["revision"])))
    finally:
        conn.close()

    actor_id = ensure_actor(
        character_id=character_id,
        kind=author_kind,
        display_name=author_display_name,
        external_subject=author_external_subject,
    )

    written = memory_write(
        content=content,
        kind=kind,
        importance=importance,
        session_id=None,
        character_id=character_id,
        config=config,
        embedder=embedder,
        extraction_client=extraction_client,
    )
    episode_value = written.get("episode_id")
    if not isinstance(episode_value, int):
        raise RuntimeError("memory_write returned an invalid episode_id")
    episode_id = episode_value

    conn = sqlite3.connect(path)
    try:
        conn.executemany(
            """
            INSERT INTO episode_sources
                (episode_id, source_type, source_id, source_revision,
                 relation, actor_id)
            VALUES (?, 'post', ?, ?, 'derived_from', ?)
            """,
            [
                (episode_id, post_id, revision, actor_id)
                for post_id, revision in sources
            ],
        )
        conn.commit()
    finally:
        conn.close()

    return {
        **written,
        "source_posts": [
            {"post_id": post_id, "revision": revision}
            for post_id, revision in sources
        ],
        "derived_by_actor_id": actor_id,
    }


def get_episode_sources(
    *,
    character_id: str,
    episode_id: int,
) -> list[dict[str, object]]:
    """Return provenance edges for an episode."""
    path = kv_db_path(character_id)
    init_kv(path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT es.source_type, es.source_id, es.source_revision,
                   es.relation, es.created_at,
                   a.id AS actor_id, a.kind AS actor_kind,
                   a.display_name AS actor_name
            FROM episode_sources es
            LEFT JOIN actors a ON a.id = es.actor_id
            WHERE es.episode_id = ?
            ORDER BY es.source_type, es.source_id
            """,
            (episode_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()
