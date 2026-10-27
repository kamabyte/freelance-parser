from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import Project

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    link        TEXT UNIQUE NOT NULL,
    fl_id       INTEGER,              -- fl.ru project id; the link changes when the title is edited
    title       TEXT,
    description TEXT,
    category    TEXT,
    budget      INTEGER,
    pub_date    TEXT,
    score       INTEGER DEFAULT 0,
    reasons     TEXT,
    notified    INTEGER DEFAULT 0,
    decision    TEXT,                 -- NULL | 'skip' | 'applied' | 'won'
    lag_seconds INTEGER,              -- pub_date → first seen; NULL for the first-run backlog
    created_at  TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def _row_to_project(row: sqlite3.Row) -> Project:
    return Project(
        id=row["id"],
        link=row["link"],
        title=row["title"] or "",
        description=row["description"] or "",
        category=row["category"] or "",
        budget=row["budget"],
        pub_date=row["pub_date"] or "",
        score=row["score"] or 0,
        reasons=json.loads(row["reasons"]) if row["reasons"] else [],
        lag_seconds=row["lag_seconds"],
    )


def _parse_created_at(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._migrate()
        # NULLs don't collide, so links without a parsable id still dedupe by link alone.
        self.conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS projects_fl_id ON projects(fl_id)")
        self.conn.commit()

    def _migrate(self) -> None:
        """Add fl_id / lag_seconds to a DB created before they existed and backfill them."""
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(projects)")}
        if "fl_id" in cols:
            return
        self.conn.execute("ALTER TABLE projects ADD COLUMN fl_id INTEGER")
        self.conn.execute("ALTER TABLE projects ADD COLUMN lag_seconds INTEGER")

        rows = self.conn.execute("SELECT * FROM projects ORDER BY id").fetchall()
        if not rows:
            return
        first_poll = _parse_created_at(rows[0]["created_at"])
        seen: set[int] = set()
        for row in rows:
            p = _row_to_project(row)
            # A repeated id is the same project re-sent after a title edit: leave it
            # without fl_id (the unique index allows that) and without a lag.
            if p.fl_id is None or p.fl_id in seen:
                continue
            seen.add(p.fl_id)
            lag = None
            published = p.published_at
            if published and published >= first_poll:  # earlier ones are the first-run backlog
                lag = max(0, int((_parse_created_at(row["created_at"]) - published).total_seconds()))
            self.conn.execute(
                "UPDATE projects SET fl_id = ?, lag_seconds = ? WHERE id = ?", (p.fl_id, lag, p.id)
            )

    def is_empty(self) -> bool:
        return self.conn.execute("SELECT 1 FROM projects LIMIT 1").fetchone() is None

    def add_if_new(self, p: Project) -> int | None:
        """Insert a project; return its new id, or None if its fl.ru id or link was already seen."""
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO projects"
            "(link, fl_id, title, description, category, budget, pub_date, score, reasons, lag_seconds) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                p.link,
                p.fl_id,
                p.title,
                p.description,
                p.category,
                p.budget,
                p.pub_date,
                p.score,
                json.dumps(p.reasons, ensure_ascii=False),
                p.lag_seconds,
            ),
        )
        self.conn.commit()
        return cur.lastrowid if cur.rowcount else None

    def get(self, pid: int) -> Project | None:
        row = self.conn.execute("SELECT * FROM projects WHERE id = ?", (pid,)).fetchone()
        return _row_to_project(row) if row else None

    def mark_notified(self, pid: int) -> None:
        self.conn.execute("UPDATE projects SET notified = 1 WHERE id = ?", (pid,))
        self.conn.commit()

    def set_decision(self, pid: int, decision: str) -> None:
        self.conn.execute("UPDATE projects SET decision = ? WHERE id = ?", (decision, pid))
        self.conn.commit()

    def counts(self) -> dict[str, int]:
        q = (
            "SELECT "
            "COUNT(*) AS total, "
            "SUM(notified) AS notified, "
            "SUM(decision = 'applied') AS applied, "
            "SUM(decision = 'won') AS won "
            "FROM projects"
        )
        row = self.conn.execute(q).fetchone()
        return {k: (row[k] or 0) for k in ("total", "notified", "applied", "won")}

    def recent_lags(self, days: int = 7) -> list[int]:
        """Publish-to-sighting lags of projects first seen in the last `days`, ascending."""
        rows = self.conn.execute(
            "SELECT lag_seconds FROM projects "
            "WHERE lag_seconds IS NOT NULL AND created_at >= datetime('now', ?) "
            "ORDER BY lag_seconds",
            (f"-{days} days",),
        ).fetchall()
        return [r["lag_seconds"] for r in rows]

    def get_setting(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_setting(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self.conn.commit()
