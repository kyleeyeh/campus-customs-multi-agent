"""Create/refresh the working database from the pristine original.

    python scripts/init_working_db.py           # reset + apply schema
    python scripts/init_working_db.py --migrate # apply schema only, keep data

The original data/campus_customs.db is never modified. Everything the agents
do happens in data/campus_customs_new.db.

The tables added here are the ones the assignment needs but the shipped
schema does not provide: a human-approval queue, purchase orders, customer
message drafts, and a transcript of agent activity for the dashboard.
"""

import argparse
import shutil
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import ORIGINAL_DB, WORKING_DB

SCHEMA = """
-- Human approval queue. An agent parks a request here and ends its turn;
-- the dashboard decides; a resume step continues the work.
CREATE TABLE IF NOT EXISTS approvals (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id     INTEGER,
    kind          TEXT NOT NULL,   -- payment | purchase_order | discount
    summary       TEXT NOT NULL,   -- one line a human can decide on
    payload       TEXT NOT NULL,   -- JSON: exact args to replay on approve
    rationale     TEXT,            -- which policy rule the agent relied on
    amount        REAL,
    requested_by  TEXT NOT NULL,   -- agent name
    status        TEXT NOT NULL DEFAULT 'pending',  -- pending|approved|rejected
    decided_by    TEXT,
    decided_at    TEXT,
    decision_note TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (ticket_id) REFERENCES tickets(id)
);

CREATE TABLE IF NOT EXISTS purchase_orders (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id     INTEGER,
    vendor_id     INTEGER NOT NULL,
    sku           TEXT,
    size          TEXT,
    qty           INTEGER NOT NULL,
    unit_cost     REAL NOT NULL,
    total_cost    REAL NOT NULL,
    status        TEXT NOT NULL DEFAULT 'draft',  -- draft|approved|ordered|received|cancelled
    expected_date TEXT,             -- ordered date + vendor lead_days
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (vendor_id) REFERENCES vendors(id),
    FOREIGN KEY (ticket_id) REFERENCES tickets(id)
);

-- Customer/vendor messages. These are DRAFTS. Nothing is ever sent.
CREATE TABLE IF NOT EXISTS drafts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id    INTEGER,
    audience     TEXT NOT NULL,   -- customer | vendor | landlord
    recipient    TEXT,
    subject      TEXT,
    body         TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'draft',  -- draft only; never 'sent'
    created_by   TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (ticket_id) REFERENCES tickets(id)
);

-- One row per agent turn / tool call, so the dashboard can show the team
-- working and the write-up can show the delegation path.
CREATE TABLE IF NOT EXISTS agent_messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT,
    ticket_id   INTEGER,
    from_agent  TEXT,
    to_agent    TEXT,            -- set on a delegation/handoff
    role        TEXT NOT NULL,   -- message | handoff | tool_call | tool_result
    content     TEXT,
    tool_name   TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS runs (
    id         TEXT PRIMARY KEY,
    ticket_id  INTEGER,
    status     TEXT NOT NULL DEFAULT 'running',  -- running|waiting_approval|done|error
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    ended_at   TEXT,
    summary    TEXT
);

CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status);
CREATE INDEX IF NOT EXISTS idx_agent_messages_ticket ON agent_messages(ticket_id);
CREATE INDEX IF NOT EXISTS idx_agent_messages_run ON agent_messages(run_id);
"""

# Columns added to shipped tables (SQLite has no ADD COLUMN IF NOT EXISTS).
TICKET_COLUMNS = {
    "assignee": "TEXT",       # which agent owns it
    "resolution": "TEXT",     # how it ended
    "resolved_at": "TEXT",
}


def apply_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    existing = {r[1] for r in conn.execute("PRAGMA table_info(tickets)")}
    for col, decl in TICKET_COLUMNS.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE tickets ADD COLUMN {col} {decl}")
    conn.commit()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--migrate",
        action="store_true",
        help="apply schema to the existing working copy without resetting data",
    )
    args = ap.parse_args()

    if not ORIGINAL_DB.exists():
        raise SystemExit(f"Original database not found: {ORIGINAL_DB}")

    if not args.migrate:
        shutil.copyfile(ORIGINAL_DB, WORKING_DB)
        print(f"Reset {WORKING_DB.name} from {ORIGINAL_DB.name}")

    with sqlite3.connect(WORKING_DB) as conn:
        apply_schema(conn)
    print(f"Schema applied to {WORKING_DB.name}")

    with sqlite3.connect(WORKING_DB) as conn:
        names = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    print("Tables:", ", ".join(names))


if __name__ == "__main__":
    main()
