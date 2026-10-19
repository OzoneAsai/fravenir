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
    rename_space,
    search_board,
    set_thread_status,
    trash_item,
    update_thread,
)
from fravenir.storage.sqlite_init import init_kv


def _init(tmp_project: Path, character_id: str = "board_test") -> str:
    data = tmp_project / "data" / character_id
    data.mkdir(parents=True)
    init_kv(data / "kv.sqlite")
    return character_id


def test_space_rename_preserves_children_and_rejects_conflicts(tmp_project: Path) -> None:
    character_id = _init(tmp_project)
    space = create_space(character_id=character_id, name="Original", description="Keep this")
    space_id = int(space["space_id"])
    thread = create_thread(
        character_id=character_id,
        space_id=space_id,
        title="Keep this thread",
        author_kind="human",
        author_display_name="Admin",
        initial_post="Keep this post",
    )
    rename_space(
        character_id=character_id,
        space_id=space_id,
        name="Renamed",
        expected_name="Original",
    )
    listed = list_spaces(character_id=character_id)[0]
    assert (listed["id"], listed["name"], listed["description"], listed["thread_count"]) == (
        space_id,
        "Renamed",
        "Keep this",
        1,
    )
    detail = get_thread(character_id=character_id, thread_id=int(thread["thread_id"]))
    assert detail["thread"]["space_id"] == space_id
    assert detail["posts"][0]["body"] == "Keep this post"
    with pytest.raises(ValueError, match="stale space name"):
        rename_space(
            character_id=character_id,
            space_id=space_id,
            name="Stale",
            expected_name="Original",
        )
    create_space(character_id=character_id, name="Taken")
    with pytest.raises(ValueError, match="already exists"):
        rename_space(
            character_id=character_id,
            space_id=space_id,
            name="Taken",
            expected_name="Renamed",
        )
    trash_item(character_id=character_id, kind="space", item_id=space_id)
    with pytest.raises(ValueError, match="space not found"):
        rename_space(
            character_id=character_id,
            space_id=space_id,
            name="Hidden",
            expected_name="Renamed",
        )


def test_thread_title_and_archive_share_concurrency_and_preserve_posts(tmp_project: Path) -> None:
    character_id = _init(tmp_project)
    space = create_space(character_id=character_id, name="Board")
    thread = create_thread(
        character_id=character_id,
        space_id=int(space["space_id"]),
        title="Original",
        author_kind="human",
        author_display_name="Admin",
        initial_post="Keep this body",
    )
    thread_id = int(thread["thread_id"])
    renamed = update_thread(
        character_id=character_id,
        thread_id=thread_id,
        title="Renamed",
        expected_version=1,
    )
    assert renamed["version"] == 2
    closed = set_thread_status(
        character_id=character_id,
        thread_id=thread_id,
        status="closed",
        expected_version=2,
    )
    assert closed["version"] == 3
    with pytest.raises(ValueError, match="stale thread version"):
        update_thread(
            character_id=character_id,
            thread_id=thread_id,
            title="Stale",
            expected_version=2,
        )
    updated = update_thread(
        character_id=character_id,
        thread_id=thread_id,
        title="Archived title",
        expected_version=3,
    )
    assert (updated["status"], updated["version"]) == ("closed", 4)
    with pytest.raises(ValueError, match="closed thread"):
        add_post(
            character_id=character_id,
            thread_id=thread_id,
            body="Blocked",
            author_kind="human",
            author_display_name="Admin",
        )
    set_thread_status(
        character_id=character_id,
        thread_id=thread_id,
        status="open",
        expected_version=4,
    )
    detail = get_thread(character_id=character_id, thread_id=thread_id)
    assert detail["thread"]["title"] == "Archived title"
    assert detail["thread"]["status"] == "open"
    assert len(detail["posts"]) == 1
    assert detail["posts"][0]["body"] == "Keep this body"
    assert detail["posts"][0]["revision"] == 1
    trash_item(character_id=character_id, kind="space", item_id=int(space["space_id"]))
    with pytest.raises(ValueError, match="thread not found"):
        update_thread(
            character_id=character_id,
            thread_id=thread_id,
            title="Hidden",
            expected_version=5,
        )


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
