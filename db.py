"""SQLite access + tiny forward-only migration runner."""
from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .config import settings, BASE_DIR

MIGRATIONS_DIR = BASE_DIR / "migrations"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id() -> str:
    return str(uuid.uuid4())


def _connect() -> sqlite3.Connection:
    Path(settings.database_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.database_path, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def db():
    conn = _connect()
    try:
        yield conn
    finally:
        conn.close()


def migrate() -> list[str]:
    """Apply pending migrations in filename order. Returns applied names."""
    applied: list[str] = []
    with db() as c:
        c.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
        done = {r["name"] for r in c.execute("SELECT name FROM schema_migrations")}
        for f in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if f.name in done:
                continue
            c.executescript("BEGIN;" + f.read_text() + f"\nINSERT INTO schema_migrations VALUES ('{f.name}', '{now()}');COMMIT;")
            applied.append(f.name)
    return applied


def row(conn: sqlite3.Connection, sql: str, *args) -> dict | None:
    r = conn.execute(sql, args).fetchone()
    return dict(r) if r else None
