"""SQLite database for bookmark storage and retrieval."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Generator

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS bookmarks (
    id               TEXT PRIMARY KEY,
    text             TEXT NOT NULL,
    author_id        TEXT,
    author_name      TEXT,
    author_username  TEXT,
    created_at       TIMESTAMP,
    url              TEXT,
    category         TEXT DEFAULT 'Other',
    raw_json         TEXT,
    fetched_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    classified_at    TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_category   ON bookmarks(category);
CREATE INDEX IF NOT EXISTS idx_created_at ON bookmarks(created_at);
"""


class BookmarkDB:
    """Thin wrapper around SQLite for bookmark CRUD."""

    def __init__(self, db_path: str = "bookmarks.db") -> None:
        self._path = db_path
        self._conn: sqlite3.Connection | None = None

    # ── connection ───────────────────────────────────────────────────────

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self._path)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    @contextmanager
    def _tx(self) -> Generator[sqlite3.Cursor, None, None]:
        conn = self._get_conn()
        cur = conn.cursor()
        try:
            yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    # ── schema ───────────────────────────────────────────────────────────

    def init_db(self) -> None:
        conn = self._get_conn()
        conn.executescript(_SCHEMA)
        conn.commit()

    # ── write ────────────────────────────────────────────────────────────

    def upsert_bookmarks(self, bookmarks: list[dict[str, Any]]) -> int:
        """Insert or update bookmarks. Returns number of rows affected."""
        sql = """\
            INSERT INTO bookmarks
                (id, text, author_id, author_name, author_username,
                 created_at, url, category, raw_json, fetched_at)
            VALUES
                (:id, :text, :author_id, :author_name, :author_username,
                 :created_at, :url, :category, :raw_json, :fetched_at)
            ON CONFLICT(id) DO UPDATE SET
                text            = excluded.text,
                author_id       = excluded.author_id,
                author_name     = excluded.author_name,
                author_username = excluded.author_username,
                created_at      = excluded.created_at,
                url             = excluded.url,
                raw_json        = excluded.raw_json
        """
        now = datetime.utcnow().isoformat()
        rows = 0
        with self._tx() as cur:
            for bm in bookmarks:
                bm.setdefault("fetched_at", now)
                bm.setdefault("category", "Other")
                cur.execute(sql, bm)
                rows += cur.rowcount
        return rows

    def update_categories(self, mapping: dict[str, str]) -> int:
        """Update category and classified_at for the given tweet IDs."""
        sql = "UPDATE bookmarks SET category = ?, classified_at = ? WHERE id = ?"
        now = datetime.utcnow().isoformat()
        rows = 0
        with self._tx() as cur:
            for tid, cat in mapping.items():
                cur.execute(sql, (cat, now, tid))
                rows += cur.rowcount
        return rows

    # ── read ─────────────────────────────────────────────────────────────

    def get_existing_ids(self) -> set[str]:
        conn = self._get_conn()
        cur = conn.execute("SELECT id FROM bookmarks")
        return {row["id"] for row in cur.fetchall()}

    def get_unclassified(self) -> list[dict[str, Any]]:
        """Return bookmarks that haven't been classified yet."""
        conn = self._get_conn()
        cur = conn.execute(
            "SELECT id, text FROM bookmarks WHERE classified_at IS NULL"
        )
        return [dict(row) for row in cur.fetchall()]

    def get_all(self, *, category: str | None = None) -> list[dict[str, Any]]:
        conn = self._get_conn()
        if category:
            cur = conn.execute(
                "SELECT * FROM bookmarks WHERE category = ? ORDER BY created_at DESC",
                (category,),
            )
        else:
            cur = conn.execute(
                "SELECT * FROM bookmarks ORDER BY created_at DESC"
            )
        return [dict(row) for row in cur.fetchall()]

    def get_stats(self) -> dict[str, int]:
        """Return {category: count} plus total."""
        conn = self._get_conn()
        cur = conn.execute(
            "SELECT category, COUNT(*) as cnt FROM bookmarks GROUP BY category ORDER BY cnt DESC"
        )
        stats = {row["category"]: row["cnt"] for row in cur.fetchall()}
        stats["_total"] = sum(stats.values())
        return stats

    # ── export ───────────────────────────────────────────────────────────

    def export_csv(self, path: str = "bookmarks_export.csv") -> str:
        """Export all bookmarks to CSV. Returns the output path."""
        import csv

        rows = self.get_all()
        if not rows:
            return ""
        fieldnames = [
            "id", "text", "author_username", "author_name",
            "category", "created_at", "url",
        ]
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        return path

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
