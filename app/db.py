import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from .config import DB_PATH

def now() -> str:
    return datetime.now(timezone.utc).isoformat()

@contextmanager
def connect():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    try:
        yield db
        db.commit()
    finally:
        db.close()

def init_db():
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS tasks (
          id INTEGER PRIMARY KEY, correlation_id TEXT NOT NULL, repo TEXT NOT NULL,
          issue_number INTEGER NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL,
          labels TEXT NOT NULL DEFAULT '[]', state TEXT NOT NULL, idempotency_key TEXT UNIQUE NOT NULL,
          session_id TEXT, pr_url TEXT, attempts INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL, blocked_escalated INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL, correlation_id TEXT NOT NULL,
          event_type TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS evals (
          id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL, checks_passed INTEGER NOT NULL,
          judge_score REAL, score REAL NOT NULL, feedback TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reviews (
          id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL, action TEXT NOT NULL,
          body TEXT, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS events_task_idx ON events(task_id);
        """)

def row_task(row):
    if not row: return None
    result = dict(row)
    result["labels"] = json.loads(result["labels"])
    return result
