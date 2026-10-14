"""Prove the money guardrails hold, without spending a token.

    python scripts/test_guardrails.py

Every check here goes through the MCP server over a real stdio connection, the
same path the agents use. No model is called, so the result is deterministic and
reproducible — which is the point. A safety property demonstrated by asking a
language model nicely is not demonstrated at all.

What is checked:

  1. A payment with no approval row is refused.
  2. A payment whose approval is still 'pending' is refused.
  3. An approval for one obligation cannot be replayed against another.
  4. An approved payment succeeds, debits cash, and records the human's name.
  5. The same obligation cannot be paid twice.
  6. A spend that would overdraw the account is refused.
  7. Discretionary spend that would break the cash reserve is refused, while a
     contractual obligation may still be paid down toward zero.
  8. A ticket cannot be closed while an approval is pending.
  9. The server exposes no tool capable of sending anything.

The script RESETS the working database before it starts, because it moves real
money through the working copy and must begin from a known board.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastmcp import Client

from app.config import ROOT, WORKING_DB

PASS = "PASS"
FAIL = "FAIL"
results: list[tuple[str, str, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    results.append((PASS if condition else FAIL, name, detail))
    mark = "[OK]  " if condition else "[FAIL]"
    print(f"  {mark} {name}" + (f"\n          {detail}" if detail else ""))


def unwrap(result: Any) -> Any:
    """FastMCP wraps a bare return value under a `result` key."""
    data = getattr(result, "structured_content", None)
    if isinstance(data, dict):
        return data.get("result", data)
    return getattr(result, "data", data)


def human_decides(approval_id: int, decision: str, who: str = "Kyle Yeh") -> None:
    """Stand in for the dashboard: a HUMAN sets an approval's status.

    Written with direct SQL on purpose. There is no MCP tool that approves
    anything, because no agent may ever approve anything — including its own
    request. The decision enters the system from outside the agent team.
    """
    with sqlite3.connect(WORKING_DB) as conn:
        conn.execute(
            "UPDATE approvals SET status=?, decided_by=?, decided_at=date('now'), "
            "decision_note='test harness' WHERE id=?",
            (decision, who, approval_id),
        )


def cash() -> float:
    with sqlite3.connect(WORKING_DB) as conn:
        return conn.execute("SELECT balance FROM cash_accounts LIMIT 1").fetchone()[0]


async def main() -> int:
    print("Resetting working database to a known board...")
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "init_working_db.py")],
        check=True,
        capture_output=True,
    )
    print(f"Starting cash: ${cash():,.2f}\n")

    async with Client(str(ROOT / "mcp_server" / "server.py")) as c:

        async def call(tool: str, **args: Any) -> Any:
            return unwrap(await c.call_tool(tool, args))

        # --- 9. no send capability -------------------------------------
        print("Tool surface:")
        names = {t.name for t in await c.list_tools()}
        sendish = {n for n in names if any(w in n for w in ("send", "email", "sms", "call_vendor"))}
        check(
            "No tool on the server can send anything",
            not sendish,
            f"{len(names)} tools, none matching send/email/sms. Drafting is save_draft_message.",
        )

        # --- 1. payment with no approval at all -------------------------
        print("\nPayments without authorisation:")
        r = await call("pay_invoice", invoice_id=501, approval_id=999)
        check(
            "pay_invoice refuses a non-existent approval",
            "error" in r and not r.get("paid"),
            r.get("error", ""),
        )

        # --- 2. payment with a pending approval -------------------------
        a = await call(
            "request_approval",
            ticket_id=102,
            kind="payment",
            summary="Rent for Chapel Street",
            rationale="Lease 1, due 2026-09-02",
            requested_by="facilities",
            amount=2400.0,
            payload={"tool": "pay_rent", "ref_id": 1},
        )
        rent_approval = a["approval_id"]
        check(
            "request_approval parks as 'pending'",
            a["status"] == "pending",
            f"approval #{rent_approval}",
        )

        r = await call("pay_rent", lease_id=1, approval_id=rent_approval)
        check(
            "pay_rent refuses while the approval is pending",
            r.get("refused") is True,
            r.get("error", ""),
        )
        check("No money moved on a refused payment", cash() == 3400.0, f"balance ${cash():,.2f}")

        # --- 3. an approval cannot be replayed against another target ---
        print("\nApproval scope:")
        human_decides(rent_approval, "approved")
        r = await call("pay_invoice", invoice_id=501, approval_id=rent_approval)
        check(
            "Rent approval cannot be replayed to pay invoice 501",
            r.get("refused") is True,
            r.get("error", ""),
        )

        # --- 4. approved payment succeeds -------------------------------
        print("\nApproved payments:")
        r = await call("pay_rent", lease_id=1, approval_id=rent_approval)
        check("Approved rent payment succeeds", r.get("paid") is True, f"payment #{r.get('payment_id')}")
        check(
            "Cash debited correctly",
            cash() == 1000.0,
            f"$3,400.00 - $2,400.00 = ${cash():,.2f}",
        )
        check(
            "Payment records the human approver, not an agent",
            r.get("approved_by") == "Kyle Yeh",
            f"approved_by = {r.get('approved_by')!r}",
        )
        check(
            "Lease next_due advanced a month",
            r.get("next_due_now") == "2026-10-02",
            f"{r.get('paid_for_due_date')} -> {r.get('next_due_now')}",
        )

        # --- 5. no double payment ---------------------------------------
        r = await call("pay_rent", lease_id=1, approval_id=rent_approval)
        check("Same rent cycle cannot be paid twice", r.get("refused") is True, r.get("error", ""))

        # --- 7a. contractual obligation may spend toward zero -----------
        print("\nCash floors:")
        a2 = await call(
            "request_approval",
            ticket_id=101,
            kind="payment",
            summary="Overdue invoice 501",
            rationale="Blocks Bulldog Print Co from shipping",
            requested_by="accounting",
            amount=840.0,
            payload={"tool": "pay_invoice", "ref_id": 501},
        )
        human_decides(a2["approval_id"], "approved")
        r = await call("pay_invoice", invoice_id=501, approval_id=a2["approval_id"])
        check(
            "Contractual debt may be paid below the $250 reserve",
            r.get("paid") is True and cash() == 160.0,
            f"balance now ${cash():,.2f} (reserve $250 binds discretionary spend only)",
        )

        # --- 5b. invoice cannot be paid twice ---------------------------
        r = await call("pay_invoice", invoice_id=501, approval_id=a2["approval_id"])
        check("Same invoice cannot be paid twice", r.get("refused") is True, r.get("error", ""))

        # --- 7b. discretionary spend blocked by the reserve -------------
        r = await call(
            "create_purchase_order",
            ticket_id=103,
            vendor_id=1,
            sku="CC-HOOD-NAVY",
            size="M",
            qty=12,
            created_by="inventory",
        )
        check(
            "Unaffordable purchase order is refused at the point it is raised",
            r.get("refused") is True,
            f"12 x $22 = $264 against ${cash():,.2f} available. {r.get('error','')}",
        )

        # --- 6. overdraft is impossible ---------------------------------
        print("\nOverdraft:")
        with sqlite3.connect(WORKING_DB) as conn:
            conn.execute(
                "INSERT INTO invoices (id, vendor_id, amount, due_date, status, description) "
                "VALUES (902, 1, 5000.0, '2026-08-20', 'open', 'Synthetic oversized bill')"
            )
        a3 = await call(
            "request_approval",
            ticket_id=101,
            kind="payment",
            summary="Oversized bill",
            rationale="Guardrail test",
            requested_by="accounting",
            amount=5000.0,
            payload={"tool": "pay_invoice", "ref_id": 902},
        )
        human_decides(a3["approval_id"], "approved")
        before = cash()
        r = await call("pay_invoice", invoice_id=902, approval_id=a3["approval_id"])
        check(
            "A payment larger than the balance is refused even when approved",
            r.get("refused") is True,
            f"${5000:,.2f} against ${before:,.2f}. {r.get('error','')}",
        )
        check("Balance unchanged after the refusal", cash() == before, f"${cash():,.2f}")

        # --- 8. ticket cannot close over a pending approval -------------
        print("\nTicket hygiene:")
        a4 = await call(
            "request_approval",
            ticket_id=103,
            kind="discount",
            summary="Bulk hoodie discount",
            rationale="Guardrail test",
            requested_by="accounting",
            amount=0.0,
            payload={},
        )
        r = await call("update_ticket", ticket_id=103, status="resolved")
        check(
            "Ticket cannot be marked resolved with an approval pending",
            r.get("refused") is True,
            r.get("error", ""),
        )
        r = await call("update_ticket", ticket_id=103, status="waiting_approval")
        check("Ticket may be marked waiting_approval", r.get("updated") is True, "")

        # --- drafts never send ------------------------------------------
        r = await call(
            "save_draft_message",
            ticket_id=101,
            audience="customer",
            recipient="Tauhid Zaman",
            subject="Test",
            body="Guardrail test draft.",
            created_by="customer_service",
        )
        check(
            "Draft is saved as 'draft' and reports sent=False",
            r.get("status") == "draft" and r.get("sent") is False,
            f"draft #{r.get('draft_id')}",
        )

    failed = [r for r in results if r[0] == FAIL]
    print("\n" + "=" * 68)
    print(f"{len(results) - len(failed)}/{len(results)} guardrail checks passed.")
    if failed:
        for _, name, detail in failed:
            print(f"  FAILED: {name} {detail}")
    print("=" * 68)
    print("\nThe working database is now mid-test. Reset before a real run:")
    print("  python scripts/init_working_db.py")

    out = ROOT / "output" / "guardrail_checks.json"
    out.write_text(
        json.dumps(
            [{"result": r, "check": n, "detail": d} for r, n, d in results], indent=2
        ),
        encoding="utf-8",
    )
    print(f"Evidence written to {out.relative_to(ROOT)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
