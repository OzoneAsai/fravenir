"""Register graph MCP tools."""

from __future__ import annotations

from typing import Literal

from mcp.server.fastmcp import FastMCP

from fravenir.core import graph as core


def register_graph_tools(mcp: FastMCP, *, character_id: str) -> None:
    """Expose graph traversal and controlled relation editing."""

    @mcp.tool()
    def graph_get_node(
        node_type: Literal["episode", "entity", "space", "thread", "post"],
        node_id: int,
    ) -> dict[str, object]:
        """グラフノードを型とIDで取得する。"""
        return core.graph_get_node(
            character_id=character_id, node_type=node_type, node_id=node_id
        )

    @mcp.tool()
    def graph_neighbors(
        node_type: Literal["episode", "entity", "space", "thread", "post"],
        node_id: int,
        predicates: list[str] | None = None,
        direction: Literal["incoming", "outgoing", "both"] = "both",
        include_archived: bool = False,
        limit: int = 100,
    ) -> dict[str, object]:
        """ノードに接続する relation と隣接ノードを取得する。"""
        return core.graph_neighbors(
            character_id=character_id,
            node_type=node_type,
            node_id=node_id,
            predicates=predicates,
            direction=direction,
            include_archived=include_archived,
            limit=limit,
        )

    @mcp.tool()
    def graph_link(
        src_type: Literal["episode", "entity", "space", "thread", "post"],
        src_id: int,
        dst_type: Literal["episode", "entity", "space", "thread", "post"],
        dst_id: int,
        predicate: str,
        strength: float = 1.0,
        description: str | None = None,
        allow_custom_predicate: bool = False,
    ) -> dict[str, object]:
        """ノード間に relation を張る。同一のライブ relation は重複作成しない。"""
        return core.graph_link(
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

    @mcp.tool()
    def graph_invalidate_relation(relation_id: int) -> dict[str, object]:
        """relation を物理削除せず valid_to を設定して無効化する。"""
        return core.graph_invalidate_relation(
            character_id=character_id, relation_id=relation_id
        )

    @mcp.tool()
    def graph_search(query: str, limit: int = 30) -> list[dict[str, object]]:
        """memory/board のノードを横断して文字列検索する。"""
        return core.graph_search(character_id=character_id, query=query, limit=limit)
