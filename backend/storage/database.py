"""SQLite database bootstrap helpers."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Iterator

from backend.config import get_settings


MIGRATION_NAME = "0001_initial"


class Database:
    """Thin wrapper around sqlite3 with schema bootstrapping."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def initialize(self) -> None:
        """Create the database and apply the initial schema if needed."""

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    name TEXT PRIMARY KEY,
                    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            already_applied = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE name = ?",
                (MIGRATION_NAME,),
            ).fetchone()
            if already_applied:
                self._apply_runtime_migrations(connection)
                return

            sql_path = Path(__file__).resolve().parent / "migrations" / f"{MIGRATION_NAME}.sql"
            connection.executescript(sql_path.read_text(encoding="utf-8"))
            connection.execute(
                "INSERT INTO schema_migrations (name) VALUES (?)",
                (MIGRATION_NAME,),
            )
            self._apply_runtime_migrations(connection)

    def _apply_runtime_migrations(self, connection: sqlite3.Connection) -> None:
        """Apply additive schema updates needed for existing local databases."""

        self._ensure_column(connection, "runs", "stage", "TEXT NOT NULL DEFAULT 'pending'")
        self._ensure_column(connection, "runs", "progress_current", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_column(connection, "runs", "progress_total", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_column(connection, "runs", "progress_message", "TEXT")
        self._ensure_column(connection, "runs", "finished_at", "TEXT")

        self._ensure_column(connection, "run_models", "status", "TEXT NOT NULL DEFAULT 'pending'")
        self._ensure_column(connection, "run_models", "progress_current", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_column(connection, "run_models", "progress_total", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_column(connection, "run_models", "progress_message", "TEXT")
        self._ensure_column(connection, "run_models", "started_at", "TEXT")
        self._ensure_column(connection, "run_models", "finished_at", "TEXT")
        self._ensure_column(connection, "run_models", "error_message", "TEXT")

        self._ensure_column(connection, "run_sources", "status", "TEXT NOT NULL DEFAULT 'pending'")
        self._ensure_column(connection, "run_sources", "completed_count", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_column(connection, "run_sources", "failed_count", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_column(connection, "run_sources", "progress_current", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_column(connection, "run_sources", "progress_total", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_column(connection, "run_sources", "progress_message", "TEXT")
        self._ensure_column(connection, "run_sources", "started_at", "TEXT")
        self._ensure_column(connection, "run_sources", "finished_at", "TEXT")
        self._ensure_column(connection, "run_sources", "error_message", "TEXT")

        self._ensure_column(connection, "llm_calls", "started_at", "TEXT")
        self._ensure_column(connection, "llm_calls", "finished_at", "TEXT")

    @staticmethod
    def _ensure_column(
        connection: sqlite3.Connection,
        table_name: str,
        column_name: str,
        column_sql: str,
    ) -> None:
        existing_columns = {
            row["name"]
            for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        if column_name in existing_columns:
            return
        connection.execute(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}"
        )

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


@lru_cache(maxsize=1)
def get_database() -> Database:
    """Return the singleton database handle."""

    settings = get_settings()
    database = Database(settings.database.path)
    database.initialize()
    return database
