"""Checkpoint database. Every stage result is recorded so a crash or a pause
never costs more than the stage that was running.

Files on disk are the source of truth for content (dossier, script, renders).
The database tracks what has run, what is waiting for a human, and spend.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS topics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    angle TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT '',
    score REAL NOT NULL DEFAULT 0,
    details TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'candidate',   -- candidate | approved | rejected | used
    project_id INTEGER,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    angle TEXT NOT NULL DEFAULT '',
    pack TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',      -- active | waiting | failed | ready | published
    published_url TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stage_runs (
    project_id INTEGER NOT NULL,
    stage TEXT NOT NULL,
    status TEXT NOT NULL,                       -- done | failed | waiting | approved
    attempts INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    started_at TEXT,
    finished_at TEXT,
    PRIMARY KEY (project_id, stage)
);
CREATE TABLE IF NOT EXISTS usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER,
    service TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    units REAL NOT NULL DEFAULT 0,
    unit TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class State:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        with self.conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def conn(self) -> Iterator[sqlite3.Connection]:
        c = sqlite3.connect(self.db_path, timeout=30)
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        finally:
            c.close()

    # ---- topics -------------------------------------------------------
    def add_topic(self, title: str, angle: str, category: str, score: float, details: dict) -> int:
        with self.conn() as c:
            cur = c.execute(
                "INSERT INTO topics (title, angle, category, score, details, created_at) VALUES (?,?,?,?,?,?)",
                (title, angle, category, score, json.dumps(details), now()),
            )
            return int(cur.lastrowid)

    def topics(self, status: str | None = None) -> list[sqlite3.Row]:
        with self.conn() as c:
            if status:
                return list(c.execute("SELECT * FROM topics WHERE status=? ORDER BY score DESC", (status,)))
            return list(c.execute("SELECT * FROM topics ORDER BY created_at DESC, score DESC"))

    def topic(self, topic_id: int) -> sqlite3.Row | None:
        with self.conn() as c:
            return c.execute("SELECT * FROM topics WHERE id=?", (topic_id,)).fetchone()

    def set_topic_status(self, topic_id: int, status: str, project_id: int | None = None) -> None:
        with self.conn() as c:
            c.execute("UPDATE topics SET status=?, project_id=COALESCE(?, project_id) WHERE id=?", (status, project_id, topic_id))

    def all_titles(self) -> list[str]:
        with self.conn() as c:
            rows = list(c.execute("SELECT title FROM topics UNION SELECT title FROM projects"))
        return [r[0] for r in rows]

    # ---- projects -----------------------------------------------------
    def create_project(self, slug: str, title: str, angle: str, pack: str) -> int:
        with self.conn() as c:
            cur = c.execute(
                "INSERT INTO projects (slug, title, angle, pack, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                (slug, title, angle, pack, now(), now()),
            )
            return int(cur.lastrowid)

    def project(self, project_id: int) -> sqlite3.Row:
        with self.conn() as c:
            row = c.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if row is None:
            raise KeyError(f"No project with id {project_id}")
        return row

    def projects(self) -> list[sqlite3.Row]:
        with self.conn() as c:
            return list(c.execute("SELECT * FROM projects ORDER BY id DESC"))

    def set_project_status(self, project_id: int, status: str, published_url: str | None = None) -> None:
        with self.conn() as c:
            c.execute(
                "UPDATE projects SET status=?, published_url=COALESCE(?, published_url), updated_at=? WHERE id=?",
                (status, published_url, now(), project_id),
            )

    # ---- stage runs ---------------------------------------------------
    def stage(self, project_id: int, stage: str) -> sqlite3.Row | None:
        with self.conn() as c:
            return c.execute(
                "SELECT * FROM stage_runs WHERE project_id=? AND stage=?", (project_id, stage)
            ).fetchone()

    def stages(self, project_id: int) -> dict[str, sqlite3.Row]:
        with self.conn() as c:
            rows = c.execute("SELECT * FROM stage_runs WHERE project_id=?", (project_id,))
            return {r["stage"]: r for r in rows}

    def mark_stage(self, project_id: int, stage: str, status: str, error: str | None = None) -> None:
        existing = self.stage(project_id, stage)
        attempts = (existing["attempts"] if existing else 0) + (1 if status in {"done", "failed"} else 0)
        with self.conn() as c:
            c.execute(
                """INSERT INTO stage_runs (project_id, stage, status, attempts, error, started_at, finished_at)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(project_id, stage) DO UPDATE SET
                     status=excluded.status, attempts=excluded.attempts, error=excluded.error,
                     finished_at=excluded.finished_at""",
                (project_id, stage, status, attempts, error, now(), now()),
            )

    def reset_stage(self, project_id: int, stage: str) -> None:
        with self.conn() as c:
            c.execute("DELETE FROM stage_runs WHERE project_id=? AND stage=?", (project_id, stage))

    # ---- usage --------------------------------------------------------
    def log_usage(self, project_id: int | None, service: str, units: float, unit: str, detail: str = "") -> None:
        with self.conn() as c:
            c.execute(
                "INSERT INTO usage (project_id, service, detail, units, unit, created_at) VALUES (?,?,?,?,?,?)",
                (project_id, service, detail, units, unit, now()),
            )

    def usage_summary(self, project_id: int | None = None) -> list[dict[str, Any]]:
        sql = "SELECT service, unit, SUM(units) AS total FROM usage"
        args: tuple = ()
        if project_id is not None:
            sql += " WHERE project_id=?"
            args = (project_id,)
        sql += " GROUP BY service, unit ORDER BY service"
        with self.conn() as c:
            return [dict(r) for r in c.execute(sql, args)]
