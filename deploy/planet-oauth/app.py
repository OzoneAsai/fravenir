from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import os
import secrets
import sqlite3
import struct
import time
import urllib.request
from pathlib import Path
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit

import jwt
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse


PUBLIC_BASE_URL = os.environ.get("OAUTH_PUBLIC_BASE_URL", "").rstrip("/")
RESOURCE = os.environ.get("OAUTH_RESOURCE", PUBLIC_BASE_URL).rstrip("/")
DB_PATH = Path(os.environ.get("OAUTH_DB_PATH", "oauth.sqlite3"))
TOTP_SECRET = os.environ.get("OAUTH_TOTP_SECRET", "").replace(" ", "").upper()
SIGNING_SECRET = os.environ.get("OAUTH_SIGNING_SECRET", "")
TOKEN_TTL = int(os.environ.get("OAUTH_TOKEN_TTL_SECONDS", "3600"))
REFRESH_TTL = int(os.environ.get("OAUTH_REFRESH_TTL_SECONDS", "2592000"))
SCOPES = {"planet:read", "planet:write"}
DEFAULT_SCOPE = "planet:read planet:write"

app = FastAPI(title="Planet OAuth", version="1.0.0", docs_url=None, redoc_url=None)
attempts: dict[str, list[float]] = {}
registration_attempts: dict[str, list[float]] = {}
client_assertion_jtis: dict[str, int] = {}
chatgpt_jwks = jwt.PyJWKClient(
    "https://chatgpt.com/oauth/jwks.json",
    cache_keys=True,
    cache_jwk_set=True,
    lifespan=300,
    timeout=5,
    headers={"User-Agent": "PlanetOAuth/1.2"},
)


