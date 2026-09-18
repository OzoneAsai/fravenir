"""Tests for the generic board-aware graph API."""

from __future__ import annotations

from pathlib import Path

import pytest

from fravenir.core.board import create_space, create_thread, get_thread
from fravenir.core.graph_api import (
    add_relation,
    get_neighbors,
    get_node,
    invalidate_relation,
    search_nodes,
)
from fravenir.storage.sqlite_init import init_kv


def _init(tmp_project: Path, character_id: str = "graph_api") -> str:
    data = tmp_project / "data" / character_id
    data.mkdir(parents=True)
    init_kv(data / "kv.sqlite")
    return character_id


def test_thread_post_relation_roundtrip(tmp_project: Path) -> None:
    character_id = _init(tmp_project)
    space = create_space(character_id=character_id, name="JADX")
    thread = create_thread(
        character_id=character_id,
        space_id=int(space["space_id"]),
        title="finally reconstruction",
        author_kind="human",
        author_display_name="Ozone",
        initial_post="B193 evidence",
    )
    data = get_thread(character_id=character_id, thread_id=int(thread["thread_id"]))
    post_id = int(data["posts"][0]["id"])

    relation = add_relation(
        character_id=character_id,
        src_type="thread",
        src_id=int(thread["thread_id"]),
        dst_type="post",
        dst_id=post_id,
        predicate="contains",
    )

    neighbors = get_neighbors(
        character_id=character_id,
        node_type="thread",
        node_id=int(thread["thread_id"]),
    )
    assert neighbors["neighbors"][0]["predicate"] == "contains"
    assert neighbors["neighbors"][0]["direction"] == "outgoing"
    assert neighbors["neighbors"][0]["node"]["type"] == "post"

    invalidated = invalidate_relation(
        character_id=character_id,
        relation_id=int(relation["relation_id"]),
    )
    assert invalidated["changed"] is True

    active = get_neighbors(
        character_id=character_id,
        node_type="thread",
        node_id=int(thread["thread_id"]),
    )
    assert active["neighbors"] == []

    archived = get_neighbors(
        character_id=character_id,
        node_type="thread",
        node_id=int(thread["thread_id"]),
        include_archived=True,
    )
    assert len(archived["neighbors"]) == 1
    assert archived["neighbors"][0]["valid_to"] is not None


def test_graph_node_returns_post_source(tmp_project: Path) -> None:
    character_id = _init(tmp_project, "graph_node")
    space = create_space(character_id=character_id, name="board")
    thread = create_thread(
        character_id=character_id,
        space_id=int(space["space_id"]),
        title="topic",
        author_kind="agent",
        author_display_name="ChatGPT",
        initial_post="source text",
    )
    data = get_thread(character_id=character_id, thread_id=int(thread["thread_id"]))
    post_id = int(data["posts"][0]["id"])

    node = get_node(character_id=character_id, node_type="post", node_id=post_id)
    assert node["body"] == "source text"
    assert node["type"] == "post"


def test_graph_rejects_unknown_predicate_without_opt_in(tmp_project: Path) -> None:
    character_id = _init(tmp_project, "graph_predicate")
    space = create_space(character_id=character_id, name="board")
    thread = create_thread(
        character_id=character_id,
        space_id=int(space["space_id"]),
        title="topic",
        author_kind="agent",
        author_display_name="ChatGPT",
        initial_post="source",
    )
    data = get_thread(character_id=character_id, thread_id=int(thread["thread_id"]))
    post_id = int(data["posts"][0]["id"])

    with pytest.raises(ValueError, match="unsupported predicate"):
        add_relation(
            character_id=character_id,
            src_type="thread",
            src_id=int(thread["thread_id"]),
            dst_type="post",
            dst_id=post_id,
            predicate="somehow_related",
        )


def test_graph_rejects_self_relation(tmp_project: Path) -> None:
    character_id = _init(tmp_project, "graph_self")
    space = create_space(character_id=character_id, name="board")
    thread = create_thread(
        character_id=character_id,
        space_id=int(space["space_id"]),
        title="topic",
        author_kind="agent",
        author_display_name="ChatGPT",
    )

    with pytest.raises(ValueError, match="self-referential"):
        add_relation(
            character_id=character_id,
            src_type="thread",
            src_id=int(thread["thread_id"]),
            dst_type="thread",
            dst_id=int(thread["thread_id"]),
            predicate="related_to",
        )


def test_graph_search_spans_thread_and_post(tmp_project: Path) -> None:
    character_id = _init(tmp_project, "graph_search")
    space = create_space(character_id=character_id, name="board")
    thread = create_thread(
        character_id=character_id,
        space_id=int(space["space_id"]),
        title="B193 finally analysis",
        author_kind="human",
        author_display_name="Ozone",
        initial_post="SGET preparation evidence",
    )

    results = search_nodes(
        character_id=character_id,
        query="B193",
    )
    assert results[0]["type"] == "thread"
    assert results[0]["id"] == thread["thread_id"]

    post_results = search_nodes(
        character_id=character_id,
        query="SGET",
        node_types=["post"],
    )
    assert len(post_results) == 1
    assert post_results[0]["type"] == "post"
