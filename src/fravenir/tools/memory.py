"""Register the character-memory MCP tools."""

from __future__ import annotations

from typing import Literal

import structlog
from mcp.server.fastmcp import FastMCP

from fravenir.core.delete import memory_delete as _core_delete
from fravenir.core.explore import memory_explore as _core_explore
from fravenir.core.extraction import ExtractionClient
from fravenir.core.get import memory_get as _core_get
from fravenir.core.search import memory_search as _core_search
from fravenir.core.trace import memory_trace as _core_trace
from fravenir.core.write import memory_write as _core_write
from fravenir.embedding import Embedder
from fravenir.schemas.config import AppConfig
from fravenir.schemas.provenance import SourceRef

_logger = structlog.get_logger(__name__)


def register_memory_tools(
    mcp: FastMCP,
    *,
    config: AppConfig,
    embedder: Embedder,
    extraction_client: ExtractionClient | None,
) -> None:
    """Register the existing memory surface on ``mcp``.

    Keeping registration separate from server construction makes later board and
    graph tool groups independent and keeps the MCP SDK migration localized.
    """
    character_id = config.character.id

    @mcp.tool()
    def memory_write(
        content: str,
        kind: Literal["facts", "state", "emo"] = "facts",
        importance: int = 1,
        session_id: str | None = None,
    ) -> dict[str, object]:
        """記憶を1件書き込む。"""
        try:
            return _core_write(
                content=content,
                kind=kind,
                importance=importance,
                session_id=session_id,
                character_id=character_id,
                config=config,
                embedder=embedder,
                extraction_client=extraction_client,
            )
        except Exception as e:
            _logger.exception("memory_write_error", error=str(e))
            raise RuntimeError("Internal server error in memory_write") from None

    @mcp.tool()
    def memory_derive(
        content: str,
        sources: list[SourceRef],
        kind: Literal["facts", "state", "emo"] = "facts",
        importance: int = 1,
        session_id: str | None = None,
    ) -> dict[str, object]:
        """原典ノードから整理済み記憶を作り、derived_from provenance を必ず残す。"""
        if not sources:
            raise ValueError("sources must not be empty")
        try:
            result = _core_write(
                content=content,
                kind=kind,
                importance=importance,
                session_id=session_id,
                character_id=character_id,
                config=config,
                embedder=embedder,
                extraction_client=extraction_client,
                source_refs=[(source.type, source.id) for source in sources],
            )
            result["sources"] = [source.model_dump(mode="json") for source in sources]
            return result
        except Exception as e:
            _logger.exception("memory_derive_error", error=str(e))
            raise RuntimeError("Internal server error in memory_derive") from None

    @mcp.tool()
    def memory_search(
        query: str,
        limit: int = 5,
        kind_filter: list[str] | None = None,
        min_importance: int = 1,
        include_archived: bool = False,
        include_suppressed: bool = False,
    ) -> list[dict[str, object]]:
        """関連記憶を検索（ACT-R活性化 + ベクトル類似度）。"""
        try:
            return _core_search(
                query=query,
                limit=limit,
                kind_filter=kind_filter,
                min_importance=min_importance,
                include_archived=include_archived,
                include_suppressed=include_suppressed,
                character_id=character_id,
                config=config,
                embedder=embedder,
            )
        except Exception as e:
            _logger.exception("memory_search_error", error=str(e))
            raise RuntimeError("Internal server error in memory_search") from None

    @mcp.tool()
    def memory_get(limit: int = 5) -> dict[str, object]:
        """自己紹介・最近の状態を返す（v1互換API）。"""
        try:
            return _core_get(
                limit=limit,
                character_id=character_id,
                config=config,
                embedder=embedder,
            )
        except Exception as e:
            _logger.exception("memory_get_error", error=str(e))
            raise RuntimeError("Internal server error in memory_get") from None

    @mcp.tool()
    def memory_delete(episode_id: int, reason: str) -> dict[str, object]:
        """論理削除（valid_to=now を立てるだけ、行は残る）。"""
        try:
            return _core_delete(
                episode_id=episode_id,
                reason=reason,
                character_id=character_id,
                config=config,
            )
        except Exception as e:
            _logger.exception("memory_delete_error", error=str(e))
            raise RuntimeError("Internal server error in memory_delete") from None

    @mcp.tool()
    def memory_trace(episode_id: int) -> dict[str, object]:
        """supersedes チェーンを遡及する。"""
        try:
            return _core_trace(
                episode_id=episode_id,
                character_id=character_id,
                config=config,
            )
        except Exception as e:
            _logger.exception("memory_trace_error", error=str(e))
            raise RuntimeError("Internal server error in memory_trace") from None

    @mcp.tool()
    def memory_explore(
        node_type: Literal["episode", "entity"],
        node_id: int,
        depth: int = 1,
        full: bool = False,
        exclude_episode_ids: list[int] | None = None,
        exclude_entity_ids: list[int] | None = None,
        include_archived: bool = False,
        include_suppressed: bool = False,
    ) -> dict[str, object]:
        """グラフを 1 ホップ深掘り（memory_search の補完、AI 主導の連想探索）。"""
        try:
            result = _core_explore(
                node_type=node_type,
                node_id=node_id,
                depth=depth,
                full=full,
                exclude_episode_ids=exclude_episode_ids,
                exclude_entity_ids=exclude_entity_ids,
                include_archived=include_archived,
                include_suppressed=include_suppressed,
                character_id=character_id,
                config=config,
            )
            return result.model_dump(mode="json")
        except (ValueError, NotImplementedError):
            raise
        except Exception as e:
            _logger.exception("memory_explore_error", error=str(e))
            raise RuntimeError("Internal server error in memory_explore") from None

    @mcp.tool()
    def memory_compact(dry_run: bool = False) -> dict[str, object]:
        """夜バッチを手動起動。"""
        from fravenir.core.compact import run_compact

        try:
            result = run_compact(
                character_id=character_id,
                config=config,
                dry_run=dry_run,
            )
            return result.to_dict()
        except Exception as e:
            _logger.exception("memory_compact_error", error=str(e))
            raise RuntimeError("Internal server error in memory_compact") from None
