"""
database.py — Pure Python sqlite3 (no SQLAlchemy, no extra deps)
DB file : chat.db  (created automatically next to this file)

Tables:
  threads  — id, title, created_at
  messages — id, thread_id, role, content, created_at
"""

import sqlite3
import os
from contextlib import contextmanager
from datetime import datetime

# ── DB path — same folder as this file, works anywhere ──────────────────────
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chat.db")


# ── Connection helper ─────────────────────────────────────────────────────────

@contextmanager
def get_conn():
    """Yield a sqlite3 connection with row_factory set, then close it."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row          # rows behave like dicts
    conn.execute("PRAGMA journal_mode=WAL") # safe for concurrent reads
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── Schema ────────────────────────────────────────────────────────────────────

def create_tables():
    """Create tables if they don't already exist (idempotent)."""
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS threads (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                title      TEXT    NOT NULL DEFAULT 'New Thread',
                created_at TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS messages (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id  INTEGER NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
                role       TEXT    NOT NULL,   -- user | assistant | system
                content    TEXT    NOT NULL,
                created_at TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_messages_thread
                ON messages(thread_id, created_at);
        """)


# ── Thread CRUD ───────────────────────────────────────────────────────────────

def create_thread(title: str = "New Thread") -> dict:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO threads (title) VALUES (?)", (title,)
        )
        row = conn.execute(
            "SELECT * FROM threads WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
        return dict(row)


def get_all_threads() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM threads ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def get_thread(thread_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM threads WHERE id = ?", (thread_id,)
        ).fetchone()
        return dict(row) if row else None


def rename_thread(thread_id: int, title: str) -> dict | None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE threads SET title = ? WHERE id = ?", (title, thread_id)
        )
        row = conn.execute(
            "SELECT * FROM threads WHERE id = ?", (thread_id,)
        ).fetchone()
        return dict(row) if row else None


def delete_thread(thread_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM threads WHERE id = ?", (thread_id,)
        )
        return cur.rowcount > 0


# ── Message CRUD ──────────────────────────────────────────────────────────────

def add_message(thread_id: int, role: str, content: str) -> dict:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO messages (thread_id, role, content) VALUES (?, ?, ?)",
            (thread_id, role, content),
        )
        row = conn.execute(
            "SELECT * FROM messages WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
        return dict(row)


def get_thread_messages(thread_id: int, limit: int = 50) -> list[dict]:
    """Return the last `limit` messages for a thread, oldest first."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM (
                SELECT * FROM messages
                WHERE thread_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            ) ORDER BY created_at ASC
            """,
            (thread_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


# ── Universal Cross-Thread Memory ─────────────────────────────────────────────

def get_universal_context(
    exclude_thread_id: int | None = None,
    per_thread_limit: int = 6,
    max_threads: int = 5,
) -> str:
    """
    Build a universal memory string from recent messages across other threads.
    Injected as a system-level context so the AI remembers past conversations.
    """
    with get_conn() as conn:
        # Get the most recent threads, excluding the current one
        placeholder = "AND id != ?" if exclude_thread_id is not None else ""
        params = [max_threads + 1]
        query = f"""
            SELECT * FROM threads
            WHERE 1=1 {placeholder}
            ORDER BY created_at DESC
            LIMIT ?
        """
        if exclude_thread_id is not None:
            rows = conn.execute(query, (exclude_thread_id, max_threads + 1)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM threads ORDER BY created_at DESC LIMIT ?",
                (max_threads + 1,)
            ).fetchall()

        threads = [dict(r) for r in rows][:max_threads]

        if not threads:
            return ""

        snippets: list[str] = []
        for thread in threads:
            msgs = get_thread_messages(thread["id"], limit=per_thread_limit)
            if not msgs:
                continue
            lines = [
                f'  [{m["role"].upper()}]: {m["content"][:300]}'
                for m in msgs
            ]
            snippets.append(
                f'--- Thread "{thread["title"]}" ---\n' + "\n".join(lines)
            )

    if not snippets:
        return ""

    return (
        "You have memory of the user's past conversations below. "
        "Use this context naturally to give consistent, personalized responses.\n\n"
        + "\n\n".join(snippets)
    )
