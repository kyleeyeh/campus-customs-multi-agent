"""Database access for the shop.

Every read and write in this project goes through here, so there is exactly one
place that knows which file is the working copy and one place that defines what
"today" means for the shop.

Two rules enforced here rather than trusted to a prompt:

1. `data/campus_customs.db` is never opened for writing. Only the working copy
   `data/campus_customs_new.db` is mutable.
2. "Today" is `desk.date_today`, never the system clock. Overdue tests and
   lead-time arithmetic that use the real date would silently give wrong
   answers, since the shop's calendar is set in 2026.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date, timedelta
from typing import Any, Iterator

from app.config import WORKING_DB


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}


@contextmanager
def connect(write: bool = False) -> Iterator[sqlite3.Connection]:
    """Open the working copy. Read-only unless `write=True`.

    Foreign keys are enforced so a bad ticket_id fails loudly instead of
    writing an orphan row.
    """
    if write:
        conn = sqlite3.connect(WORKING_DB)
    else:
        conn = sqlite3.connect(f"file:{WORKING_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        yield conn
        if write:
            conn.commit()
    except Exception:
        if write:
            conn.rollback()
        raise
    finally:
        conn.close()


def query(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    """Run a SELECT and return plain dicts (JSON-safe for MCP tool output)."""
    with connect() as conn:
        return [_row_to_dict(r) for r in conn.execute(sql, params)]


def query_one(sql: str, params: tuple = ()) -> dict[str, Any] | None:
    rows = query(sql, params)
    return rows[0] if rows else None


# --- The shop's calendar ---------------------------------------------------

def shop_today() -> str:
    """`desk.date_today` — the only date the agents may treat as 'now'."""
    row = query_one("SELECT date_today FROM desk LIMIT 1")
    if not row:
        raise RuntimeError("desk.date_today is missing; cannot establish shop date.")
    return row["date_today"]


def days_until(target: str) -> int:
    """Days from the shop date to `target` (ISO). Negative means overdue."""
    today = date.fromisoformat(shop_today())
    return (date.fromisoformat(target) - today).days


def is_overdue(due_date: str) -> bool:
    return days_until(due_date) < 0


def add_days(start: str, days: int) -> str:
    """ISO date `days` after `start`. Used for vendor lead times."""
    return (date.fromisoformat(start) + timedelta(days=days)).isoformat()
