"""MCP adapters for provenance-aware knowledge derivation."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from fravenir.core.extraction import ExtractionClient
from fravenir.core.provenance import derive_memory_from_posts, get_episode_sources
from fravenir.embedding import Embedder
from fravenir.schemas.config import AppConfig


def _as_tool_error[T](fn: Callable[[], T]) -> T:
    try:
        return fn()
    except ValueError as e:
        raise ToolError(str(e)) from e


def register_provenance_tools(
    mcp: MCPServer,
    *,
    character_id: str,
    config: AppConfig,
    embedder: Embedder,
    extraction_client: ExtractionClient | None,
) -> None:
    """Register provenance-aware knowledge tools."""

    @mcp.tool(
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=False,
            open_world_hint=False,
        )
    )
    def memory_derive(
        content: str,
        source_post_ids: list[int],
        author_display_name: str,
        author_kind: Literal["human", "agent", "system"] = "agent",
        author_external_subject: str | None = None,
        kind: Literal["facts", "state", "emo"] = "facts",
        importance: int = 1,
    ) -> dict[str, object]:
        """掲示板postを原典として、出典付きのmemoryを作成する。"""
        return _as_tool_error(lambda: derive_memory_from_posts(
            character_id=character_id,
            config=config,
            embedder=embedder,
            extraction_client=extraction_client,
            content=content,
            source_post_ids=source_post_ids,
            author_kind=author_kind,
            author_display_name=author_display_name,
            author_external_subject=author_external_subject,
            kind=kind,
            importance=importance,
        ))

    @mcp.tool(
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False)
    )
    def memory_sources(episode_id: int) -> list[dict[str, object]]:
        """memoryがどの原典から導出されたかを取得する。"""
        return _as_tool_error(lambda: get_episode_sources(
            character_id=character_id,
            episode_id=episode_id,
        ))
