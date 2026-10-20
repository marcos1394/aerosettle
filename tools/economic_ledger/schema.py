"""Database schema migrations runner for the economic ledger."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


class MigrationError(Exception):
    pass


def run_migrations(conn: sqlite3.Connection) -> list[int]:
    """Applies all pending migrations in order, recording applied versions.
    
    Returns the list of newly applied migration versions.
    """
    conn.execute("PRAGMA foreign_keys = ON;")
    
    # Ensure migration tracking table exists
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at INTEGER NOT NULL
        );
    """)
    conn.commit()

    # Query currently applied versions
    cursor = conn.execute("SELECT version FROM schema_migrations ORDER BY version ASC;")
    applied_versions = {row[0] for row in cursor.fetchall()}

    # Discover migration files
    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    newly_applied = []

    for mfile in migration_files:
        filename = mfile.name
        try:
            version_str = filename.split("_", 1)[0]
            version = int(version_str)
        except (ValueError, IndexError) as exc:
            raise MigrationError(f"Invalid migration filename format: {filename}") from exc

        if version in applied_versions:
            continue

        sql_content = mfile.read_text(encoding="utf-8")
        now = int(time.time())

        # Apply migration inside an isolated transaction
        try:
            with conn:
                conn.executescript(sql_content)
                conn.execute(
                    "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?);",
                    (version, filename, now)
                )
            newly_applied.append(version)
        except Exception as exc:
            raise MigrationError(f"Failed to apply migration {filename}: {exc}") from exc

    return newly_applied
