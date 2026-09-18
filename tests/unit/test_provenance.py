"""Tests for board-to-memory provenance."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import numpy as np

from fravenir.core.board import create_space, create_thread, get_thread
from fravenir.core.provenance import derive_memory_from_posts, get_episode_sources
from fravenir.schemas.config import AppConfig, CharacterConfig, ExtractionConfig
from fravenir.storage.sqlite_init import init_kv, init_vdb, init_vdb_entities, init_vdb_relations

DIM = 768


def _stub_embedder() -> MagicMock:
    embedder = MagicMock()
    vector = np.ones(DIM, dtype=np.float32)
    vector /= np.linalg.norm(vector)
    embedder.encode_document.return_value = vector
    embedder.encode_query.return_value = vector
    embedder.encode_topic.return_value = vector
    return embedder


def _init(tmp_project: Path, character_id: str) -> AppConfig:
    data = tmp_project / "data" / character_id
    data.mkdir(parents=True)
    init_kv(data / "kv.sqlite")
    init_vdb(data / "vdb_memories.db")
    init_vdb_entities(data / "vdb_entities.db")
    init_vdb_relations(data / "vdb_relations.db")
    return AppConfig(
        character=CharacterConfig(id=character_id),
        extraction=ExtractionConfig(enabled=False),
    )


def test_derive_memory_snapshots_post_revisions(tmp_project: Path) -> None:
    character_id = "provenance"
    config = _init(tmp_project, character_id)
    space = create_space(character_id=character_id, name="JADX")
    thread = create_thread(
        character_id=character_id,
        space_id=int(space["space_id"]),
        title="finally",
        author_kind="human",
        author_display_name="Ozone",
        initial_post="B193 is suspicious",
    )
    thread_data = get_thread(
        character_id=character_id,
        thread_id=int(thread["thread_id"]),
    )
    post_id = int(thread_data["posts"][0]["id"])

    result = derive_memory_from_posts(
        character_id=character_id,
        config=config,
        embedder=_stub_embedder(),
        extraction_client=None,
        content="B193 is evidence for the finally-family reconstruction.",
        source_post_ids=[post_id],
        author_kind="agent",
        author_display_name="ChatGPT",
        kind="facts",
        importance=2,
    )

    sources = get_episode_sources(
        character_id=character_id,
        episode_id=int(result["episode_id"]),
    )
    assert sources == [
        {
            "source_type": "post",
            "source_id": post_id,
            "source_revision": 1,
            "relation": "derived_from",
            "created_at": sources[0]["created_at"],
            "actor_id": result["derived_by_actor_id"],
            "actor_kind": "agent",
            "actor_name": "ChatGPT",
        }
    ]