def now() -> int:
    return int(time.time())


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def db() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def init_db() -> None:
    if not PUBLIC_BASE_URL.startswith("https://"):
        raise RuntimeError("OAUTH_PUBLIC_BASE_URL must be an HTTPS URL")
    if RESOURCE != PUBLIC_BASE_URL:
        raise RuntimeError("OAUTH_RESOURCE must equal the canonical public origin")
    if len(TOTP_SECRET) < 16 or len(SIGNING_SECRET) < 32:
        raise RuntimeError("TOTP and signing secrets are missing or too short")
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with db() as connection:
        connection.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS clients (
                client_id TEXT PRIMARY KEY,
                redirect_uris TEXT NOT NULL,
                client_name TEXT NOT NULL,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS auth_requests (
                request_id TEXT PRIMARY KEY,
                client_id TEXT NOT NULL,
                redirect_uri TEXT NOT NULL,
                state TEXT NOT NULL,
                scope TEXT NOT NULL,
                resource TEXT NOT NULL,
                code_challenge TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                used INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS authorization_codes (
                code_hash TEXT PRIMARY KEY,
                client_id TEXT NOT NULL,
                redirect_uri TEXT NOT NULL,
                scope TEXT NOT NULL,
                resource TEXT NOT NULL,
                code_challenge TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                used INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS refresh_tokens (
                token_hash TEXT PRIMARY KEY,
                client_id TEXT NOT NULL,
                scope TEXT NOT NULL,
                resource TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                revoked INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )


@app.on_event("startup")
def startup() -> None:
    init_db()


def normalize_scope(scope: str) -> str:
    requested = set(scope.split()) if scope.strip() else set(SCOPES)
    if not requested or not requested.issubset(SCOPES):
        raise HTTPException(status_code=400, detail="invalid_scope")
    return " ".join(sorted(requested))


def allowed_redirect(uri: str) -> bool:
    try:
        parsed = urlsplit(uri)
        port = parsed.port
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    if parsed.scheme == "https" and host == "chatgpt.com":
        return parsed.path == "/connector_platform_oauth_redirect" or parsed.path.startswith(("/connector/oauth/", "/oauth/"))
    if parsed.scheme == "http" and host in {"localhost", "127.0.0.1", "::1"}:
        return bool(port) and parsed.path.startswith("/")
    return False


def client_redirect_allowed(client_id: str, redirect_uri: str) -> bool:
    with db() as connection:
        row = connection.execute("SELECT redirect_uris FROM clients WHERE client_id=?", (client_id,)).fetchone()
    return bool(row and redirect_uri in json.loads(row["redirect_uris"]))


def register_cimd_client(client_id: str, redirect_uri: str) -> bool:
    """Resolve and cache an RFC 7591 client metadata document used as client_id."""
    try:
        parsed = urlsplit(client_id)
        port = parsed.port
    except ValueError:
        return False
    if (
        parsed.scheme != "https"
        or (parsed.hostname or "").lower() != "chatgpt.com"
        or port is not None
        or parsed.query
        or parsed.fragment
        or not (parsed.path.startswith("/oauth/") and parsed.path.endswith("/client.json"))
    ):
        return False
    try:
        request = urllib.request.Request(
            client_id,
            headers={"Accept": "application/json", "User-Agent": "PlanetOAuth/1.1"},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            final = urlsplit(response.geturl())
            if final.scheme != "https" or (final.hostname or "").lower() != "chatgpt.com":
                return False
            raw = response.read(65537)
        if len(raw) > 65536:
            return False
        metadata = json.loads(raw)
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    if not isinstance(metadata, dict) or metadata.get("client_id", client_id) != client_id:
        return False
    redirect_uris = metadata.get("redirect_uris")
    if (
        not isinstance(redirect_uris, list)
        or not redirect_uris
        or len(redirect_uris) > 20
        or redirect_uri not in redirect_uris
        or not all(isinstance(uri, str) and allowed_redirect(uri) for uri in redirect_uris)
    ):
        return False
    methods = metadata.get("token_endpoint_auth_methods_supported")
    if methods is None:
        methods = [metadata.get("token_endpoint_auth_method", "none")]
    if not isinstance(methods, list) or "none" not in methods:
        return False
    client_name = str(metadata.get("client_name", "CIMD client"))[:200]
    with db() as connection:
        connection.execute(
            "INSERT INTO clients(client_id,redirect_uris,client_name,created_at) VALUES(?,?,?,?) "
            "ON CONFLICT(client_id) DO UPDATE SET redirect_uris=excluded.redirect_uris,client_name=excluded.client_name",
            (client_id, json.dumps(redirect_uris), client_name, now()),
        )
    return True


def verify_client_assertion(client_id: str, assertion_type: str, assertion: str) -> None:
    expected_type = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
    if assertion_type != expected_type or not assertion or len(assertion) > 16384:
        raise HTTPException(status_code=401, detail="invalid_client")
    parsed = urlsplit(client_id)
    if (
        parsed.scheme != "https"
        or (parsed.hostname or "").lower() != "chatgpt.com"
        or not (parsed.path.startswith("/oauth/") and parsed.path.endswith("/client.json"))
    ):
        raise HTTPException(status_code=401, detail="invalid_client")
    try:
        signing_key = chatgpt_jwks.get_signing_key_from_jwt(assertion)
        claims = jwt.decode(
            assertion,
            signing_key.key,
            algorithms=["RS256"],
            audience=f"{PUBLIC_BASE_URL}/oauth/token",
            issuer=client_id,
            subject=client_id,
            leeway=30,
            options={"require": ["iss", "sub", "aud", "exp", "iat", "jti"]},
        )
        expires = int(claims["exp"])
        issued = int(claims["iat"])
        jti = str(claims["jti"])
    except (jwt.PyJWTError, OSError, TypeError, ValueError):
        raise HTTPException(status_code=401, detail="invalid_client")
    current = now()
    if not jti or expires > current + 300 or issued > current + 30:
        raise HTTPException(status_code=401, detail="invalid_client")
    for known_jti, known_expiry in list(client_assertion_jtis.items()):
        if known_expiry < current:
            client_assertion_jtis.pop(known_jti, None)
    if jti in client_assertion_jtis:
        raise HTTPException(status_code=401, detail="invalid_client")
    client_assertion_jtis[jti] = expires


def redirect_url(uri: str, **params: str) -> str:
    parsed = urlsplit(uri)
    query = parse_qsl(parsed.query, keep_blank_values=True)
    query.extend((key, value) for key, value in params.items() if value is not None)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))


def redirect_with(uri: str, **params: str) -> RedirectResponse:
    return RedirectResponse(redirect_url(uri, **params), status_code=302)


def totp_for_step(step: int) -> str:
    key = base64.b32decode(TOTP_SECRET + "=" * (-len(TOTP_SECRET) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{value % 1_000_000:06d}"


def verify_totp_once(code: str) -> bool:
    if len(code) != 6 or not code.isdigit():
        return False
    current = now() // 30
    matched: int | None = None
    for step in (current - 1, current, current + 1):
        if hmac.compare_digest(totp_for_step(step), code):
            matched = step
            break
    if matched is None:
        return False
    with db() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("SELECT value FROM settings WHERE key='last_totp_step'").fetchone()
        last = int(row["value"]) if row else -1
        if matched <= last:
            return False
        connection.execute(
            "INSERT INTO settings(key,value) VALUES('last_totp_step',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(matched),),
        )
    return True


def rate_limited(ip: str) -> bool:
    cutoff = time.time() - 300
    recent = [stamp for stamp in attempts.get(ip, []) if stamp >= cutoff]
    global_recent = [stamp for stamp in attempts.get("__global__", []) if stamp >= cutoff]
    if len(recent) >= 8 or len(global_recent) >= 20:
        attempts[ip] = recent
        attempts["__global__"] = global_recent
        return True
    stamp = time.time()
    recent.append(stamp)
    global_recent.append(stamp)
    attempts[ip] = recent
    attempts["__global__"] = global_recent
    return False


def registration_rate_limited(ip: str) -> bool:
    cutoff = time.time() - 3600
    recent = [stamp for stamp in registration_attempts.get(ip, []) if stamp >= cutoff]
    if len(recent) >= 20:
        registration_attempts[ip] = recent
        return True
    recent.append(time.time())
    registration_attempts[ip] = recent
    return False


def jwt_access_token(client_id: str, scope: str, resource: str) -> str:
    issued = now()
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "iss": PUBLIC_BASE_URL,
        "sub": "totp-owner",
        "aud": resource,
        "client_id": client_id,
        "scope": scope,
        "iat": issued,
        "exp": issued + TOKEN_TTL,
        "jti": secrets.token_urlsafe(16),
    }
    signing_input = f"{b64url(json.dumps(header, separators=(',', ':')).encode())}.{b64url(json.dumps(payload, separators=(',', ':')).encode())}"
    signature = hmac.new(SIGNING_SECRET.encode(), signing_input.encode("ascii"), hashlib.sha256).digest()
    return f"{signing_input}.{b64url(signature)}"


def issue_tokens(client_id: str, scope: str, resource: str) -> dict[str, object]:
    refresh = secrets.token_urlsafe(48)
    with db() as connection:
        connection.execute(
            "INSERT INTO refresh_tokens(token_hash,client_id,scope,resource,expires_at) VALUES(?,?,?,?,?)",
            (token_hash(refresh), client_id, scope, resource, now() + REFRESH_TTL),
        )
    return {
        "access_token": jwt_access_token(client_id, scope, resource),
        "token_type": "Bearer",
        "expires_in": TOKEN_TTL,
        "refresh_token": refresh,
        "scope": scope,
    }


def html_page(request_id: str, error: str = "") -> HTMLResponse:
    nonce = secrets.token_urlsafe(18)
    error_html = f'<p class="error">{html.escape(error)}</p>' if error else ""
    body = f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Planet MCP authorization</title>
<style>body{{font-family:system-ui;background:#101418;color:#edf2f7;display:grid;place-items:center;min-height:100vh;margin:0}}main{{width:min(420px,calc(100% - 40px));background:#1b232c;padding:28px;border-radius:16px;box-shadow:0 12px 40px #0008}}h1{{font-size:1.35rem}}input{{font-size:1.6rem;letter-spacing:.35rem;width:100%;box-sizing:border-box;padding:12px;border-radius:9px;border:1px solid #526170;background:#0c1116;color:white}}button{{margin-top:16px;width:100%;padding:13px;border:0;border-radius:9px;background:#55d6a0;color:#062117;font-weight:700}}button:disabled{{opacity:.55}}.error{{color:#ff9b9b}}.success{{color:#78efb7;font-weight:700}}small{{color:#aeb9c4}}</style></head>
<body><main><h1>Planet MCPを認証</h1><p id="status">Authenticatorの6桁コードだけを入力してください。</p>{error_html}
<form id="authorize-form" method="post" action="/oauth/authorize"><input type="hidden" name="request_id" value="{html.escape(request_id)}">
<input name="totp" inputmode="numeric" autocomplete="one-time-code" pattern="[0-9]{{6}}" maxlength="6" autofocus required>
<button type="submit" name="approve" value="yes">認証して接続</button></form>
<p><small>要求権限: Planetの読み取り・書き込み</small></p></main>
<script nonce="{nonce}">
const form=document.getElementById('authorize-form');
const statusText=document.getElementById('status');
form.addEventListener('submit',async(event)=>{{
  event.preventDefault();
  const button=form.querySelector('button');
  button.disabled=true;
  button.textContent='確認中…';
  statusText.className='';
  statusText.textContent='コードを確認しています…';
  const fields=new URLSearchParams(new FormData(form));
  fields.set('approve','yes');
  try{{
    const response=await fetch(form.action,{{method:'POST',credentials:'same-origin',headers:{{'Content-Type':'application/x-www-form-urlencoded','X-OAuth-Interactive':'1'}},body:fields}});
    const result=await response.json();
    if(!response.ok||!result.ok)throw new Error(result.error||'認証できませんでした。');
    form.hidden=true;
    statusText.className='success';
    statusText.textContent='認証に成功しました。ChatGPTへ戻っています…';
    setTimeout(()=>window.location.assign(result.redirect_to),900);
  }}catch(error){{
    statusText.className='error';
    statusText.textContent=error.message||'認証できませんでした。';
    button.disabled=false;
    button.textContent='認証して接続';
  }}
}});
</script></body></html>"""
    return HTMLResponse(body, headers={"Cache-Control": "no-store", "Content-Security-Policy": f"default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-{nonce}'; connect-src 'self'; form-action 'self'; frame-ancestors 'none'", "X-Frame-Options": "DENY"})


@app.exception_handler(HTTPException)
async def oauth_error(request: Request, exc: HTTPException) -> JSONResponse:
    detail = str(exc.detail)
    if request.url.path.startswith("/oauth/"):
        return JSONResponse({"error": detail}, status_code=exc.status_code, headers={"Cache-Control": "no-store"})
    return JSONResponse({"detail": detail}, status_code=exc.status_code)


@app.get("/.well-known/oauth-protected-resource/mcp")
@app.get("/.well-known/oauth-protected-resource")
def protected_resource_metadata() -> dict[str, object]:
    return {
        "resource": RESOURCE,
        "authorization_servers": [PUBLIC_BASE_URL],
        "scopes_supported": sorted(SCOPES),
        "bearer_methods_supported": ["header"],
    }


@app.get("/.well-known/openid-configuration")
@app.get("/.well-known/oauth-authorization-server")
def authorization_server_metadata() -> dict[str, object]:
    return {
        "issuer": PUBLIC_BASE_URL,
        "authorization_endpoint": f"{PUBLIC_BASE_URL}/oauth/authorize",
        "token_endpoint": f"{PUBLIC_BASE_URL}/oauth/token",
        "registration_endpoint": f"{PUBLIC_BASE_URL}/oauth/register",
        "client_id_metadata_document_supported": True,
        "authorization_response_iss_parameter_supported": True,
        "revocation_endpoint": f"{PUBLIC_BASE_URL}/oauth/revoke",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        # ChatGPT's CIMD supports both methods. Advertising only the public-client
        # method makes the selection deterministic; PKCE S256 authenticates the
        # authorization-code exchange without a per-client secret.
        "token_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": sorted(SCOPES),
    }


@app.post("/oauth/register")
async def register(request: Request) -> JSONResponse:
    ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "unknown").split(",")[0].strip()
    if registration_rate_limited(ip):
        raise HTTPException(status_code=429, detail="too_many_requests")
    if request.headers.get("content-length") and int(request.headers["content-length"]) > 32768:
        raise HTTPException(status_code=413, detail="request too large")
    payload = await request.json()
    redirect_uris = payload.get("redirect_uris")
    if not isinstance(redirect_uris, list) or not redirect_uris or len(redirect_uris) > 10:
        raise HTTPException(status_code=400, detail="invalid_redirect_uris")
    if not all(isinstance(uri, str) and allowed_redirect(uri) for uri in redirect_uris):
        raise HTTPException(status_code=400, detail="redirect_uri_not_allowed")
    method = payload.get("token_endpoint_auth_method", "none")
    if method != "none":
        raise HTTPException(status_code=400, detail="only public PKCE clients are supported")
    client_id = secrets.token_urlsafe(24)
    client_name = str(payload.get("client_name", "MCP client"))[:200]
    with db() as connection:
        connection.execute(
            "INSERT INTO clients(client_id,redirect_uris,client_name,created_at) VALUES(?,?,?,?)",
            (client_id, json.dumps(redirect_uris), client_name, now()),
        )
    return JSONResponse({
        "client_id": client_id,
        "client_id_issued_at": now(),
        "redirect_uris": redirect_uris,
        "client_name": client_name,
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
    }, status_code=201, headers={"Cache-Control": "no-store"})


@app.get("/oauth/authorize")
def authorize_get(
    response_type: str,
    client_id: str,
    redirect_uri: str,
    state: str,
    code_challenge: str,
    code_challenge_method: str,
    resource: str,
    scope: str = DEFAULT_SCOPE,
) -> HTMLResponse:
    if response_type != "code" or code_challenge_method != "S256" or len(code_challenge) < 43:
        raise HTTPException(status_code=400, detail="authorization code with PKCE S256 is required")
    known_client = client_redirect_allowed(client_id, redirect_uri)
    if not known_client:
        known_client = register_cimd_client(client_id, redirect_uri)
    if resource.rstrip("/") != RESOURCE or not known_client:
        raise HTTPException(status_code=400, detail="invalid client, redirect URI, or resource")
    normalized_scope = normalize_scope(scope)
    request_id = secrets.token_urlsafe(32)
    with db() as connection:
        connection.execute(
            "INSERT INTO auth_requests(request_id,client_id,redirect_uri,state,scope,resource,code_challenge,expires_at) VALUES(?,?,?,?,?,?,?,?)",
            (request_id, client_id, redirect_uri, state, normalized_scope, RESOURCE, code_challenge, now() + 300),
        )
    return html_page(request_id)


@app.post("/oauth/authorize")
async def authorize_post(request: Request):
    form = parse_qs((await request.body()).decode("utf-8"), keep_blank_values=True)
    interactive = request.headers.get("x-oauth-interactive") == "1"
    request_id = form.get("request_id", [""])[0]
    code = form.get("totp", [""])[0].strip()
    approved = form.get("approve", [""])[0] == "yes"
    with db() as connection:
        row = connection.execute("SELECT * FROM auth_requests WHERE request_id=?", (request_id,)).fetchone()
    if not row or row["used"] or row["expires_at"] < now():
        raise HTTPException(status_code=400, detail="authorization request expired")
    if not approved:
        return redirect_with(
            row["redirect_uri"],
            error="access_denied",
            state=row["state"],
            iss=PUBLIC_BASE_URL,
        )
    ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "unknown").split(",")[0].strip()
    if rate_limited(ip):
        if interactive:
            return JSONResponse({"ok": False, "error": "試行回数が多すぎます。5分後に再試行してください。"}, status_code=429, headers={"Cache-Control": "no-store"})
        return html_page(request_id, "試行回数が多すぎます。5分後に再試行してください。")
    if not verify_totp_once(code):
        if interactive:
            return JSONResponse({"ok": False, "error": "コードが違うか、すでに使用済みです。"}, status_code=400, headers={"Cache-Control": "no-store"})
        return html_page(request_id, "コードが違うか、すでに使用済みです。")
    authorization_code = secrets.token_urlsafe(40)
    with db() as connection:
        connection.execute("BEGIN IMMEDIATE")
        updated = connection.execute(
            "UPDATE auth_requests SET used=1 WHERE request_id=? AND used=0 AND expires_at>=?",
            (request_id, now()),
        ).rowcount
        if updated != 1:
            raise HTTPException(status_code=400, detail="authorization request already used")
        connection.execute(
            "INSERT INTO authorization_codes(code_hash,client_id,redirect_uri,scope,resource,code_challenge,expires_at) VALUES(?,?,?,?,?,?,?)",
            (token_hash(authorization_code), row["client_id"], row["redirect_uri"], row["scope"], row["resource"], row["code_challenge"], now() + 120),
        )
    attempts.pop(ip, None)
    location = redirect_url(
        row["redirect_uri"],
        code=authorization_code,
        state=row["state"],
        iss=PUBLIC_BASE_URL,
    )
    if interactive:
        return JSONResponse({"ok": True, "redirect_to": location}, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})
    return RedirectResponse(location, status_code=302)


@app.post("/oauth/token")
async def token(request: Request) -> JSONResponse:
    form = parse_qs((await request.body()).decode("utf-8"), keep_blank_values=True)
    grant_type = form.get("grant_type", [""])[0]
    client_id = form.get("client_id", [""])[0]
    client_assertion = form.get("client_assertion", [""])[0]
    if client_assertion:
        verify_client_assertion(
            client_id,
            form.get("client_assertion_type", [""])[0],
            client_assertion,
        )
    resource = form.get("resource", [""])[0].rstrip("/")
    if resource != RESOURCE:
        raise HTTPException(status_code=400, detail="invalid_target")
    if grant_type == "authorization_code":
        raw_code = form.get("code", [""])[0]
        redirect_uri = form.get("redirect_uri", [""])[0]
        verifier = form.get("code_verifier", [""])[0]
        with db() as connection:
            row = connection.execute("SELECT * FROM authorization_codes WHERE code_hash=?", (token_hash(raw_code),)).fetchone()
        if not row or row["used"] or row["expires_at"] < now():
            raise HTTPException(status_code=400, detail="invalid_grant")
        expected = b64url(hashlib.sha256(verifier.encode("ascii")).digest()) if verifier else ""
        if client_id != row["client_id"] or redirect_uri != row["redirect_uri"] or resource != row["resource"] or not hmac.compare_digest(expected, row["code_challenge"]):
            raise HTTPException(status_code=400, detail="invalid_grant")
        with db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            updated = connection.execute("UPDATE authorization_codes SET used=1 WHERE code_hash=? AND used=0", (token_hash(raw_code),)).rowcount
            if updated != 1:
                raise HTTPException(status_code=400, detail="invalid_grant")
        result = issue_tokens(client_id, row["scope"], resource)
    elif grant_type == "refresh_token":
        raw_refresh = form.get("refresh_token", [""])[0]
        with db() as connection:
            row = connection.execute("SELECT * FROM refresh_tokens WHERE token_hash=?", (token_hash(raw_refresh),)).fetchone()
        if not row or row["revoked"] or row["expires_at"] < now() or row["client_id"] != client_id or row["resource"] != resource:
            raise HTTPException(status_code=400, detail="invalid_grant")
        with db() as connection:
            connection.execute("UPDATE refresh_tokens SET revoked=1 WHERE token_hash=?", (token_hash(raw_refresh),))
        result = issue_tokens(client_id, row["scope"], resource)
    else:
        raise HTTPException(status_code=400, detail="unsupported_grant_type")
    return JSONResponse(result, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})


@app.post("/oauth/revoke")
async def revoke(request: Request) -> JSONResponse:
    form = parse_qs((await request.body()).decode("utf-8"), keep_blank_values=True)
    raw_token = form.get("token", [""])[0]
    if raw_token:
        with db() as connection:
            connection.execute("UPDATE refresh_tokens SET revoked=1 WHERE token_hash=?", (token_hash(raw_token),))
    return JSONResponse({}, headers={"Cache-Control": "no-store"})


@app.get("/oauth/health")
def health() -> dict[str, object]:
    return {"ok": True, "issuer": PUBLIC_BASE_URL, "resource": RESOURCE}
