from __future__ import annotations

import base64
import json
import os
import secrets
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlencode
import qrcode

ROOT = Path(r"C:\ProgramData\PlanetOAuth")
ENV = ROOT / "oauth.env"
URI_PATH = ROOT / "enrollment-uri.txt"
INTERNAL_QR = ROOT / "enrollment-qr.png"
DOWNLOAD_QR = Path(r"C:\Users\USER1\Downloads\Planet-MCP-Fravenir-TOTP-20261004.png")


def atomic_text(path: Path, text: str) -> None:
    temp = path.with_name(path.name + ".new-" + secrets.token_hex(6))
    temp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temp, path)


def main() -> None:
    if DOWNLOAD_QR.exists():
        raise RuntimeError("download QR destination already exists")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = ROOT / "backups" / ("totp-rotation-" + stamp)
    backup.mkdir(parents=True, exist_ok=False)
    for source in (ENV, URI_PATH, INTERNAL_QR):
        if not source.is_file():
            raise RuntimeError("required enrollment file is missing")
        shutil.copy2(source, backup / source.name)

    text = ENV.read_text(encoding="utf-8")
    db_value = next((line.split("=", 1)[1].strip().strip("\"'") for line in text.splitlines() if line.startswith("OAUTH_DB_PATH=")), None)
    if not db_value:
        raise RuntimeError("OAuth database path is missing")
    db_path = Path(db_value)
    with sqlite3.connect(db_path, timeout=15) as source_db, sqlite3.connect(backup / db_path.name) as backup_db:
        source_db.backup(backup_db)

    seed = base64.b32encode(os.urandom(20)).decode("ascii").rstrip("=")
    label = quote("Planet MCP:owner", safe="")
    uri = "otpauth://totp/" + label + "?" + urlencode({
        "secret": seed,
        "issuer": "Planet MCP",
        "algorithm": "SHA1",
        "digits": "6",
        "period": "30",
    })
    lines = text.splitlines()
    replaced = False
    for index, line in enumerate(lines):
        if line.startswith("OAUTH_TOTP_SECRET="):
            lines[index] = "OAUTH_TOTP_SECRET=" + seed
            replaced = True
            break
    if not replaced:
        raise RuntimeError("TOTP secret setting is missing")
    new_env = "\n".join(lines) + "\n"
    qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=12, border=4)
    qr.add_data(uri)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")
    temp_download = DOWNLOAD_QR.with_name(DOWNLOAD_QR.name + ".new")
    image.save(temp_download, format="PNG")
    temp_internal = INTERNAL_QR.with_name(INTERNAL_QR.name + ".new")
    image.save(temp_internal, format="PNG")

    changed = False
    try:
        atomic_text(ENV, new_env)
        changed = True
        atomic_text(URI_PATH, uri + "\n")
        os.replace(temp_internal, INTERNAL_QR)
        os.replace(temp_download, DOWNLOAD_QR)
        with sqlite3.connect(db_path, timeout=15) as connection:
            connection.execute("DELETE FROM settings WHERE key='last_totp_step'")
            connection.commit()
    except Exception:
        if changed:
            shutil.copy2(backup / ENV.name, ENV)
            shutil.copy2(backup / URI_PATH.name, URI_PATH)
            shutil.copy2(backup / INTERNAL_QR.name, INTERNAL_QR)
        if temp_download.exists():
            temp_download.replace(backup / "uncommitted-download-qr.png")
        if DOWNLOAD_QR.exists():
            DOWNLOAD_QR.replace(backup / "uncommitted-download-qr.png")
        if temp_internal.exists():
            temp_internal.replace(backup / "uncommitted-internal-qr.png")
        raise

    status = {
        "result": "SUCCESS",
        "backup_directory": str(backup),
        "download_qr": str(DOWNLOAD_QR),
        "qr_bytes": DOWNLOAD_QR.stat().st_size,
        "created_local": datetime.now().astimezone().isoformat(),
    }
    (ROOT / "totp-rotation.status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
    print(json.dumps(status))


if __name__ == "__main__":
    main()