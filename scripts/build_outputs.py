"""Build `output/resolved_tickets.json` from the real run.

    python scripts/build_outputs.py

Reads the working database and `output/audit_trail.json` and writes, per
ticket: its final status, a short outcome, what each agent actually
contributed, and every human approval attached to it.

Nothing here is written by hand or carried over from the planning document.
Agent contributions are reconstructed from the audit trail — the tools each
agent called and the line it signed off with — so the file records what
happened rather than what was meant to happen.

Cash figures are read back from `cash_accounts` and `payments`, and the
arithmetic is checked against the database rather than accumulated, because a
ledger that agrees with itself but not with the shop is worthless.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import ORIGINAL_DB, WORKING_DB

AUDIT = ROOT / "output" / "audit_trail.json"
CAPTURE = ROOT / "output" / "full_run_capture.json"
OUT = ROOT / "output" / "resolved_tickets.json"

# Framework mechanics, not work a person did.
HIDE_TOOLS = {"final_result", "delegate"}

CHARACTER = {
    "boss": "Johnny Rose",
    "inventory": "David Rose",
    "accounting": "Patrick Brewer",
    "facilities": "Stevie Budd",
    "customer_service": "Alexis Rose",
}


def rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    conn.row_factory = sqlite3.Row
    return [dict(r) for r in conn.execute(sql, params)]


def audit_rows() -> list[dict]:
    if not AUDIT.exists():
        return []
    return json.load(open(AUDIT, encoding="utf-8"))


def runs_for_ticket(trail: list[dict], ticket_id: int, capture: dict) -> list[str]:
    """Run ids that worked this ticket **in the pass being reported**.

    The audit trail is append-only across database resets, so it still holds
    every earlier run of ticket 101 going back days. Reading all of them would
    describe a delegation chain nineteen hops long that never happened in one
    sitting. The run capture names the runs from this pass, so it wins; the
    trail is only consulted when no capture exists.
    """
    from_capture = [
        r["run_id"]
        for r in capture.get("runs", [])
        if r.get("ticket_id") == ticket_id and r.get("run_id")
    ]
    if from_capture:
        return from_capture

    seen: list[str] = []
    for r in trail:
        if r.get("ticket_id") == ticket_id and r.get("run_id") not in seen:
            seen.append(r["run_id"])
    return seen


def contributions(trail: list[dict], run_ids: list[str]) -> list[dict]:
    """What each agent did across the given runs, in the order they appeared."""
    order: list[str] = []
    acc: dict[str, dict] = {}

    for r in trail:
        if r.get("run_id") not in run_ids:
            continue
        agent = r.get("agent")
        if not agent or agent not in CHARACTER:
            continue
        if agent not in acc:
            order.append(agent)
            acc[agent] = {
                "agent": agent,
                "character": CHARACTER[agent],
                "tools_used": [],
                "delegated_to": [],
                "said": None,
            }
        entry = acc[agent]

        if r.get("event") == "tool_call":
            tool = r.get("tool_name")
            if tool and tool not in HIDE_TOOLS and tool not in entry["tools_used"]:
                entry["tools_used"].append(tool)
        if r.get("event") == "delegation" and r.get("to_agent"):
            if r["to_agent"] not in entry["delegated_to"]:
                entry["delegated_to"].append(r["to_agent"])
        if r.get("event") in {"delegation_result", "run_end"} and r.get("said"):
            entry["said"] = r["said"]

    return [acc[a] for a in order]


def delegation_chain(trail: list[dict], run_ids: list[str]) -> list[str]:
    """Readable handoff path, e.g. ['boss -> inventory', 'inventory -> accounting']."""
    chain = []
    for r in trail:
        if r.get("run_id") in run_ids and r.get("event") == "delegation":
            hop = f"{r.get('agent')} -> {r.get('to_agent')}"
            chain.append(hop)
    return chain


def main() -> int:
    conn = sqlite3.connect(WORKING_DB)
    orig = sqlite3.connect(ORIGINAL_DB)

    trail = audit_rows()
    capture = json.load(open(CAPTURE, encoding="utf-8")) if CAPTURE.exists() else {}

    starting = rows(orig, "SELECT balance FROM cash_accounts LIMIT 1")[0]["balance"]
    ending = rows(conn, "SELECT balance FROM cash_accounts LIMIT 1")[0]["balance"]
    shop_date = rows(conn, "SELECT date_today FROM desk LIMIT 1")[0]["date_today"]
    payments = rows(conn, "SELECT * FROM payments ORDER BY id")
    approvals = rows(conn, "SELECT * FROM approvals ORDER BY id")
    drafts = rows(conn, "SELECT * FROM drafts ORDER BY id")
    pos = rows(conn, "SELECT * FROM purchase_orders ORDER BY id")

    tickets_out = []
    running = starting

    for t in rows(conn, "SELECT * FROM tickets ORDER BY id"):
        tid = t["id"]
        run_ids = runs_for_ticket(trail, tid, capture)

        t_approvals = [a for a in approvals if a["ticket_id"] == tid]

        # Attribute each payment to exactly ONE ticket.
        #
        # Matching on the payload's reference alone double-counts: ticket 103
        # also raised a request to pay invoice 501, and although that request
        # was REFUSED (the invoice was already settled), its payload still
        # points at invoice 501. Crediting the payment to both tickets would
        # make the per-ticket column sum to more than the shop actually spent.
        #
        # The run capture records which approval produced which payment row, so
        # a payment belongs to the ticket whose approval actually executed.
        paid_by_ticket = {
            row["payment_id"]: row["ticket_id"]
            for row in capture.get("ledger", [])
            if row.get("executed") and row.get("payment_id")
        }
        t_payments = [p for p in payments if paid_by_ticket.get(p["id"]) == tid]
        cash_delta = -sum(p["amount"] for p in t_payments)

        # Balances are taken from the run capture, which recorded them either
        # side of each approval as it executed. Walking the tickets in id order
        # and subtracting as we go would report the wrong intermediate figures:
        # rent (ticket 102) was paid BEFORE the invoice (ticket 101), because
        # the shop's payment priority puts rent first. The ending balance would
        # still come out right, which is exactly what makes that kind of error
        # easy to miss.
        # Every decision on this ticket brackets the balance, including ones
        # that were refused — ticket 103's second request was refused (invoice
        # already paid) and moved nothing, but it still tells us what the
        # balance was when the shop looked at it. Only executed rows feed the
        # delta; all rows feed the before/after bracket.
        my_rows = [r for r in capture.get("ledger", []) if r.get("ticket_id") == tid]
        if my_rows:
            before = my_rows[0]["balance_before"]
            running = my_rows[-1]["balance_after"]
        else:
            before = running

        tickets_out.append(
            {
                "id": tid,
                "subject": t["subject"],
                "requester": t["requester"],
                "type": t["type"],
                "final_status": t["status"],
                "resolved_at": t["resolved_at"],
                "assignee": t["assignee"],
                "assignee_character": CHARACTER.get(t["assignee"] or ""),
                "outcome": t["resolution"],
                "runs": run_ids,
                "delegation_chain": delegation_chain(trail, run_ids),
                "agent_contributions": contributions(trail, run_ids),
                "human_approvals": [
                    {
                        "approval_id": a["id"],
                        "kind": a["kind"],
                        "summary": a["summary"],
                        "amount": a["amount"],
                        "requested_by": a["requested_by"],
                        "requested_by_character": CHARACTER.get(a["requested_by"] or ""),
                        "status": a["status"],
                        "decided_by": a["decided_by"],
                        "decided_at": a["decided_at"],
                        "decision_note": a["decision_note"],
                        "payload": json.loads(a["payload"] or "{}"),
                    }
                    for a in t_approvals
                ],
                "payments_executed": [
                    {
                        "payment_id": p["id"],
                        "kind": p["kind"],
                        "ref_id": p["ref_id"],
                        "amount": p["amount"],
                        "paid_at": p["paid_at"],
                        "approved_by": p["approved_by"],
                    }
                    for p in t_payments
                ],
                "drafts_written": [
                    {
                        "draft_id": d["id"],
                        "audience": d["audience"],
                        "recipient": d["recipient"],
                        "subject": d["subject"],
                        "status": d["status"],
                        "sent": False,
                        "created_by": d["created_by"],
                    }
                    for d in drafts
                    if d["ticket_id"] == tid
                ],
                "purchase_orders": [p for p in pos if p["ticket_id"] == tid],
                "cash": {
                    "balance_before": before,
                    "change": cash_delta,
                    "balance_after": running,
                },
            }
        )

    paid_total = round(sum(p["amount"] for p in payments), 2)
    computed = round(starting - paid_total, 2)

    doc = {
        "shop_date": shop_date,
        "model": "gpt-6-luna",
        "starting_checking_balance": starting,
        "ending_checking_balance": ending,
        "total_paid": paid_total,
        "arithmetic_check": {
            "starting_minus_payments": computed,
            "database_cash_accounts_balance": ending,
            "matches": abs(computed - ending) < 0.005,
        },
        "tickets": tickets_out,
        "all_payments": payments,
        "run_cost_usd": round(
            sum((r.get("result") or {}).get("cost_usd") or 0 for r in capture.get("runs", [])), 4
        ),
    }

    OUT.write_text(json.dumps(doc, indent=2), encoding="utf-8")

    print(f"starting ${starting:,.2f}  ending ${ending:,.2f}  paid ${paid_total:,.2f}")
    print(f"arithmetic matches database: {doc['arithmetic_check']['matches']}")
    for t in tickets_out:
        print(
            f"  #{t['id']} {t['final_status']:<10} {len(t['agent_contributions'])} agents, "
            f"{len(t['human_approvals'])} approval(s), cash {t['cash']['change']:+.2f}"
        )
    print(f"\nwrote {OUT.relative_to(ROOT)}")
    return 0 if doc["arithmetic_check"]["matches"] else 1


if __name__ == "__main__":
    sys.exit(main())
