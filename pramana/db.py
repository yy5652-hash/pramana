"""SQLite storage. One database per course: knowledge base, question bank, learner state."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Iterable

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL, file TEXT NOT NULL,
    licence TEXT, attribution TEXT, meta TEXT NOT NULL DEFAULT '{}'
);
-- A content unit is the smallest citable piece of course material. `locator` says where it
-- came from: {"page": 214, "rects": [...]}, {"slide": 12} or {"t_start": 63.2, "t_end": 95.0}.
CREATE TABLE IF NOT EXISTS units (
    id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id),
    kind TEXT NOT NULL,            -- text | equation | figure | slide | transcript | frame
    modality TEXT NOT NULL,        -- text | vision | speech  (how the content was obtained)
    locator TEXT NOT NULL, section TEXT, text TEXT NOT NULL, asset TEXT, ord INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS units_source ON units(source_id, ord);
CREATE TABLE IF NOT EXISTS embeddings (unit_id TEXT PRIMARY KEY REFERENCES units(id), vec BLOB NOT NULL);

CREATE TABLE IF NOT EXISTS topics (id TEXT PRIMARY KEY, title TEXT NOT NULL, summary TEXT, ord INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS concepts (
    id TEXT PRIMARY KEY, topic_id TEXT NOT NULL REFERENCES topics(id),
    name TEXT NOT NULL, description TEXT, ord INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS prereqs (
    concept_id TEXT NOT NULL REFERENCES concepts(id), requires_id TEXT NOT NULL REFERENCES concepts(id),
    PRIMARY KEY (concept_id, requires_id)
);
CREATE TABLE IF NOT EXISTS unit_concepts (
    unit_id TEXT NOT NULL REFERENCES units(id), concept_id TEXT NOT NULL REFERENCES concepts(id),
    weight REAL NOT NULL DEFAULT 1.0, PRIMARY KEY (unit_id, concept_id)
);

CREATE TABLE IF NOT EXISTS questions (
    id TEXT PRIMARY KEY, concept_id TEXT NOT NULL REFERENCES concepts(id),
    type TEXT NOT NULL,            -- mcq | short | numeric
    difficulty INTEGER NOT NULL,   -- 1 (recall) .. 5 (multi-step transfer)
    stem TEXT NOT NULL, options TEXT, answer TEXT NOT NULL, explanation TEXT,
    unit_ids TEXT NOT NULL,        -- JSON list of source units the question is grounded in
    verification TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL DEFAULT 'verified',
    vec BLOB, created REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS questions_concept ON questions(concept_id, status);

CREATE TABLE IF NOT EXISTS students (id TEXT PRIMARY KEY, name TEXT NOT NULL, created REAL NOT NULL, profile TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS mastery (
    student_id TEXT NOT NULL REFERENCES students(id), concept_id TEXT NOT NULL REFERENCES concepts(id),
    p REAL NOT NULL, n_obs INTEGER NOT NULL DEFAULT 0, updated REAL NOT NULL,
    PRIMARY KEY (student_id, concept_id)
);
CREATE TABLE IF NOT EXISTS evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT, student_id TEXT NOT NULL, concept_id TEXT NOT NULL,
    ts REAL NOT NULL, source TEXT NOT NULL,   -- quiz | diagnostic | chat
    correct REAL NOT NULL, p_before REAL NOT NULL, p_after REAL NOT NULL, detail TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS evidence_student ON evidence(student_id, ts);
CREATE TABLE IF NOT EXISTS assessments (
    id TEXT PRIMARY KEY, student_id TEXT NOT NULL, kind TEXT NOT NULL, scope TEXT NOT NULL,
    question_ids TEXT NOT NULL, created REAL NOT NULL, finished REAL, report TEXT
);
CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, assessment_id TEXT, student_id TEXT NOT NULL,
    question_id TEXT NOT NULL, ts REAL NOT NULL, response TEXT NOT NULL, score REAL NOT NULL, feedback TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS attempts_student ON attempts(student_id, question_id);
-- A lesson is a short film on one concept, cut for one student. `board` is its storyboard:
-- the scenes, the source each one shows, and where the finished video is.
CREATE TABLE IF NOT EXISTS lessons (
    id TEXT PRIMARY KEY, student_id TEXT NOT NULL, concept_id TEXT NOT NULL, created REAL NOT NULL, board TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT, student_id TEXT NOT NULL, ts REAL NOT NULL,
    role TEXT NOT NULL, content TEXT NOT NULL, meta TEXT NOT NULL DEFAULT '{}'
);
"""

JSON_COLUMNS = {
    "meta", "locator", "options", "answer", "unit_ids", "verification", "profile",
    "detail", "scope", "question_ids", "report", "response", "feedback", "board",
}


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def now() -> float:
    return time.time()


class Database:
    """Thin wrapper: dict rows, JSON columns decoded, one lock for writes."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.lock = threading.RLock()
        with self.lock:
            self.conn.executescript(SCHEMA)
            self.conn.commit()

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict[str, Any]:
        out = dict(row)
        for key, value in out.items():
            if key in JSON_COLUMNS and isinstance(value, str):
                out[key] = json.loads(value)
        return out

    @staticmethod
    def _encode(values: dict[str, Any]) -> dict[str, Any]:
        return {
            k: json.dumps(v, ensure_ascii=False) if k in JSON_COLUMNS and not isinstance(v, (str, type(None))) else v
            for k, v in values.items()
        }

    def all(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        with self.lock:
            return [self._decode(r) for r in self.conn.execute(sql, tuple(params)).fetchall()]

    def one(self, sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
        rows = self.all(sql, params)
        return rows[0] if rows else None

    def run(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self.lock:
            cursor = self.conn.execute(sql, tuple(params))
            self.conn.commit()
            return cursor

    def insert(self, table: str, values: dict[str, Any], replace: bool = False) -> int:
        values = self._encode(values)
        columns = ", ".join(values)
        marks = ", ".join("?" for _ in values)
        verb = "INSERT OR REPLACE" if replace else "INSERT"
        return self.run(f"{verb} INTO {table} ({columns}) VALUES ({marks})", values.values()).lastrowid

    def insert_many(self, table: str, rows: list[dict[str, Any]], replace: bool = False) -> None:
        if not rows:
            return
        encoded = [self._encode(r) for r in rows]
        columns = list(encoded[0])
        verb = "INSERT OR REPLACE" if replace else "INSERT"
        sql = f"{verb} INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})"
        with self.lock:
            self.conn.executemany(sql, [tuple(r[c] for c in columns) for r in encoded])
            self.conn.commit()


_open: dict[str, Database] = {}
_open_lock = threading.Lock()


def open_course(course_id: str) -> Database:
    with _open_lock:
        if course_id not in _open:
            _open[course_id] = Database(settings.course_db(course_id))
        return _open[course_id]
