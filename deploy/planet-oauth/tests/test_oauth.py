"""Exercise the distributed server using generated secrets and a temporary DB only."""

import base64
import hashlib
import importlib.util
import re
import secrets
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("OAUTH_PUBLIC_BASE_URL", "https://oauth.example.com")
    monkeypatch.setenv("OAUTH_RESOURCE", "https://oauth.example.com")
    monkeypatch.setenv("OAUTH_DB_PATH", str(tmp_path / "oauth.sqlite3"))
    monkeypatch.setenv("OAUTH_TOTP_SECRET", base64.b32encode(secrets.token_bytes(20)).decode())
    monkeypatch.setenv("OAUTH_SIGNING_SECRET", secrets.token_hex(32))
    spec = importlib.util.spec_from_file_location(
        "isolated_planet_oauth", Path(__file__).parents[1] / "app.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with TestClient(module.app) as client:
        yield module, client


def test_discovery_and_registration_rejection(server):
    module, client = server
    assert client.get("/oauth/health").status_code == 200
    metadata = client.get("/.well-known/oauth-authorization-server").json()
    assert metadata["issuer"] == module.PUBLIC_BASE_URL
    assert metadata["code_challenge_methods_supported"] == ["S256"]
    response = client.post(
        "/oauth/register", json={"redirect_uris": ["https://evil.example.com/callback"]}
    )
    assert response.status_code == 400
    with module.db() as connection:
        assert connection.execute("SELECT COUNT(*) FROM clients").fetchone()[0] == 0


def test_pkce_totp_code_replay_refresh_and_revocation(server):
    module, client = server
    redirect_uri = "http://127.0.0.1:9000/callback"
    registration = client.post("/oauth/register", json={"redirect_uris": [redirect_uri]})
    assert registration.status_code == 201
    client_id = registration.json()["client_id"]
    verifier = secrets.token_urlsafe(48)
    challenge = module.b64url(hashlib.sha256(verifier.encode()).digest())
    response = client.get(
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "state": "fixture-state",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "resource": module.RESOURCE,
        },
    )
    assert response.status_code == 200
    request_id = re.search(r'name="request_id" value="([^"]+)"', response.text).group(1)
    approval = client.post(
        "/oauth/authorize",
        data={
            "request_id": request_id,
            "totp": module.totp_for_step(module.now() // 30),
            "approve": "yes",
        },
        headers={"X-OAuth-Interactive": "1"},
    )
    assert approval.status_code == 200
    callback = parse_qs(urlsplit(approval.json()["redirect_to"]).query)
    assert callback["state"] == ["fixture-state"]
    assert callback["iss"] == [module.PUBLIC_BASE_URL]
    exchange = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "resource": module.RESOURCE,
        "code": callback["code"][0],
        "code_verifier": verifier,
    }
    invalid = client.post("/oauth/token", data={**exchange, "code_verifier": "incorrect"})
    assert invalid.status_code == 400
    token = client.post("/oauth/token", data=exchange)
    assert token.status_code == 200
    assert token.headers["cache-control"] == "no-store"
    decoded = jwt.decode(
        token.json()["access_token"],
        module.SIGNING_SECRET,
        algorithms=["HS256"],
        audience=module.RESOURCE,
        issuer=module.PUBLIC_BASE_URL,
    )
    assert decoded["client_id"] == client_id
    assert client.post("/oauth/token", data=exchange).status_code == 400
    refresh = {
        "grant_type": "refresh_token",
        "client_id": client_id,
        "resource": module.RESOURCE,
        "refresh_token": token.json()["refresh_token"],
    }
    renewed = client.post("/oauth/token", data=refresh)
    assert renewed.status_code == 200
    assert client.post("/oauth/token", data=refresh).status_code == 400
    new_refresh = renewed.json()["refresh_token"]
    assert client.post("/oauth/revoke", data={"token": new_refresh}).status_code == 200
    assert (
        client.post("/oauth/token", data={**refresh, "refresh_token": new_refresh}).status_code
        == 400
    )


def test_totp_cannot_be_reused(server):
    module, _ = server
    code = module.totp_for_step(module.now() // 30)
    assert module.verify_totp_once(code)
    assert not module.verify_totp_once(code)
    assert not module.verify_totp_once("invalid")


def test_missing_secrets_refuses_database_creation(server, tmp_path):
    module, _ = server
    module.DB_PATH = tmp_path / "unconfigured" / "oauth.sqlite3"
    module.SIGNING_SECRET = ""
    with pytest.raises(RuntimeError, match="secrets are missing"):
        module.init_db()
    assert not module.DB_PATH.exists()
