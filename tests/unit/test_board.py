"""Unit tests for the collaborative board core."""

from __future__ import annotations

import sqlite3

import pytest

from fravenir.core.board import (
    BoardConflictError,
    board_create_actor,
    board_create_space,
    board_create_thread,
    board_edit_post,
    board_get_thread,
    board_list_spaces,
    board_post,
    board_search,
)
from fravenir.storage.paths import kv_db_path
from fravenir.storage.sqlite_init import init_kv


def _init(tmp_project, character_id: str = "board") -> None:
    d = tmp_project / "data" / character_id
    d.mkdir(parents=True)
    init_kv(d / "kv.sqlite")


def test_board_roundtrip_and_search(tmp_project) -> None:
    _init(tmp_project)
    actor = board_create_actor(
        character_id="board", display_name="ChatGPT", kind="agent"
    )
    space = board_create_space(
        character_id="board",
        slug="jadx",
        name="JADX",
        created_by=int(actor["id"]),
    )
    thread = board_create_thread(
        character_id="board",
        space_id=int(space["id"]),
        title="finally reconstruction",
        body="B193 を調査する",
        created_by=int(actor["id"]),
    )

    assert thread["version"] == 1
    assert len(thread["posts"]) == 1
    posted = board_post(
        character_id="board",
        thread_id=int(thread["id"]),
        body="SGET preparation を確認",
        author_id=int(actor["id"]),
        expected_version=1,
    )
    assert posted["thread_version"] == 2

    got = board_get_thread(character_id="board", thread_id=int(thread["id"]))
    assert got["version"] == 2
    assert [p["body"] for p in got["posts"]] == [
        "B193 を調査する",
        "SGET preparation を確認",
    ]
    assert board_list_spaces(character_id="board")[0]["slug"] == "jadx"
    hits = board_search(character_id="board", query="SGET")
    assert hits[0]["node_type"] == "post"
    assert "SGET" in str(hits[0]["body"])


def test_board_stale_thread_write_is_rejected(tmp_project) -> None:
    _init(tmp_project)
    space = board_create_space(character_id="board", slug="general", name="General")
    thread = board_create_thread(
        character_id="board", space_id=int(space["id"]), title="topic"
    )
    board_post(
        character_id="board",
        thread_id=int(thread["id"]),
        body="first",
        expected_version=1,
    )

    with pytest.raises(BoardConflictError, match="stale thread version"):
        board_post(
            character_id="board",
            thread_id=int(thread["id"]),
            body="stale",
            expected_version=1,
        )


def test_post_edit_preserves_revision(tmp_project) -> None:
    _init(tmp_project)
    space = board_create_space(character_id="board", slug="general", name="General")
    thread = board_create_thread(
        character_id="board",
        space_id=int(space["id"]),
        title="topic",
        body="original",
    )
    post_id = int(thread["posts"][0]["id"])

    edited = board_edit_post(
        character_id="board",
        post_id=post_id,
        body="edited",
        expected_revision=1,
    )
    assert edited["revision"] == 2
    assert edited["body"] == "edited"

    conn = sqlite3.connect(kv_db_path("board"))
    try:
        row = conn.execute(
            "SELECT revision, body FROM post_revisions WHERE post_id = ?", (post_id,)
        ).fetchone()
    finally:
        conn.close()
    assert row == (1, "original")

    with pytest.raises(BoardConflictError, match="stale post revision"):
        board_edit_post(
            character_id="board",
            post_id=post_id,
            body="stale edit",
            expected_revision=1,
        )
