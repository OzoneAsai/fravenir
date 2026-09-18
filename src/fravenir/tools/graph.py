"""MCP adapters for generic graph inspection and organization."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from fravenir.core import graph_api as _graph


def _as_tool_error[T](fn: Callable[[], T]) -> T:
    try:
        return fn()
    except ValueError as e:
        raise ToolError(str(e)) from e


def register_graph_tools(mcp: MCPServer, *, character_id: str) -> None:
    """Register graph tools used by a human-triggered organizing agent."""

    @mcp.tool(
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False)
    )
    def graph_get_node(
        node_type: Literal["episode", "entity", "thread", "post"],
        node_id: int,
    ) -> dict[str, object]:
        """任意nodeの現在状態を取得する。"""
        return _as_tool_error(
            lambda: _graph.get_node(
                character_id=character_id,
                node_type=node_type,
                node_id=node_id,
            )
        )

    @mcp.tool(
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False)
    )
    def graph_neighbors(
        node_type: Literal["episode", "entity", "thread", "post"],
        node_id: int,
        direction: Literal["incoming", "outgoing", "both"] = "both",
        predicates: list[str] | None = None,
        include_archived: bool = False,
        limit: int = 100,
    ) -> dict[str, object]:
        """node周辺のrelationsと隣接nodeを取得する。"""
        return _as_tool_error(
            lambda: _graph.get_neighbors(
                character_id=character_id,
                node_type=node_type,
                node_id=node_id,
                direction=direction,
                predicates=predicates,
                include_archived=include_archived,
                limit=limit,
            )
        )

    @mcp.tool(
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False)
    )
    def graph_search(
        query: str,
        node_types: list[Literal["episode", "entity", "thread", "post"]] | None = None,
        limit: int = 30,
    ) -> list[dict[str, object]]:
        """episode/entity/thread/postを横断して文字列検索する。"""
        return _as_tool_error(
            lambda: _graph.search_nodes(
                character_id=character_id,
                query=query,
                node_types=node_types,
                limit=limit,
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
    def graph_link(
        src_type: Literal["episode", "entity", "thread", "post"],
        src_id: int,
        dst_type: Literal["episode", "entity", "thread", "post"],
        dst_id: int,
        predicate: str,
        strength: float = 1.0,
        description: str | None = None,
        allow_custom_predicate: bool = False,
    ) -> dict[str, object]:
        """原典を変更せず、2 node間に意味関係を追加する。"""
        return _as_tool_error(
            lambda: _graph.add_relation(
                character_id=character_id,
                src_type=src_type,
                src_id=src_id,
                dst_type=dst_type,
                dst_id=dst_id,
                predicate=predicate,
                strength=strength,
                description=description,
                allow_custom_predicate=allow_custom_predicate,
            )
        )

    @mcp.tool(
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=True,
            idempotent_hint=True,
            open_world_hint=False,
        )
    )
    def graph_unlink(relation_id: int) -> dict[str, object]:
        """relationを削除せずvalid_toを立てて無効化する。"""
        return _as_tool_error(
            lambda: _graph.invalidate_relation(
                character_id=character_id,
                relation_id=relation_id,
            )
        )
