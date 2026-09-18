"""Tests for the board/source layer."""

from __future__ import annotations

from pathlib import Path

import pytest

from fravenir.core.board import (
    add_post,
    create_space,
    create_thread,
    get_thread,
    list_spaces,
    list_threads,
    search_board,
)
from fravenir.storage.sqlite_init import init_kv


def _init(tmp_project: Path, character_id: str = "board_test") -> str:
    data = tmp_project / "data" / character_id
    data.mkdir(parents=True)
    init_kv(data / "kv.sqlite")
    return character_id


def test_board_roundtrip(tmp_project: Path) -> None:
    character_id = _init(tmp_project)

    space = create_space(
        character_id=character_id,
        name="JADX",
        description="Decompiler research",
    )
    thread = create_thread(
        character_id=character_id,
        space_id=int(space["space_id"]),
        title="finally reconstruction",
        author_kind="human",
        author_display_name="Ozone",
        initial_post="B193 を調べる",
    )
    assert thread["version"] == 1

    posted = add_post(
        character_id=character_id,
        thread_id=int(thread["thread_id"]),
        body="SGET 準備との関係を確認",
        author_kind="agent",
        author_display_name="ChatGPT",
    )
    assert posted["thread_version"] == 2

    got = get_thread(character_id=character_id, thread_id=int(thread["thread_id"]))
    assert got["thread"]["title"] == "finally reconstruction"
    assert got["thread"]["version"] == 2
    assert [p["body"] for p in got["posts"]] == [
        "B193 を調べる",
        "SGET 準備との関係を確認",
    ]
    assert got["posts"][0]["author_name"] == "Ozone"
    assert got["posts"][1]["author_name"] == "ChatGPT"

    spaces = list_spaces(character_id=character_id)
    assert spaces[0]["thread_count"] == 1

    threads = list_threads(character_id=character_id, space_id=int(space["space_id"]))
    assert threads[0]["post_count"] == 2

    results = search_board(character_id=character_id, query="SGET")
    assert results[0]["result_type"] == "post"
    assert results[0]["thread_id"] == thread["thread_id"]


def test_reply_must_stay_in_same_thread(tmp_project: Path) -> None:
    character_id = _init(tmp_project, "board_reply")
    space = create_space(character_id=character_id, name="research")

    first = create_thread(
        character_id=character_id,
        space_id=int(space["space_id"]),
        title="one",
        author_kind="agent",
        author_display_name="ChatGPT",
        initial_post="first",
    )
    second = create_thread(
        character_id=character_id,
        space_id=int(space["space_id"]),
        title="two",
        author_kind="agent",
        author_display_name="ChatGPT",
        initial_post="second",
    )
    first_data = get_thread(character_id=character_id, thread_id=int(first["thread_id"]))
    foreign_parent = int(first_data["posts"][0]["id"])

    with pytest.raises(ValueError, match="different thread"):
        add_post(
            character_id=character_id,
            thread_id=int(second["thread_id"]),
            body="bad reply",
            author_kind="agent",
            author_display_name="ChatGPT",
            parent_post_id=foreign_parent,
        )


def test_duplicate_space_name_is_rejected(tmp_project: Path) -> None:
    character_id = _init(tmp_project, "board_space")
    create_space(character_id=character_id, name="JADX")

    with pytest.raises(ValueError, match="already exists"):
        create_space(character_id=character_id, name="JADX")
