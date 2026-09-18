"""Tests for generic graph operations."""

from __future__ import annotations

from fravenir.core.board import board_create_space, board_create_thread, board_post
from fravenir.core.graph import (
    graph_get_node,
    graph_invalidate_relation,
    graph_link,
    graph_neighbors,
    graph_search,
)
from fravenir.storage.sqlite_init import init_kv


def _init(tmp_project, character_id: str = "graph") -> None:
    d = tmp_project / "data" / character_id
    d.mkdir(parents=True)
    init_kv(d / "kv.sqlite")


def test_board_structure_is_graph_native(tmp_project) -> None:
    _init(tmp_project)
    space = board_create_space(character_id="graph", slug="jadx", name="JADX")
    thread = board_create_thread(
        character_id="graph",
        space_id=int(space["id"]),
        title="finally reconstruction",
        body="B193を調べる",
    )
    first_post = thread["posts"][0]
    reply = board_post(
        character_id="graph",
        thread_id=int(thread["id"]),
        parent_post_id=int(first_post["id"]),
        body="SGET preparation",
        expected_version=1,
    )

    space_neighbors = graph_neighbors(
        character_id="graph",
        node_type="space",
        node_id=int(space["id"]),
        direction="outgoing",
    )
    assert {
        (n["relation"]["predicate"], n["node"]["type"], n["node"]["id"])
        for n in space_neighbors["neighbors"]
    } == {("contains", "thread", thread["id"])}

    thread_neighbors = graph_neighbors(
        character_id="graph",
        node_type="thread",
        node_id=int(thread["id"]),
        direction="outgoing",
        predicates=["contains"],
    )
    assert {n["node"]["id"] for n in thread_neighbors["neighbors"]} == {
        first_post["id"],
        reply["id"],
    }

    reply_neighbors = graph_neighbors(
        character_id="graph",
        node_type="post",
        node_id=int(reply["id"]),
        direction="outgoing",
        predicates=["reply_to"],
    )
    assert reply_neighbors["neighbors"][0]["node"]["id"] == first_post["id"]


def test_graph_link_is_idempotent_and_invalidation_is_logical(tmp_project) -> None:
    _init(tmp_project)
    space = board_create_space(character_id="graph", slug="general", name="General")
    a = board_create_thread(
        character_id="graph", space_id=int(space["id"]), title="A"
    )
    b = board_create_thread(
        character_id="graph", space_id=int(space["id"]), title="B"
    )

    first = graph_link(
        character_id="graph",
        src_type="thread",
        src_id=int(a["id"]),
        dst_type="thread",
        dst_id=int(b["id"]),
        predicate="related_to",
    )
    assert first["created"] is True
    second = graph_link(
        character_id="graph",
        src_type="thread",
        src_id=int(a["id"]),
        dst_type="thread",
        dst_id=int(b["id"]),
        predicate="related_to",
    )
    assert second["created"] is False
    assert second["id"] == first["id"]

    invalidated = graph_invalidate_relation(
        character_id="graph", relation_id=int(first["id"])
    )
    assert invalidated["changed"] is True
    assert invalidated["valid_to"] is not None


def test_graph_search_and_get_node(tmp_project) -> None:
    _init(tmp_project)
    space = board_create_space(character_id="graph", slug="jadx", name="JADX")
    thread = board_create_thread(
        character_id="graph",
        space_id=int(space["id"]),
        title="Coroutine finally",
        body="B193",
    )

    got = graph_get_node(
        character_id="graph", node_type="thread", node_id=int(thread["id"])
    )
    assert got["title"] == "Coroutine finally"
    hits = graph_search(character_id="graph", query="B193")
    assert any(hit["node_type"] == "post" for hit in hits)
