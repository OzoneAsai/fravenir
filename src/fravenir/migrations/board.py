"""Create the board tables used by human/agent collaboration."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

BOARD_TABLES = ("actors", "spaces", "threads", "posts", "post_revisions")

BOARD_DDL = """\
CREATE TABLE IF NOT EXISTS actors (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    kind             TEXT NOT NULL,
    display_name     TEXT NOT NULL,
    external_subject TEXT,
    created_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_actors_external_subject
    ON actors(external_subject) WHERE external_subject IS NOT NULL;

CREATE TABLE IF NOT EXISTS spaces (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    slug        TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    description TEXT,
    created_by  INTEGER REFERENCES actors(id),
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS threads (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    space_id   INTEGER NOT NULL REFERENCES spaces(id),
    title      TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'open',
    created_by INTEGER REFERENCES actors(id),
    version    INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_threads_space_updated
    ON threads(space_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_threads_status ON threads(status);

CREATE TABLE IF NOT EXISTS posts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id      INTEGER NOT NULL REFERENCES threads(id),
    parent_post_id INTEGER REFERENCES posts(id),
    author_id      INTEGER REFERENCES actors(id),
    kind           TEXT NOT NULL DEFAULT 'message',
    body           TEXT NOT NULL,
    revision       INTEGER NOT NULL DEFAULT 1,
    created_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    edited_at      TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_posts_thread ON posts(thread_id, id);
CREATE INDEX IF NOT EXISTS idx_posts_parent ON posts(parent_post_id);

CREATE TABLE IF NOT EXISTS post_revisions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id    INTEGER NOT NULL REFERENCES posts(id),
    revision   INTEGER NOT NULL,
    body       TEXT NOT NULL,
    edited_by  INTEGER REFERENCES actors(id),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(post_id, revision)
);
CREATE INDEX IF NOT EXISTS idx_post_revisions_post
    ON post_revisions(post_id, revision);
"""


@dataclass(frozen=True)
class MigrationResult:
    created_tables: list[str] = field(default_factory=list)
    dry_run: bool = False


def _has_table(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    return row is not None


def migrate(db_path: Path, *, dry_run: bool = False) -> MigrationResult:
    conn = sqlite3.connect(db_path)
    try:
        missing = [table for table in BOARD_TABLES if not _has_table(conn, table)]
        if missing and not dry_run:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.executescript(BOARD_DDL)
            conn.commit()
        return MigrationResult(created_tables=missing, dry_run=dry_run)
    finally:
        conn.close()
