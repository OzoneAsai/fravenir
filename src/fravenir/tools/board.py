"""Register MCP tools for the collaborative board surface."""

from __future__ import annotations

from typing import Literal

from mcp.server.fastmcp import FastMCP

from fravenir.core import board as core


def register_board_tools(mcp: FastMCP, *, character_id: str) -> None:
    """Register board tools on a character-bound MCP server."""

    @mcp.tool()
    def board_create_actor(
        display_name: str,
        kind: Literal["human", "agent", "system"] = "agent",
        external_subject: str | None = None,
    ) -> dict[str, object]:
        """掲示板の著者 actor を作成する。"""
        return core.board_create_actor(
            character_id=character_id,
            display_name=display_name,
            kind=kind,
            external_subject=external_subject,
        )

    @mcp.tool()
    def board_create_space(
        slug: str,
        name: str,
        description: str | None = None,
        created_by: int | None = None,
    ) -> dict[str, object]:
        """掲示板の space を作成する。"""
        return core.board_create_space(
            character_id=character_id,
            slug=slug,
            name=name,
            description=description,
            created_by=created_by,
        )

    @mcp.tool()
    def board_list_spaces() -> list[dict[str, object]]:
        """利用可能な space を一覧する。"""
        return core.board_list_spaces(character_id=character_id)

    @mcp.tool()
    def board_create_thread(
        space_id: int,
        title: str,
        body: str | None = None,
        created_by: int | None = None,
    ) -> dict[str, object]:
        """thread を作成し、必要なら最初の投稿も同時に作る。"""
        return core.board_create_thread(
            character_id=character_id,
            space_id=space_id,
            title=title,
            body=body,
            created_by=created_by,
        )

    @mcp.tool()
    def board_list_threads(
        space_id: int | None = None,
        status: Literal["open", "resolved", "archived"] | None = None,
        limit: int = 50,
    ) -> list[dict[str, object]]:
        """thread を更新順に一覧する。"""
        return core.board_list_threads(
            character_id=character_id,
            space_id=space_id,
            status=status,
            limit=limit,
        )

    @mcp.tool()
    def board_get_thread(thread_id: int) -> dict[str, object]:
        """thread とその投稿を取得する。"""
        return core.board_get_thread(character_id=character_id, thread_id=thread_id)

    @mcp.tool()
    def board_post(
        thread_id: int,
        body: str,
        author_id: int | None = None,
        parent_post_id: int | None = None,
        kind: Literal["message", "summary", "decision", "note"] = "message",
        expected_version: int | None = None,
    ) -> dict[str, object]:
        """thread に投稿する。expected_version 指定時は古い状態への書き込みを拒否する。"""
        return core.board_post(
            character_id=character_id,
            thread_id=thread_id,
            body=body,
            author_id=author_id,
            parent_post_id=parent_post_id,
            kind=kind,
            expected_version=expected_version,
        )

    @mcp.tool()
    def board_edit_post(
        post_id: int,
        body: str,
        expected_revision: int,
        edited_by: int | None = None,
    ) -> dict[str, object]:
        """投稿を編集し、旧本文を revision 履歴に保存する。"""
        return core.board_edit_post(
            character_id=character_id,
            post_id=post_id,
            body=body,
            expected_revision=expected_revision,
            edited_by=edited_by,
        )

    @mcp.tool()
    def board_search(query: str, limit: int = 20) -> list[dict[str, object]]:
        """thread title と post body を横断検索する。"""
        return core.board_search(character_id=character_id, query=query, limit=limit)
