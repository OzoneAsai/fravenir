"""MCP server entry point.

One server process is bound to one character. Tool registration is split into
domain modules so the board and graph surfaces can grow without turning this
module into a monolith.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from fravenir.core.extraction import ExtractionClient
from fravenir.embedding import Embedder
from fravenir.schemas.config import AppConfig
from fravenir.tools.memory import register_memory_tools


def build_server(
    config: AppConfig,
    embedder: Embedder | None = None,
    extraction_client: ExtractionClient | None = None,
    host: str | None = None,
    port: int | None = None,
) -> FastMCP:
    """Build an MCP server bound to a specific character.

    Host/port are retained here for v1 compatibility. They will move to the
    transport runner during the MCP SDK v2 migration.
    """
    character_id = config.character.id
    emb = embedder if embedder is not None else Embedder(config.embedding)

    ext: ExtractionClient | None
    if extraction_client is not None:
        ext = extraction_client
    elif config.extraction.enabled:
        ext = ExtractionClient(config.extraction)
    else:
        ext = None

    fastmcp_kwargs: dict[str, object] = {"name": f"fravenir_{character_id}"}
    if host is not None:
        fastmcp_kwargs["host"] = host
    if port is not None:
        fastmcp_kwargs["port"] = port
    mcp: FastMCP = FastMCP(**fastmcp_kwargs)  # type: ignore[arg-type]

    register_memory_tools(
        mcp,
        character_id=character_id,
        config=config,
        embedder=emb,
        extraction_client=ext,
    )
    return mcp
