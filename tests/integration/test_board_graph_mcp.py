"""End-to-end MCP flow across board, provenance, and generic graph layers."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest
from mcp import Client
from mcp.types import TextContent

from fravenir.schemas.config import AppConfig, CharacterConfig, ExtractionConfig
from fravenir.server import build_server
from fravenir.storage import sqlite_init

DIM = 768


def _stub_embedder() -> MagicMock:
    embedder = MagicMock()
    vector = np.ones(DIM, dtype=np.float32)
    vector /= np.linalg.norm(vector)
    embedder.encode_document.return_value = vector
    embedder.encode_query.return_value = vector
    embedder.encode_topic.return_value = vector
    return embedder


def _parse(result: object) -> object:
    structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict):
        if set(structured) == {"result"}:
            return structured["result"]
        return structured
    raw = getattr(result, "content", None)
    if raw and isinstance(raw[0], TextContent):
        return json.loads(raw[0].text)
    return None


@pytest.mark.anyio
async def test_board_to_memory_to_graph_mcp(tmp_project: Path) -> None:
    character_id = "board_graph_e2e"
    data = tmp_project / "data" / character_id
    data.mkdir(parents=True)
    sqlite_init.init_kv(data / "kv.sqlite")
    sqlite_init.init_vdb(data / "vdb_memories.db")
    sqlite_init.init_vdb_entities(data / "vdb_entities.db")
    sqlite_init.init_vdb_relations(data / "vdb_relations.db")
    config = AppConfig(
        character=CharacterConfig(id=character_id),
        extraction=ExtractionConfig(enabled=False),
    )
    server = build_server(config, embedder=_stub_embedder())

    async with Client(server) as client:
        space = _parse(
            await client.call_tool(
                "board_create_space",
                {"name": "JADX", "description": "Decompiler research"},
            )
        )
        assert isinstance(space, dict)

        thread = _parse(
            await client.call_tool(
                "board_create_thread",
                {
                    "space_id": space["space_id"],
                    "title": "finally reconstruction",
                    "author_kind": "human",
                    "author_display_name": "Ozone",
                    "initial_post": "B193 is suspicious",
                },
            )
        )
        assert isinstance(thread, dict)

        thread_data = _parse(
            await client.call_tool(
                "board_get_thread",
                {"thread_id": thread["thread_id"]},
            )
        )
        assert isinstance(thread_data, dict)
        post_id = thread_data["posts"][0]["id"]

        derived = _parse(
            await client.call_tool(
                "memory_derive",
                {
                    "content": "B193 is evidence for finally reconstruction.",
                    "source_post_ids": [post_id],
                    "author_kind": "agent",
                    "author_display_name": "ChatGPT",
                    "importance": 2,
                },
            )
        )
        assert isinstance(derived, dict)

        sources = _parse(
            await client.call_tool(
                "memory_sources",
                {"episode_id": derived["episode_id"]},
            )
        )
        assert isinstance(sources, list)
        assert sources[0]["source_id"] == post_id
        assert sources[0]["source_revision"] == 1

        relation = _parse(
            await client.call_tool(
                "graph_link",
                {
                    "src_type": "thread",
                    "src_id": thread["thread_id"],
                    "dst_type": "episode",
                    "dst_id": derived["episode_id"],
                    "predicate": "resolves",
                },
            )
        )
        assert isinstance(relation, dict)

        graph = _parse(
            await client.call_tool(
                "graph_neighbors",
                {
                    "node_type": "thread",
                    "node_id": thread["thread_id"],
                },
            )
        )
        assert isinstance(graph, dict)
        assert graph["neighbors"][0]["predicate"] == "resolves"
        assert graph["neighbors"][0]["node"]["id"] == derived["episode_id"]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
