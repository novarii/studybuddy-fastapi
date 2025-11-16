"""SQLite helpers for persistent metadata (courses, etc.)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import List, Optional


class CourseDatabase:
    """Lightweight wrapper around SQLite for storing courses."""

    def __init__(self, db_path: str = "data/app.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS courses (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL
                )
                """
            )

    # Placeholder helpers for upcoming endpoints
    def create_course(self, course_id: str, name: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO courses (id, name) VALUES (?, ?)",
                (course_id, name),
            )

    def get_course(self, course_id: str) -> Optional[sqlite3.Row]:
        with self._connect() as conn:
            cur = conn.execute("SELECT id, name FROM courses WHERE id = ?", (course_id,))
            return cur.fetchone()

    def list_courses(self) -> List[sqlite3.Row]:
        with self._connect() as conn:
            cur = conn.execute("SELECT id, name FROM courses ORDER BY name ASC")
            return cur.fetchall()
