"""MCP adapters for the source-board layer."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from fravenir.core import board as _board


def _as_tool_error[T](fn: Callable[[], T]) -> T:
    try:
        return fn()
    except ValueError as e:
        raise ToolError(str(e)) from e


def register_board_tools(mcp: MCPServer, *, character_id: str) -> None:
    """Register board tools for one character-local knowledge space."""

    @mcp.tool(
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=False,
            open_world_hint=False,
        )
    )
    def board_create_space(name: str, description: str | None = None) -> dict[str, object]:
        """掲示板のspaceを作成する。"""
        return _as_tool_error(lambda: _board.create_space(
            character_id=character_id,
            name=name,
            description=description,
        ))

    @mcp.tool(
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False)
    )
    def board_get_post_revision(
        post_id: int,
        revision: int | None = None,
    ) -> dict[str, object]:
        """postの現在または指定revisionの原文を取得する。"""
        return _as_tool_error(
            lambda: _board.get_post_revision(
                character_id=character_id,
                post_id=post_id,
                revision=revision,
            )
        )

    @mcp.tool(
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False)
    )
    def board_list_spaces() -> list[dict[str, object]]:
        """利用可能なspaceとthread数を一覧する。"""
        return _as_tool_error(lambda: _board.list_spaces(character_id=character_id))

    @mcp.tool(
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=False,
            open_world_hint=False,
        )
    )
    def board_create_thread(
        space_id: int,
        title: str,
        author_display_name: str,
        author_kind: Literal["human", "agent", "system"] = "agent",
        author_external_subject: str | None = None,
        initial_post: str | None = None,
    ) -> dict[str, object]:
        """space内にthreadを作成し、必要なら最初の投稿も追加する。"""
        return _as_tool_error(lambda: _board.create_thread(
            character_id=character_id,
            space_id=space_id,
            title=title,
            author_kind=author_kind,
            author_display_name=author_display_name,
            author_external_subject=author_external_subject,
            initial_post=initial_post,
        ))

    @mcp.tool(
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False)
    )
    def board_list_threads(
        space_id: int | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, object]]:
        """threadを更新順で一覧する。"""
        return _as_tool_error(lambda: _board.list_threads(
            character_id=character_id,
            space_id=space_id,
            status=status,
            limit=limit,
        ))

    @mcp.tool(
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False)
    )
    def board_get_thread(thread_id: int) -> dict[str, object]:
        """thread本文と投稿を原典のまま取得する。"""
        return _as_tool_error(
            lambda: _board.get_thread(
                character_id=character_id,
                thread_id=thread_id,
            )
        )

    @mcp.tool(
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=False,
            open_world_hint=False,
        )
    )
    def board_post(
        thread_id: int,
        body: str,
        author_display_name: str,
        author_kind: Literal["human", "agent", "system"] = "agent",
        author_external_subject: str | None = None,
        kind: Literal["message", "summary", "decision", "note"] = "message",
        parent_post_id: int | None = None,
    ) -> dict[str, object]:
        """threadへ追記する。既存投稿は変更しない。"""
        return _as_tool_error(lambda: _board.add_post(
            character_id=character_id,
            thread_id=thread_id,
            body=body,
            author_kind=author_kind,
            author_display_name=author_display_name,
            author_external_subject=author_external_subject,
            kind=kind,
            parent_post_id=parent_post_id,
        ))

    @mcp.tool(
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=False,
            open_world_hint=False,
        )
    )
    def board_edit_post(
        post_id: int,
        body: str,
        expected_revision: int,
        editor_display_name: str,
        editor_kind: Literal["human", "agent", "system"] = "agent",
        editor_external_subject: str | None = None,
    ) -> dict[str, object]:
        """postをrevision一致時だけ編集し、旧本文を履歴へ保存する。"""
        return _as_tool_error(
            lambda: _board.edit_post(
                character_id=character_id,
                post_id=post_id,
                body=body,
                expected_revision=expected_revision,
                editor_kind=editor_kind,
                editor_display_name=editor_display_name,
                editor_external_subject=editor_external_subject,
            )
        )

    @mcp.tool(
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=False,
            open_world_hint=False,
        )
    )
    def board_organize_thread(
        thread_id: int,
        summary: str,
        source_post_ids: list[int],
        expected_thread_version: int,
        author_display_name: str,
        author_kind: Literal["human", "agent", "system"] = "agent",
        author_external_subject: str | None = None,
    ) -> dict[str, object]:
        """threadを原典保持のままsummary Postへ整理する。"""
        return _as_tool_error(
            lambda: _board.organize_thread(
                character_id=character_id,
                thread_id=thread_id,
                summary=summary,
                source_post_ids=source_post_ids,
                expected_thread_version=expected_thread_version,
                author_kind=author_kind,
                author_display_name=author_display_name,
                author_external_subject=author_external_subject,
            )
        )

    @mcp.tool(
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False)
    )
    def board_post_sources(post_id: int) -> list[dict[str, object]]:
        """summary等のPostが参照した原典Post revisionを取得する。"""
        return _as_tool_error(
            lambda: _board.get_post_sources(
                character_id=character_id,
                post_id=post_id,
            )
        )

    @mcp.tool(
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False)
    )
    def board_search(query: str, limit: int = 20) -> list[dict[str, object]]:
        """thread titleとpost本文を横断検索する。"""
        return _as_tool_error(lambda: _board.search_board(
            character_id=character_id,
            query=query,
            limit=limit,
        ))
