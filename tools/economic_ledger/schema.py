"""Database schema migrations runner for the economic ledger with true atomic transactions."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


class MigrationError(Exception):
    pass


def split_sql_statements(sql_text: str) -> list[str]:
    """Split complete SQLite statements, including trigger bodies."""
    clean_lines = []
    for line in sql_text.splitlines():
        trimmed = line.strip()
        if trimmed.startswith("--"):
            continue
        clean_lines.append(line)
    clean_sql = "\n".join(clean_lines)

    statements = []
    pending = ""
    for char in clean_sql:
        pending += char
        if char == ";" and sqlite3.complete_statement(pending):
            stmt = pending.strip()
            if stmt:
                statements.append(stmt)
            pending = ""
    if pending.strip():
        raise MigrationError("Incomplete SQL migration statement")
    return statements


def run_migrations(conn: sqlite3.Connection) -> list[int]:
    """Applies all pending migrations in order, recording applied versions atomically.

    Guarantees:
    1. PRAGMA foreign_keys is NEVER toggled inside an active transaction.
    2. Before table recreation migrations, foreign keys are disabled on the connection level.
    3. PRAGMA foreign_key_check is performed BEFORE commit to verify relational integrity.
    4. Migration failures trigger complete atomic rollback without partial state.
    5. PRAGMA foreign_keys is restored to ON after each migration attempt.

    Returns the list of newly applied migration versions.
    """
    conn.execute("PRAGMA foreign_keys = ON;")

    # Ensure migration tracking table exists
    cursor = conn.cursor()
    cursor.execute("BEGIN IMMEDIATE;")
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at INTEGER NOT NULL
        );
        """
    )
    cursor.execute("COMMIT;")

    # Query currently applied versions
    cursor.execute("SELECT version FROM schema_migrations ORDER BY version ASC;")
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
        statements = split_sql_statements(sql_content)
        now = int(time.time())

        # Toggle foreign_keys OFF outside of the transaction to allow table migrations
        conn.execute("PRAGMA foreign_keys = OFF;")
        cursor.execute("BEGIN IMMEDIATE;")
        try:
            for stmt in statements:
                cursor.execute(stmt)

            # Check foreign key integrity BEFORE committing
            cursor.execute("PRAGMA foreign_key_check;")
            fk_violations = cursor.fetchall()
            if fk_violations:
                raise MigrationError(
                    f"Foreign key constraint violation during migration {filename}: {fk_violations}"
                )

            cursor.execute(
                "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?);",
                (version, filename, now),
            )
            cursor.execute("COMMIT;")
            newly_applied.append(version)
        except Exception as exc:
            try:
                cursor.execute("ROLLBACK;")
            except Exception:
                pass
            raise MigrationError(f"Failed to apply migration {filename}: {exc}") from exc
        finally:
            # Always restore foreign_keys = ON outside transaction
            conn.execute("PRAGMA foreign_keys = ON;")

    return newly_applied
