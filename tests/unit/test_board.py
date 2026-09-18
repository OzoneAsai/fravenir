"""Tests for the board/source layer."""

from __future__ import annotations

from pathlib import Path

import pytest

from fravenir.core.board import (
    add_post,
    create_space,
    create_thread,
    edit_post,
    get_post_revision,
    get_post_sources,
    get_thread,
    list_spaces,
    list_threads,
    organize_thread,
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


def test_edit_post_preserves_revision_and_rejects_stale_writer(tmp_project: Path) -> None:
    character_id = _init(tmp_project, "board_edit")
    space = create_space(character_id=character_id, name="research")
    thread = create_thread(
        character_id=character_id,
        space_id=int(space["space_id"]),
        title="revision",
        author_kind="human",
        author_display_name="Ozone",
        initial_post="old text",
    )
    before = get_thread(character_id=character_id, thread_id=int(thread["thread_id"]))
    post_id = int(before["posts"][0]["id"])

    edited = edit_post(
        character_id=character_id,
        post_id=post_id,
        body="new text",
        expected_revision=1,
        editor_kind="agent",
        editor_display_name="ChatGPT",
    )
    assert edited["revision"] == 2
    assert edited["thread_version"] == 2

    after = get_thread(character_id=character_id, thread_id=int(thread["thread_id"]))
    assert after["posts"][0]["body"] == "new text"
    assert after["posts"][0]["revision"] == 2

    with pytest.raises(ValueError, match="stale post revision"):
        edit_post(
            character_id=character_id,
            post_id=post_id,
            body="stale overwrite",
            expected_revision=1,
            editor_kind="agent",
            editor_display_name="Other agent",
        )


def test_organize_thread_preserves_exact_source_revisions(tmp_project: Path) -> None:
    character_id = _init(tmp_project, "board_organize")
    space = create_space(character_id=character_id, name="research")
    thread = create_thread(
        character_id=character_id,
        space_id=int(space["space_id"]),
        title="organize",
        author_kind="human",
        author_display_name="Ozone",
        initial_post="first source",
    )
    added = add_post(
        character_id=character_id,
        thread_id=int(thread["thread_id"]),
        body="second source",
        author_kind="agent",
        author_display_name="ChatGPT",
    )
    assert added["thread_version"] == 2

    before = get_thread(character_id=character_id, thread_id=int(thread["thread_id"]))
    source_ids = [int(post["id"]) for post in before["posts"]]

    organized = organize_thread(
        character_id=character_id,
        thread_id=int(thread["thread_id"]),
        summary="two sources summarized",
        source_post_ids=source_ids,
        expected_thread_version=2,
        author_kind="agent",
        author_display_name="Organizer",
    )
    assert organized["thread_version"] == 3

    source_rows = get_post_sources(
        character_id=character_id,
        post_id=int(organized["summary_post_id"]),
    )
    assert [(row["source_post_id"], row["source_revision"]) for row in source_rows] == [
        (source_ids[0], 1),
        (source_ids[1], 1),
    ]

    after = get_thread(character_id=character_id, thread_id=int(thread["thread_id"]))
    assert after["posts"][-1]["kind"] == "summary"
    assert after["posts"][-1]["body"] == "two sources summarized"

    with pytest.raises(ValueError, match="stale thread version"):
        organize_thread(
            character_id=character_id,
            thread_id=int(thread["thread_id"]),
            summary="stale summary",
            source_post_ids=source_ids,
            expected_thread_version=2,
            author_kind="agent",
            author_display_name="Stale organizer",
        )


def test_get_post_revision_recovers_historical_body(tmp_project: Path) -> None:
    character_id = _init(tmp_project, "board_revision_read")
    space = create_space(character_id=character_id, name="research")
    thread = create_thread(
        character_id=character_id,
        space_id=int(space["space_id"]),
        title="history",
        author_kind="human",
        author_display_name="Ozone",
        initial_post="revision one",
    )
    data = get_thread(character_id=character_id, thread_id=int(thread["thread_id"]))
    post_id = int(data["posts"][0]["id"])

    edit_post(
        character_id=character_id,
        post_id=post_id,
        body="revision two",
        expected_revision=1,
        editor_kind="human",
        editor_display_name="Ozone",
    )

    old = get_post_revision(
        character_id=character_id,
        post_id=post_id,
        revision=1,
    )
    current = get_post_revision(
        character_id=character_id,
        post_id=post_id,
    )
    assert old["body"] == "revision one"
    assert old["revision"] == 1
    assert old["current_revision"] == 2
    assert current["body"] == "revision two"
    assert current["revision"] == 2
