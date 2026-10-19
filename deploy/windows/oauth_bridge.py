from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import httpx
from dotenv import dotenv_values
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.background import BackgroundTask

PLANET_ENV = Path(r"C:\ProgramData\Planet\release\0.2.2-full-audit\planet\.env")
UPSTREAM = "http://127.0.0.1:8280"
HOP_BY_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers", "transfer-encoding", "upgrade"}

_config = {key: value or "" for key, value in dotenv_values(PLANET_ENV).items()}
_issuer = _config.get("PLANET_OAUTH_ISSUER", "").rstrip("/")
_audience = _config.get("PLANET_OAUTH_AUDIENCE", "").rstrip("/")
_signing_secret = _config.get("PLANET_OAUTH_SIGNING_SECRET", "")
_scopes = set(_config.get("PLANET_OAUTH_REQUIRED_SCOPES", "planet:read planet:write").split())
_public_base_url = _config.get("PLANET_PUBLIC_BASE_URL", _issuer).rstrip("/")
if not (_issuer and _audience and len(_signing_secret) >= 32 and _scopes):
    raise RuntimeError("Planet OAuth settings are missing or invalid; refusing to expose the MCP bridge")


def _decode_segment(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _valid_token(token: str) -> bool:
    if not token or len(token) > 4096:
        return False
    try:
        header_part, payload_part, signature_part = token.split(".")
        header = json.loads(_decode_segment(header_part))
        payload = json.loads(_decode_segment(payload_part))
        signature = _decode_segment(signature_part)
        signing_input = f"{header_part}.{payload_part}".encode("ascii")
        expected = hmac.new(_signing_secret.encode(), signing_input, hashlib.sha256).digest()
        expires = int(payload["exp"])
        issued = int(payload["iat"])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError, UnicodeDecodeError):
        return False
    if header.get("alg") != "HS256" or header.get("typ") != "JWT":
        return False
    if not hmac.compare_digest(signature, expected):
        return False
    now = int(time.time())
    if expires <= now or issued > now + 60:
        return False
    if str(payload.get("iss", "")).rstrip("/") != _issuer:
        return False
    audience = payload.get("aud")
    audiences = {audience} if isinstance(audience, str) else set(audience or [])
    if _audience not in {value.rstrip("/") for value in audiences if isinstance(value, str)}:
        return False
    return _scopes.issubset(set(str(payload.get("scope", "")).split()))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.client = httpx.AsyncClient(timeout=None, follow_redirects=False)
    try:
        yield
    finally:
        await app.state.client.aclose()


app = FastAPI(title="Fravenir MCP OAuth bridge", docs_url=None, redoc_url=None, lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "fravenir-mcp-bridge"}


@app.api_route("/{path:path}", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def forward(request: Request, path: str) -> Response:
    authorization = request.headers.get("authorization", "")
    token = authorization[7:] if authorization.startswith("Bearer ") else ""
    if not _valid_token(token):
        resource = f"{_public_base_url}/.well-known/oauth-protected-resource/mcp"
        challenge = f'Bearer resource_metadata="{resource}", scope="{" ".join(sorted(_scopes))}"'
        return JSONResponse(
            {"detail": "authentication required"},
            status_code=401,
            headers={"WWW-Authenticate": challenge, "Cache-Control": "no-store"},
        )

    target = f"{UPSTREAM}/{path}"
    if request.url.query:
        target = f"{target}?{request.url.query}"
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in HOP_BY_HOP | {"host", "authorization", "content-length"}
    }
    outgoing = httpx.Request(request.method, target, headers=headers, content=await request.body())
    try:
        upstream = await request.app.state.client.send(outgoing, stream=True)
    except httpx.HTTPError:
        return JSONResponse({"detail": "MCP backend unavailable"}, status_code=502)
    response_headers = {
        key: value for key, value in upstream.headers.items() if key.lower() not in HOP_BY_HOP
    }
    return StreamingResponse(
        upstream.aiter_raw(),
        status_code=upstream.status_code,
        headers=response_headers,
        background=BackgroundTask(upstream.aclose),
    )
