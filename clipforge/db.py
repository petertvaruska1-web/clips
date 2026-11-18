"""SQLite state: moments (candidates through the pipeline) and uploads."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS moments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  channel TEXT NOT NULL,
  t_event REAL, t_on REAL, t_peak REAL,
  clip_start REAL, clip_end REAL,
  score REAL, category TEXT,
  state TEXT NOT NULL DEFAULT 'detected',
  features TEXT NOT NULL DEFAULT '{}',
  title TEXT, hook TEXT, hashtags TEXT,
  raw_path TEXT, out_path TEXT, note TEXT,
  created REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_moments_state ON moments(state);
CREATE TABLE IF NOT EXISTS uploads (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  moment_id INTEGER, video_id TEXT, title TEXT, channel TEXT,
  published_at REAL, exceptional INTEGER DEFAULT 0,
  views INTEGER, likes INTEGER, status TEXT
);
"""

_JSON_COLS = {"features"}


class Database:
    def __init__(self, path: Path | str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def _row(self, r: sqlite3.Row | None) -> dict | None:
        if r is None:
            return None
        d = dict(r)
        for c in _JSON_COLS:
            if c in d and isinstance(d[c], str):
                d[c] = json.loads(d[c])
        return d

    def add_moment(self, *, channel: str, t_event: float, t_on: float, t_peak: float,
                   score: float, category: str, features: dict, **extra: Any) -> int:
        cols = dict(channel=channel, t_event=t_event, t_on=t_on, t_peak=t_peak, score=score,
                    category=category, features=json.dumps(features), created=time.time(), **extra)
        with self._lock:
            cur = self.conn.execute(
                f"INSERT INTO moments ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                list(cols.values()))
            self.conn.commit()
            return int(cur.lastrowid)

    def update_moment(self, mid: int, **vals: Any) -> None:
        if "features" in vals:
            vals["features"] = json.dumps(vals["features"])
        with self._lock:
            self.conn.execute(f"UPDATE moments SET {','.join(k + '=?' for k in vals)} WHERE id=?",
                              [*vals.values(), mid])
            self.conn.commit()

    def get_moment(self, mid: int) -> dict | None:
        with self._lock:
            return self._row(self.conn.execute("SELECT * FROM moments WHERE id=?", (mid,)).fetchone())

    def moments_in_state(self, state: str) -> list[dict]:
        with self._lock:
            rows = self.conn.execute("SELECT * FROM moments WHERE state=? ORDER BY id", (state,)).fetchall()
        return [self._row(r) for r in rows]

    def add_upload(self, moment_id: int, *, video_id: str, title: str, channel: str,
                   published_at: float, exceptional: bool) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO uploads (moment_id, video_id, title, channel, published_at, exceptional, status)"
                " VALUES (?,?,?,?,?,?,?)",
                (moment_id, video_id, title, channel, published_at, int(exceptional), "uploaded"))
            self.conn.commit()

    def uploads_since(self, ts: float) -> list[dict]:
        with self._lock:
            rows = self.conn.execute("SELECT * FROM uploads WHERE published_at>=? ORDER BY published_at",
                                     (ts,)).fetchall()
        return [dict(r) for r in rows]
