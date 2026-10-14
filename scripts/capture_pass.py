"""Write `output/full_run_capture.json` for the pass currently in the database.

    python scripts/capture_pass.py [--since "YYYY-MM-DD HH:MM:SS"]

`full_run.py` writes this file as it drives a pass. When a human approves the
requests by hand in the dashboard instead, nothing writes it — and the stale
copy from the previous pass then names the wrong runs, which silently gives the
write-up the wrong delegation chains and tool counts. This rebuilds it from the
database and the audit trail, so the manual path produces the same evidence the
scripted one does.

Which runs belong to "this pass"
--------------------------------
`init_working_db.py` empties `approvals`, `drafts` and `purchase_orders`, so the
earliest row in any of them was written after the last reset. That timestamp is
the anchor. Runs that started before it are from an earlier pass and are left
out, with a five-minute margin so a run that opened just before it wrote
anything is still counted.

The audit trail is append-only across resets, which is why this scoping matters
at all: without it the trail still holds every earlier run of ticket 101 and
would describe a delegation chain that never happened in one sitting.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import WORKING_DB  # noqa: E402

TRAIL = ROOT / "output" / "audit_trail.json"
OUT = ROOT / "output" / "full_run_capture.json"
MARGIN = timedelta(minutes=5)


def parse(ts: str) -> datetime:
    """Accept both the trail's ISO form and SQLite's 'YYYY-MM-DD HH:MM:SS'."""
    ts = ts.strip().replace("T", " ")
    for suffix in ("+00:00", "Z"):
        if ts.endswith(suffix):
            ts = ts[: -len(suffix)]
    return datetime.fromisoformat(ts.strip())


def anchor(conn: sqlite3.Connection) -> datetime | None:
    stamps = []
    for table in ("approvals", "drafts", "purchase_orders"):
        row = conn.execute(f"SELECT MIN(created_at) FROM {table}").fetchone()
        if row and row[0]:
            stamps.append(parse(row[0]))
    return min(stamps) if stamps else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", help="override the anchor timestamp")
    args = ap.parse_args()

    conn = sqlite3.connect(str(WORKING_DB))
    conn.row_factory = sqlite3.Row

    cutoff = parse(args.since) if args.since else anchor(conn)
    if cutoff is None:
        print("nothing written since the last reset — no pass to capture")
        return 1
    cutoff -= MARGIN
    print(f"including runs that started at or after {cutoff:%Y-%m-%d %H:%M:%S}")

    trail = json.loads(TRAIL.read_text(encoding="utf-8"))
    runs = [
        {"ticket_id": e["ticket_id"], "run_id": e["run_id"], "started_at": e["ts"]}
        for e in trail
        if e.get("event") == "run_start" and parse(e["ts"]) >= cutoff
    ]
    if not runs:
        print("no runs found after the anchor — is the trail up to date?")
        return 1

    # Attach each run's closing figures so anything reading the capture sees the
    # same cost and outcome `full_run.py` would have recorded.
    ends = {
        e["run_id"]: e
        for e in trail
        if e.get("event") == "run_end" and parse(e["ts"]) >= cutoff
    }
    for r in runs:
        end = ends.get(r["run_id"])
        if end:
            r["result"] = {
                "cost_usd": end.get("cost_usd"),
                "duration_ms": end.get("duration_ms"),
                "summary": end.get("content"),
            }

    # The ledger records what each decision did to the balance. Rebuilt from the
    # approvals the human actually decided, in the order they decided them.
    starting = 3400.0
    original = ROOT / "data" / "campus_customs.db"
    if original.exists():
        with sqlite3.connect(str(original)) as orig:
            starting = orig.execute("SELECT balance FROM cash_accounts").fetchone()[0]

    payments = [dict(r) for r in conn.execute("SELECT * FROM payments ORDER BY id")]
    paid_by_ref = {(p["kind"], p["ref_id"]): p for p in payments}

    ledger = []
    balance = starting
    decided = conn.execute(
        "SELECT * FROM approvals WHERE decided_at IS NOT NULL ORDER BY decided_at, id"
    )
    for a in decided:
        payload = json.loads(a["payload"] or "{}")
        tool = payload.get("tool", "")
        kind = {"pay_invoice": "invoice", "pay_rent": "rent"}.get(tool)
        ref = payload.get("invoice_id") or payload.get("lease_id") or payload.get("ref_id")
        pay = paid_by_ref.get((kind, ref)) if kind else None

        before = balance
        executed = False
        if pay and pay.get("_claimed") is None:
            pay["_claimed"] = a["id"]
            balance = round(balance - pay["amount"], 2)
            executed = True

        ledger.append(
            {
                "approval_id": a["id"],
                "ticket_id": a["ticket_id"],
                "kind": a["kind"],
                "summary": a["summary"],
                "amount": a["amount"],
                "requested_by": a["requested_by"],
                "executed": executed,
                "payment_id": pay["id"] if executed else None,
                "approved_by": a["decided_by"],
                "decided_at": a["decided_at"],
                "balance_before": before,
                "balance_after": balance,
            }
        )

    doc = {
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "source": "scripts/capture_pass.py (approvals decided in the dashboard)",
        "anchor": f"{cutoff:%Y-%m-%d %H:%M:%S}",
        "starting_balance": starting,
        "ending_balance": conn.execute("SELECT balance FROM cash_accounts").fetchone()[0],
        "runs": runs,
        "ledger": ledger,
    }
    OUT.write_text(json.dumps(doc, indent=2), encoding="utf-8")

    print(f"wrote {OUT.relative_to(ROOT)}")
    for r in runs:
        print(f"  {r['ticket_id']}  {r['run_id']}  {r['started_at']}")
    print(f"  {len(ledger)} decision(s), {sum(1 for x in ledger if x['executed'])} executed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
