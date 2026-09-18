"""MCP server entry point.

One server process is bound to one character. Tool registration is split into
domain modules so the board and graph surfaces can grow without turning this
module into a monolith.
"""

from __future__ import annotations

from mcp.server import MCPServer

from fravenir.core.extraction import ExtractionClient
from fravenir.embedding import Embedder
from fravenir.schemas.config import AppConfig
from fravenir.tools.board import register_board_tools
from fravenir.tools.memory import register_memory_tools


def build_server(
    config: AppConfig,
    embedder: Embedder | None = None,
    extraction_client: ExtractionClient | None = None,
) -> MCPServer:
    """Build an MCP server bound to a specific character."""
    character_id = config.character.id
    emb = embedder if embedder is not None else Embedder(config.embedding)

    ext: ExtractionClient | None
    if extraction_client is not None:
        ext = extraction_client
    elif config.extraction.enabled:
        ext = ExtractionClient(config.extraction)
    else:
        ext = None

    mcp = MCPServer(name=f"fravenir_{character_id}")
    register_memory_tools(
        mcp,
        character_id=character_id,
        config=config,
        embedder=emb,
        extraction_client=ext,
    )
    register_board_tools(mcp, character_id=character_id)
    return mcp
