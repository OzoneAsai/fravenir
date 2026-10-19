from __future__ import annotations

import base64
import hashlib
import hmac
import json
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

OAUTH_ROOT = Path(r"C:\ProgramData\PlanetOAuth")
sys.path.insert(0, str(OAUTH_ROOT))
import app as totp_provider  # noqa: E402

ADMIN_UPSTREAM = "http://127.0.0.1:8281"
COOKIE_NAME = "__Host-fravenir-board"
SESSION_TTL_SECONDS = 8 * 60 * 60
SESSION_KEY = hmac.new(
    totp_provider.SIGNING_SECRET.encode("utf-8"),
    b"fravenir-board-session-v1",
    hashlib.sha256,
).digest()
HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "content-length",
    "host",
    "cookie",
    "authorization",
}


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _issue_session() -> str:
    now = int(time.time())
    payload = _b64(json.dumps({"v": 1, "iat": now, "exp": now + SESSION_TTL_SECONDS}, separators=(",", ":")).encode())
    signature = _b64(hmac.new(SESSION_KEY, payload.encode("ascii"), hashlib.sha256).digest())
    return f"{payload}.{signature}"


def _valid_session(value: str | None) -> bool:
    if not value or len(value) > 1024:
        return False
    try:
        payload_part, signature_part = value.split(".")
        expected = _b64(hmac.new(SESSION_KEY, payload_part.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(signature_part, expected):
            return False
        payload = json.loads(base64.urlsafe_b64decode(payload_part + "=" * (-len(payload_part) % 4)))
        now = int(time.time())
        return payload.get("v") == 1 and int(payload["iat"]) <= now + 60 and int(payload["exp"]) > now
    except (ValueError, KeyError, TypeError, json.JSONDecodeError, UnicodeDecodeError):
        return False


def _same_origin(request: Request) -> bool:
    try:
        origin = urlsplit(request.headers.get("origin", ""))
        public = urlsplit(totp_provider.PUBLIC_BASE_URL)
        return (
            origin.scheme.lower() == "https"
            and public.scheme.lower() == "https"
            and bool(origin.hostname)
            and origin.hostname.lower() == (public.hostname or "").lower()
            and origin.port in (None, 443)
            and public.port in (None, 443)
            and origin.username is None
            and origin.password is None
            and origin.path in ("", "/")
            and not origin.query
            and not origin.fragment
        )
    except ValueError:
        return False


def _same_login_origin(request: Request) -> bool:
    if _same_origin(request):
        return True
    fetch_site = request.headers.get("sec-fetch-site", "").lower()
    if fetch_site not in {"", "same-origin", "none"}:
        return False
    try:
        observed = urlsplit(str(request.url))
        public = urlsplit(totp_provider.PUBLIC_BASE_URL)
        return (
            observed.scheme.lower() == "https"
            and public.scheme.lower() == "https"
            and bool(observed.hostname)
            and observed.hostname.lower() == (public.hostname or "").lower()
            and observed.port in (None, 443)
            and public.port in (None, 443)
        )
    except ValueError:
        return False
def _client_ip(request: Request) -> str:
    if request.client is not None:
        return request.client.host
    return "unknown"


def _login_page(message: str = "") -> HTMLResponse:
    safe_message = (
        "<p role=\"alert\">認証コードを確認してください。コードは一度だけ使用できます。</p>"
        if message
        else ""
    )
    html = f"""<!doctype html>
<html lang="ja">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>Fravenir 掲示板ログイン</title>
<body>
<main>
<h1>Fravenir 掲示板</h1>
<p>Authenticator の6桁コードでログインしてください。</p>
{safe_message}
<form method="post" action="/login" autocomplete="on">
<label for="totp">認証コード</label>
<input id="totp" name="totp" inputmode="numeric" autocomplete="one-time-code"
       pattern="[0-9]{{6}}" minlength="6" maxlength="6" required autofocus>
<button type="submit">ログイン</button>
</form>
</main>
</body>
</html>"""
    return HTMLResponse(
        html,
        headers={
            "Cache-Control": "no-store",
            "Content-Security-Policy": "default-src 'none'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        },
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.client = httpx.AsyncClient(timeout=None, follow_redirects=False)
    try:
        yield
    finally:
        await app.state.client.aclose()


app = FastAPI(title="Fravenir Board TOTP Gate", docs_url=None, redoc_url=None, lifespan=lifespan)


@app.get("/login")
async def login_get(request: Request) -> Response:
    if _valid_session(request.cookies.get(COOKIE_NAME)):
        return RedirectResponse("/", status_code=303, headers={"Cache-Control": "no-store"})
    return _login_page()


@app.post("/login")
async def login_post(request: Request) -> Response:
    if not _same_login_origin(request):
        return Response("Forbidden", status_code=403, headers={"Cache-Control": "no-store"})
    body = await request.body()
    if len(body) > 1024:
        return Response("Bad request", status_code=400, headers={"Cache-Control": "no-store"})
    code = parse_qs(body.decode("utf-8", errors="ignore")).get("totp", [""])[0].strip()
    if totp_provider.rate_limited(_client_ip(request)):
        return Response("Too many attempts", status_code=429, headers={"Retry-After": "300", "Cache-Control": "no-store"})
    if not await run_in_threadpool(totp_provider.verify_totp_once, code):
        return _login_page("invalid")
    response = RedirectResponse("/?surface=board", status_code=303, headers={"Cache-Control": "no-store"})
    response.set_cookie(
        COOKIE_NAME,
        _issue_session(),
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )
    return response


@app.post("/logout")
async def logout(request: Request) -> Response:
    if not _same_origin(request):
        return Response("Forbidden", status_code=403, headers={"Cache-Control": "no-store"})
    response = RedirectResponse("/login", status_code=303, headers={"Cache-Control": "no-store"})
    response.delete_cookie(COOKIE_NAME, path="/", secure=True, httponly=True, samesite="strict")
    return response


@app.api_route(
    "/{path:path}",
    methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def protected_board(request: Request, path: str) -> Response:
    if not _valid_session(request.cookies.get(COOKIE_NAME)):
        if request.method in {"GET", "HEAD"} and not path.startswith("api/"):
            return RedirectResponse("/login", status_code=303, headers={"Cache-Control": "no-store"})
        return JSONResponse(
            {"detail": "TOTP login required"},
            status_code=401,
            headers={"Cache-Control": "no-store", "WWW-Authenticate": 'Session realm="Fravenir Board"'},
        )
    if request.method not in {"GET", "HEAD", "OPTIONS"} and not _same_origin(request):
        return Response("Forbidden", status_code=403, headers={"Cache-Control": "no-store"})
    target = f"{ADMIN_UPSTREAM}/{quote(path, safe='/')}"
    if request.url.query:
        target += f"?{request.url.query}"
    headers = {key: value for key, value in request.headers.items() if key.lower() not in HOP_BY_HOP}
    try:
        upstream = await request.app.state.client.send(
            httpx.Request(request.method, target, headers=headers, content=await request.body()),
            stream=True,
        )
    except httpx.HTTPError:
        return JSONResponse({"detail": "Board UI unavailable"}, status_code=502)
    response_headers = {
        key: value for key, value in upstream.headers.items() if key.lower() not in HOP_BY_HOP
    }
    response_headers["Cache-Control"] = "no-store"
    return StreamingResponse(
        upstream.aiter_raw(),
        status_code=upstream.status_code,
        headers=response_headers,
        background=BackgroundTask(upstream.aclose),
    )
