"""
storage.py
Thin SQLite wrapper. No ORM on purpose - the schema is tiny and this keeps
the whole system runnable with zero external dependencies beyond Flask.
"""
import sqlite3
import json
import os
from datetime import datetime, timezone
from contextlib import contextmanager

DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "..", "data.db"))


def _row_to_dict(cursor, row):
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = None
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS activities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                activity_type TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                duration_minutes REAL,
                metadata TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS insights (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                generated_at TEXT NOT NULL,
                stats_json TEXT NOT NULL,
                narrative TEXT NOT NULL,
                llm_used INTEGER NOT NULL,
                llm_model TEXT
            )
            """
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_activities_user ON activities(user_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_insights_user ON insights(user_id)")


def insert_activity(user_id, activity_type, timestamp, duration_minutes=None, metadata=None):
    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            """INSERT INTO activities (user_id, activity_type, timestamp, duration_minutes, metadata, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                user_id,
                activity_type,
                timestamp,
                duration_minutes,
                json.dumps(metadata or {}),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        return c.lastrowid


def get_activities(user_id):
    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT id, user_id, activity_type, timestamp, duration_minutes, metadata, created_at "
            "FROM activities WHERE user_id = ? ORDER BY timestamp ASC",
            (user_id,),
        )
        rows = c.fetchall()
        out = []
        for r in rows:
            out.append(
                {
                    "id": r[0],
                    "user_id": r[1],
                    "activity_type": r[2],
                    "timestamp": r[3],
                    "duration_minutes": r[4],
                    "metadata": json.loads(r[5]) if r[5] else {},
                    "created_at": r[6],
                }
            )
        return out


def insert_insight(user_id, stats, narrative, llm_used, llm_model=None):
    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            """INSERT INTO insights (user_id, generated_at, stats_json, narrative, llm_used, llm_model)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                user_id,
                datetime.now(timezone.utc).isoformat(),
                json.dumps(stats),
                narrative,
                1 if llm_used else 0,
                llm_model,
            ),
        )
        return c.lastrowid


def get_insights(user_id):
    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT id, user_id, generated_at, stats_json, narrative, llm_used, llm_model "
            "FROM insights WHERE user_id = ? ORDER BY generated_at DESC",
            (user_id,),
        )
        rows = c.fetchall()
        out = []
        for r in rows:
            out.append(
                {
                    "id": r[0],
                    "user_id": r[1],
                    "generated_at": r[2],
                    "stats": json.loads(r[3]),
                    "narrative": r[4],
                    "llm_used": bool(r[5]),
                    "llm_model": r[6],
                }
            )
        return out
