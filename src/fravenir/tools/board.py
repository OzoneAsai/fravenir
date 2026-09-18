"""MCP adapters for the source-board layer."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal, TypeVar

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from fravenir.core import board as _board

_T = TypeVar("_T")


def _as_tool_error(fn: Callable[[], _T]) -> _T:
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
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False)
    )
    def board_search(query: str, limit: int = 20) -> list[dict[str, object]]:
        """thread titleとpost本文を横断検索する。"""
        return _as_tool_error(lambda: _board.search_board(
            character_id=character_id,
            query=query,
            limit=limit,
        ))
