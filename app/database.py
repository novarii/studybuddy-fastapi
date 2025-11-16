"""SQLite helpers for persistent metadata (courses, etc.)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional


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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS course_lectures (
                    course_id TEXT NOT NULL,
                    lecture_id TEXT NOT NULL,
                    PRIMARY KEY (course_id, lecture_id),
                    FOREIGN KEY(course_id) REFERENCES courses(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS course_documents (
                    course_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    PRIMARY KEY (course_id, document_id),
                    FOREIGN KEY(course_id) REFERENCES courses(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS course_units (
                    id TEXT PRIMARY KEY,
                    course_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT,
                    position INTEGER DEFAULT 0,
                    FOREIGN KEY(course_id) REFERENCES courses(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS course_topics (
                    id TEXT PRIMARY KEY,
                    unit_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT,
                    position INTEGER DEFAULT 0,
                    FOREIGN KEY(unit_id) REFERENCES course_units(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    id TEXT PRIMARY KEY,
                    course_id TEXT NOT NULL,
                    user_id TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(course_id) REFERENCES courses(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    message TEXT NOT NULL,
                    source TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
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

    # Relational helpers --------------------------------------------------

    def link_lecture(self, course_id: str, lecture_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO course_lectures (course_id, lecture_id) VALUES (?, ?)",
                (course_id, lecture_id),
            )

    def link_document(self, course_id: str, document_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO course_documents (course_id, document_id) VALUES (?, ?)",
                (course_id, document_id),
            )

    def list_lectures_for_course(self, course_id: str) -> List[str]:
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT lecture_id FROM course_lectures WHERE course_id = ? ORDER BY lecture_id",
                (course_id,),
            )
            return [row["lecture_id"] for row in cur.fetchall()]

    def list_documents_for_course(self, course_id: str) -> List[str]:
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT document_id FROM course_documents WHERE course_id = ? ORDER BY document_id",
                (course_id,),
            )
            return [row["document_id"] for row in cur.fetchall()]

    # Unit & topic helpers ------------------------------------------------

    def create_unit(
        self,
        *,
        unit_id: str,
        course_id: str,
        title: str,
        description: Optional[str],
        position: Optional[int],
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO course_units (id, course_id, title, description, position)
                VALUES (?, ?, ?, ?, COALESCE(?, 0))
                """,
                (unit_id, course_id, title, description, position),
            )

    def list_units(self, course_id: str) -> List[sqlite3.Row]:
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT id, course_id, title, description, position
                FROM course_units
                WHERE course_id = ?
                ORDER BY position, title
                """,
                (course_id,),
            )
            return cur.fetchall()

    def get_unit(self, unit_id: str) -> Optional[sqlite3.Row]:
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT id, course_id, title, description, position FROM course_units WHERE id = ?",
                (unit_id,),
            )
            return cur.fetchone()

    def create_topic(
        self,
        *,
        topic_id: str,
        unit_id: str,
        title: str,
        description: Optional[str],
        position: Optional[int],
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO course_topics (id, unit_id, title, description, position)
                VALUES (?, ?, ?, ?, COALESCE(?, 0))
                """,
                (topic_id, unit_id, title, description, position),
            )

    def list_topics(self, unit_id: str) -> List[sqlite3.Row]:
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT id, unit_id, title, description, position
                FROM course_topics
                WHERE unit_id = ?
                ORDER BY position, title
                """,
                (unit_id,),
            )
            return cur.fetchall()

    # Chat history helpers -----------------------------------------------

    def get_or_create_chat_session(self, course_id: str, user_id: Optional[str]) -> str:
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT id FROM chat_sessions
                WHERE course_id = ? AND ((? IS NULL AND user_id IS NULL) OR user_id = ?)
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (course_id, user_id, user_id),
            )
            row = cur.fetchone()
            if row:
                return row["id"]
            from datetime import datetime

            session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
            conn.execute(
                "INSERT INTO chat_sessions (id, course_id, user_id, created_at) VALUES (?, ?, ?, ?)",
                (session_id, course_id, user_id, datetime.now().isoformat()),
            )
            return session_id

    def add_chat_message(
        self,
        *,
        session_id: str,
        role: str,
        message: str,
        source: Optional[str],
    ) -> None:
        from datetime import datetime

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO chat_messages (session_id, role, message, source, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, role, message, source, datetime.utcnow().isoformat()),
            )

    def get_chat_history(self, course_id: str, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            params: List = [course_id]
            query = """
                SELECT s.id as session_id, s.course_id, s.user_id, s.created_at as session_created_at,
                       m.id as message_id, m.role, m.message, m.source, m.created_at
                FROM chat_sessions s
                LEFT JOIN chat_messages m ON m.session_id = s.id
                WHERE s.course_id = ?
            """
            if user_id is None:
                query += " AND (s.user_id IS NULL OR s.user_id IS NOT NULL)"
            else:
                query += " AND s.user_id = ?"
                params.append(user_id)
            query += " ORDER BY s.created_at ASC, m.created_at ASC, m.id ASC"
            cur = conn.execute(query, params)
            sessions: Dict[str, Dict[str, Any]] = {}
            for row in cur.fetchall():
                session_id = row["session_id"]
                if session_id not in sessions:
                    sessions[session_id] = {
                        "session_id": session_id,
                        "course_id": row["course_id"],
                        "user_id": row["user_id"],
                        "created_at": row["session_created_at"],
                        "messages": [],
                    }
                if row["message_id"] is not None:
                    sessions[session_id]["messages"].append(
                        {
                            "message_id": row["message_id"],
                            "role": row["role"],
                            "message": row["message"],
                            "source": row["source"],
                            "created_at": row["created_at"],
                        }
                    )
            return list(sessions.values())
