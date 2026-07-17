import sqlite3
from contextlib import closing

from app.core.config import DB_PATH


def get_conn():
    return closing(sqlite3.connect(DB_PATH))


def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                title TEXT,
                created_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                role TEXT,
                content TEXT,
                created_at TEXT,
                FOREIGN KEY(session_id) REFERENCES sessions(id)
            )
        """)
        conn.commit()