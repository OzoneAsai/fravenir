"""Tests for the additive board schema migration."""

from __future__ import annotations

import sqlite3

from fravenir.migrations.board import BOARD_TABLES, migrate


def test_board_migration_is_idempotent(tmp_path) -> None:
    db = tmp_path / "kv.sqlite"
    sqlite3.connect(db).close()

    preview = migrate(db, dry_run=True)
    assert preview.created_tables == list(BOARD_TABLES)

    first = migrate(db)
    assert first.created_tables == list(BOARD_TABLES)

    second = migrate(db)
    assert second.created_tables == []

    conn = sqlite3.connect(db)
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    finally:
        conn.close()
    assert set(BOARD_TABLES) <= tables
