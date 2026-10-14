"""Drive one full pass over the board and capture everything for the write-up.

    python scripts/full_run.py

Assumes the working database has just been reset and the backend is up on
port 8000. Does NOT reset by itself — the reset is a deliberate act the
assignment asks for explicitly, and a script that quietly wiped the board
before every run would make it impossible to inspect the state afterwards.

What it does, in order:

1. Records the starting checking balance.
2. Runs each ticket through `POST /tickets/{id}/run`.
3. Approves every parked request in the shop's payment priority order
   (rent before vendor invoices), which is what actually moves cash.
4. Re-runs any ticket still unresolved, so the team closes it against the
   board as it stands *after* the money moved.
5. Writes `output/resolved_tickets.json` and a cash ledger the write-up uses.

Every figure in the output is read back from the API after the fact rather
than accumulated as we go, so the ending balance is the database's number and
not this script's arithmetic.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BASE = "http://localhost:8000"
PRIORITY = {"rent": 0, "invoice": 1, "purchase_order": 2, "discount": 3}


def call(path: str, method: str = "GET", body: dict | None = None, timeout: int = 1200):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"_http_error": e.code, "detail": e.read().decode()[:300]}


def balance() -> float:
    return call("/cash")["balance"]


def priority_key(approval: dict) -> int:
    """Rent first, then vendor invoices — the shop's written payment priority."""
    payload = json.loads(approval.get("payload") or "{}")
    tool = payload.get("tool", "")
    if "rent" in tool:
        return PRIORITY["rent"]
    if "invoice" in tool:
        return PRIORITY["invoice"]
    return PRIORITY.get(approval["kind"], 9)


def main() -> int:
    ledger: list[dict] = []
    runs: list[dict] = []

    start = balance()
    print(f"STARTING CHECKING BALANCE: ${start:,.2f}\n")

    # --- 1. run every ticket --------------------------------------------
    board = call("/tickets")
    for t in board["tickets"]:
        tid = t["id"]
        print(f"--- running ticket {tid} ---", flush=True)
        res = call(f"/tickets/{tid}/run?wait=true", "POST")
        out = (res.get("result") or {}).get("outcome") or {}
        runs.append({"ticket_id": tid, "run_id": res.get("run_id"), "result": res.get("result")})
        print(
            f"    {out.get('status')} | assignee {out.get('assignee')} | "
            f"delegated {out.get('delegated_to')} | approvals {out.get('approval_ids')} | "
            f"drafts {out.get('draft_ids')}"
        )
        print(f"    cash after run: ${balance():,.2f}  (agents move no money)\n", flush=True)

    # --- 2. the human decides -------------------------------------------
    pending = sorted(call("/approvals?status=pending")["approvals"], key=priority_key)
    print(f"--- {len(pending)} approval(s) awaiting a human ---")
    for a in pending:
        before = balance()
        result = call(
            f"/approvals/{a['id']}/approve",
            "POST",
            {"decision": "approved", "decided_by": "Kyle Yeh", "note": "Full-run sign-off."},
        )
        after = result.get("balance_after", balance())
        ex = result.get("execution", {})
        print(
            f"    #{a['id']} t{a['ticket_id']} {a['kind']} ${a['amount']:,.2f} -> "
            f"executed={result.get('executed')} closed={result.get('ticket_closed')} "
            f"${before:,.2f} -> ${after:,.2f}"
        )
        ledger.append(
            {
                "approval_id": a["id"],
                "ticket_id": a["ticket_id"],
                "kind": a["kind"],
                "summary": a["summary"],
                "requested_by": a["requested_by"],
                "amount": a["amount"],
                "executed": result.get("executed"),
                "payment_id": ex.get("payment_id"),
                "paid_at": ex.get("paid_at"),
                "approved_by": ex.get("approved_by"),
                "balance_before": before,
                "balance_after": after,
                "ticket_closed": result.get("ticket_closed"),
            }
        )
        time.sleep(0.5)
    print()

    # --- 3. close anything still open against the post-payment board ----
    for attempt in range(1, 4):
        board = call("/tickets")
        unresolved = [t for t in board["tickets"] if not t["is_resolved"]]
        if not unresolved:
            break
        print(f"--- pass {attempt}: {len(unresolved)} ticket(s) still unresolved ---")
        for t in unresolved:
            print(f"    re-running {t['id']} (status {t['status']})", flush=True)
            res = call(f"/tickets/{t['id']}/run?wait=true", "POST")
            out = (res.get("result") or {}).get("outcome") or {}
            runs.append(
                {"ticket_id": t["id"], "run_id": res.get("run_id"), "result": res.get("result")}
            )
            print(f"      -> {out.get('status')}")
            # A follow-up run can park a fresh request; decide it too.
            for a in sorted(call("/approvals?status=pending")["approvals"], key=priority_key):
                before = balance()
                result = call(
                    f"/approvals/{a['id']}/approve",
                    "POST",
                    {"decision": "approved", "decided_by": "Kyle Yeh", "note": "Full-run sign-off."},
                )
                ex = result.get("execution", {})
                after = result.get("balance_after", balance())
                print(
                    f"      approval #{a['id']} ${a['amount']:,.2f} -> "
                    f"executed={result.get('executed')} ${before:,.2f} -> ${after:,.2f}"
                )
                ledger.append(
                    {
                        "approval_id": a["id"],
                        "ticket_id": a["ticket_id"],
                        "kind": a["kind"],
                        "summary": a["summary"],
                        "requested_by": a["requested_by"],
                        "amount": a["amount"],
                        "executed": result.get("executed"),
                        "payment_id": ex.get("payment_id"),
                        "paid_at": ex.get("paid_at"),
                        "approved_by": ex.get("approved_by"),
                        "balance_before": before,
                        "balance_after": after,
                        "ticket_closed": result.get("ticket_closed"),
                    }
                )
        print()

    # --- 4. final state, read back from the database --------------------
    board = call("/tickets")
    cash = call("/cash")
    end = cash["balance"]

    print("=" * 66)
    print(f"BOARD: open={board['open']}  resolved={board['resolved']}")
    for t in board["tickets"]:
        print(f"  #{t['id']}: {t['status']:<12} assignee={t['assignee']}")
    print(f"\nSTART ${start:,.2f}  ->  END ${end:,.2f}   (moved ${start - end:,.2f})")
    for row in ledger:
        if row["executed"] and row["payment_id"]:
            print(
                f"  -${row['amount']:>9,.2f}  t{row['ticket_id']}  {row['kind']:<15} "
                f"payment #{row['payment_id']}"
            )
    # Only approvals that actually produced a payment row moved cash. A
    # discount is approved at a price and debits nothing; summing its amount
    # here would invent spending that never happened — which is exactly the
    # wrong-cash-math failure this run is supposed to avoid.
    paid_total = sum(r["amount"] for r in ledger if r["executed"] and r["payment_id"])
    print(f"  {'':>10}  sum of executed payments: ${paid_total:,.2f}")
    print(f"  arithmetic check: {start:,.2f} - {paid_total:,.2f} = {start - paid_total:,.2f}")
    print(f"  database says:    {end:,.2f}")
    print("  MATCH" if abs((start - paid_total) - end) < 0.005 else "  *** MISMATCH ***")
    print("=" * 66)

    out = ROOT / "output" / "full_run_capture.json"
    out.write_text(
        json.dumps(
            {
                "starting_balance": start,
                "ending_balance": end,
                "ledger": ledger,
                "runs": runs,
                "final_board": board,
                "final_cash": cash,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\ncapture -> {out.relative_to(ROOT)}")
    return 0 if board["open"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
