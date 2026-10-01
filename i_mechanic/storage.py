"""Local persistence for race engineer projects, sessions, and chat."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from functools import wraps
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


def default_database_path() -> Path:
    """Return the per-user database path without creating it yet."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    root = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return root / "I Mechanic" / "i_mechanic.sqlite3"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json(value: Any) -> str | None:
    return None if value is None else json.dumps(value, ensure_ascii=False)


def _decode(value: str | None) -> Any:
    return None if value is None else json.loads(value)


def _thread_safe(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapped


class Repository:
    """Small SQLite repository that owns persistence boundaries for the app."""

    def __init__(self, database_path: str | Path | None = None):
        self.database_path = Path(database_path) if database_path else default_database_path()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.connection = sqlite3.connect(self.database_path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self._initialize()

    @_thread_safe
    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "Repository":
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()

    def _initialize(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                game TEXT NOT NULL DEFAULT '',
                car TEXT NOT NULL DEFAULT '',
                track TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',
                archived INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                telemetry_path TEXT NOT NULL,
                feedback TEXT NOT NULL DEFAULT '',
                brief_json TEXT,
                assessment_json TEXT,
                status TEXT NOT NULL DEFAULT 'created',
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                session_id INTEGER REFERENCES sessions(id) ON DELETE SET NULL,
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS sessions_project_idx ON sessions(project_id, created_at);
            CREATE INDEX IF NOT EXISTS messages_project_idx ON messages(project_id, created_at);
            """
        )
        current = self.connection.execute("SELECT value FROM metadata WHERE key = 'schema_version'").fetchone()
        if current is None:
            self.connection.execute(
                "INSERT INTO metadata(key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
        elif int(current["value"]) != SCHEMA_VERSION:
            raise RuntimeError(
                f"Unsupported database schema {current['value']}; expected {SCHEMA_VERSION}."
            )
        self.connection.commit()

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row is not None else None

    @_thread_safe
    def create_project(
        self,
        name: str,
        game: str = "",
        car: str = "",
        track: str = "",
        notes: str = "",
    ) -> dict[str, Any]:
        timestamp = _now()
        cursor = self.connection.execute(
            """
            INSERT INTO projects(name, game, car, track, notes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (name.strip() or "Untitled project", game.strip(), car.strip(), track.strip(), notes, timestamp, timestamp),
        )
        self.connection.commit()
        return self.get_project(cursor.lastrowid)

    @_thread_safe
    def update_project(self, project_id: int, **fields: str) -> dict[str, Any] | None:
        allowed = {"name", "game", "car", "track", "notes", "archived"}
        changes = {key: value for key, value in fields.items() if key in allowed}
        if not changes:
            return self.get_project(project_id)
        changes["updated_at"] = _now()
        assignments = ", ".join(f"{key} = ?" for key in changes)
        self.connection.execute(
            f"UPDATE projects SET {assignments} WHERE id = ?",
            (*changes.values(), project_id),
        )
        self.connection.commit()
        return self.get_project(project_id)

    @_thread_safe
    def get_project(self, project_id: int | None) -> dict[str, Any] | None:
        if project_id is None:
            return None
        return self._row(self.connection.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone())

    @_thread_safe
    def list_projects(self, include_archived: bool = False) -> list[dict[str, Any]]:
        query = "SELECT * FROM projects"
        params: tuple[Any, ...] = ()
        if not include_archived:
            query += " WHERE archived = 0"
        query += " ORDER BY updated_at DESC, id DESC"
        return [dict(row) for row in self.connection.execute(query, params)]

    @_thread_safe
    def create_session(self, project_id: int, telemetry_path: str, feedback: str = "") -> dict[str, Any]:
        timestamp = _now()
        cursor = self.connection.execute(
            """
            INSERT INTO sessions(project_id, telemetry_path, feedback, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (project_id, telemetry_path, feedback, timestamp, timestamp),
        )
        self.connection.commit()
        return self.get_session(cursor.lastrowid)

    @_thread_safe
    def update_session(self, session_id: int, **fields: Any) -> dict[str, Any] | None:
        allowed = {"telemetry_path", "feedback", "brief_json", "assessment_json", "status", "error"}
        changes = {key: _json(value) if key.endswith("_json") else value for key, value in fields.items() if key in allowed}
        if not changes:
            return self.get_session(session_id)
        changes["updated_at"] = _now()
        assignments = ", ".join(f"{key} = ?" for key in changes)
        self.connection.execute(f"UPDATE sessions SET {assignments} WHERE id = ?", (*changes.values(), session_id))
        self.connection.commit()
        return self.get_session(session_id)

    @_thread_safe
    def get_session(self, session_id: int | None) -> dict[str, Any] | None:
        if session_id is None:
            return None
        row = self._row(self.connection.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone())
        return self._decode_session(row)

    @_thread_safe
    def list_sessions(self, project_id: int, limit: int | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM sessions WHERE project_id = ? ORDER BY created_at DESC, id DESC"
        params: tuple[Any, ...] = (project_id,)
        if limit is not None:
            query += " LIMIT ?"
            params += (limit,)
        return [self._decode_session(dict(row)) for row in self.connection.execute(query, params)]

    @staticmethod
    def _decode_session(row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        row["brief_json"] = _decode(row["brief_json"])
        row["assessment_json"] = _decode(row["assessment_json"])
        return row

    @_thread_safe
    def add_message(self, project_id: int, role: str, content: str, session_id: int | None = None) -> dict[str, Any]:
        if role not in {"user", "assistant", "system"}:
            raise ValueError(f"Unsupported message role: {role}")
        cursor = self.connection.execute(
            """
            INSERT INTO messages(project_id, session_id, role, content, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (project_id, session_id, role, content, _now()),
        )
        self.connection.commit()
        return dict(self.connection.execute("SELECT * FROM messages WHERE id = ?", (cursor.lastrowid,)).fetchone())

    @_thread_safe
    def list_messages(self, project_id: int, limit: int | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM messages WHERE project_id = ? ORDER BY created_at ASC, id ASC"
        params: tuple[Any, ...] = (project_id,)
        if limit is not None:
            query = (
                "SELECT * FROM (SELECT * FROM messages WHERE project_id = ? "
                "ORDER BY created_at DESC, id DESC LIMIT ?) "
                "ORDER BY created_at ASC, id ASC"
            )
            params += (limit,)
        return [dict(row) for row in self.connection.execute(query, params)]
