from __future__ import annotations

import base64
import os
import secrets
from pathlib import Path
from urllib.parse import quote, urlencode


ROOT = Path(__file__).resolve().parent
ENV_PATH = ROOT / "oauth.env"
ENROLLMENT_PATH = ROOT / "enrollment-uri.txt"
PUBLIC_BASE = "https://prox042460.softether.net"


def main() -> None:
    if ENV_PATH.exists():
        print(f"existing configuration preserved: {ENV_PATH}")
        return
    totp_secret = base64.b32encode(os.urandom(20)).decode("ascii").rstrip("=")
    signing_secret = secrets.token_hex(32)
    lines = [
        f"OAUTH_PUBLIC_BASE_URL={PUBLIC_BASE}",
        f"OAUTH_RESOURCE={PUBLIC_BASE}",
        f"OAUTH_DB_PATH={ROOT / 'data' / 'oauth.sqlite3'}",
        f"OAUTH_TOTP_SECRET={totp_secret}",
        f"OAUTH_SIGNING_SECRET={signing_secret}",
        "OAUTH_TOKEN_TTL_SECONDS=3600",
        "OAUTH_REFRESH_TTL_SECONDS=2592000",
    ]
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    label = quote("Planet MCP:owner", safe="")
    query = urlencode({
        "secret": totp_secret,
        "issuer": "Planet MCP",
        "algorithm": "SHA1",
        "digits": "6",
        "period": "30",
    })
    ENROLLMENT_PATH.write_text(f"otpauth://totp/{label}?{query}\n", encoding="utf-8")
    print(f"created: {ENV_PATH}")
    print(f"created: {ENROLLMENT_PATH}")


if __name__ == "__main__":
    main()
