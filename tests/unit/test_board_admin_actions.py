"""Exercise human board actions through the admin API against an isolated database."""

from pathlib import Path

from fastapi.testclient import TestClient

from fravenir.admin.server import create_app
from fravenir.storage.sqlite_init import init_kv


def test_admin_board_edits_and_archive_preserve_content(tmp_project: Path, monkeypatch) -> None:
    monkeypatch.delenv("FRAVENIR_ADMIN_USER", raising=False)
    monkeypatch.delenv("FRAVENIR_ADMIN_PASSWORD", raising=False)
    data = tmp_project / "data" / "ui_test"
    data.mkdir()
    init_kv(data / "kv.sqlite")
    with TestClient(create_app("ui_test")) as client:
        space = client.post("/api/board/spaces", json={"name": "Original"}).json()
        space_url = f"/api/board/spaces/{space['space_id']}"
        renamed = client.patch(space_url, json={"name": "Renamed", "expected_name": "Original"})
        assert renamed.status_code == 200
        assert renamed.json()["name"] == "Renamed"
        stale = client.patch(space_url, json={"name": "Stale", "expected_name": "Original"})
        assert stale.status_code == 409
        thread = client.post(
            "/api/board/threads",
            json={
                "space_id": space["space_id"],
                "title": "Original title",
                "author_display_name": "Human admin",
                "initial_post": "Original body",
            },
        ).json()
        thread_url = f"/api/board/threads/{thread['thread_id']}"
        renamed = client.patch(thread_url, json={"title": "New title", "expected_version": 1})
        assert renamed.status_code == 200
        assert renamed.json()["version"] == 2
        closed = client.patch(
            thread_url + "/status",
            json={
                "status": "closed",
                "expected_version": 2,
            },
        )
        assert closed.status_code == 200
        assert closed.json()["status"] == "closed"
        blocked = client.post(
            thread_url + "/posts",
            json={
                "body": "Blocked reply",
                "author_display_name": "Human admin",
            },
        )
        assert blocked.status_code == 409
        stale = client.patch(thread_url, json={"title": "Stale title", "expected_version": 2})
        assert stale.status_code == 409
        opened = client.patch(
            thread_url + "/status",
            json={
                "status": "open",
                "expected_version": 3,
            },
        )
        assert opened.status_code == 200
        edited = client.patch(
            f"/api/board/posts/{thread['initial_post_id']}",
            json={
                "body": "Edited body",
                "expected_revision": 1,
                "editor_kind": "human",
                "editor_display_name": "Human admin",
            },
        )
        assert edited.status_code == 200
        detail = client.get(thread_url).json()
        assert detail["thread"]["title"] == "New title"
        assert detail["thread"]["status"] == "open"
        assert len(detail["posts"]) == 1
        assert detail["posts"][0]["body"] == "Edited body"
        assert detail["posts"][0]["revision"] == 2
