"""MCP server entry point.

A server process is bound to one character. Tool registration lives in
``fravenir.tools`` so the server bootstrap stays transport/framework focused.
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

    fastmcp_kwargs: dict[str, object] = {"name": f"fravenir_{character_id}"}
    if host is not None:
        fastmcp_kwargs["host"] = host
    if port is not None:
        fastmcp_kwargs["port"] = port
    mcp: FastMCP = FastMCP(**fastmcp_kwargs)  # type: ignore[arg-type]

    register_memory_tools(
        mcp,
        config=config,
        embedder=emb,
        extraction_client=ext,
    )
    return mcp
