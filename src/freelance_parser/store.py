from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .models import Project

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    link        TEXT UNIQUE NOT NULL,
    title       TEXT,
    description TEXT,
    category    TEXT,
    budget      INTEGER,
    pub_date    TEXT,
    score       INTEGER DEFAULT 0,
    reasons     TEXT,
    notified    INTEGER DEFAULT 0,
    decision    TEXT,                 -- NULL | 'skip' | 'applied' | 'won'
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
    )


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def add_if_new(self, p: Project) -> int | None:
        """Insert a project; return its new id, or None if the link was already seen."""
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO projects"
            "(link, title, description, category, budget, pub_date, score, reasons) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                p.link,
                p.title,
                p.description,
                p.category,
                p.budget,
                p.pub_date,
                p.score,
                json.dumps(p.reasons, ensure_ascii=False),
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
