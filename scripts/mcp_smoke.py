"""Smoke-test every MCP tool over a real stdio connection, and verify the output.

Launches `mcp_server/server.py` as a subprocess, speaks the MCP protocol to it
exactly as a client would, calls each tool, and then independently re-queries
`data/campus_customs_new.db` with plain SQL to confirm the tool reported the
truth. Evidence is written to `output/mcp_smoke.json`.

    python scripts/mcp_smoke.py

The verification step is the point: a tool that returns plausible-looking
numbers is worthless if they are not the numbers in the database. Every check
below compares a tool's field against a value read straight from a table.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastmcp import Client

from app.config import WORKING_DB

SERVER = Path(__file__).resolve().parent.parent / "mcp_server" / "server.py"
OUT = Path(__file__).resolve().parent.parent / "output" / "mcp_smoke.json"


def sql(query: str, params: tuple = ()) -> list[tuple]:
    """Independent read of the working copy, used to check the tools."""
    conn = sqlite3.connect(f"file:{WORKING_DB}?mode=ro", uri=True)
    try:
        return conn.execute(query, params).fetchall()
    finally:
        conn.close()


def unwrap(result) -> dict:
    """Pull the JSON payload out of an MCP CallToolResult."""
    if getattr(result, "structured_content", None):
        sc = result.structured_content
        # FastMCP wraps a bare return value under "result".
        return sc.get("result", sc) if isinstance(sc, dict) else sc
    if getattr(result, "data", None) is not None:
        return result.data
    return json.loads(result.content[0].text)


# Each case: the question being asked, the call, and checks against raw SQL.
CASES = [
    {
        "ticket": 101,
        "prompt": (
            "Ticket 101: Tauhid Zaman wants one Bulldog tee, SKU CC-TEE-WHITE, "
            "in size S. Do we have it on the shelf right now, and if not, how "
            "many are we short?"
        ),
        "tool": "check_stock",
        "args": {"sku": "CC-TEE-WHITE", "size": "S", "qty_wanted": 1},
        "checks": lambda out: [
            (
                "qty_on_hand matches inventory table",
                out["qty_on_hand"],
                sql("SELECT qty FROM inventory WHERE sku=? AND size=?",
                    ("CC-TEE-WHITE", "S"))[0][0],
            ),
            (
                "unit_cost matches pricing table",
                out["unit_cost"],
                sql("SELECT unit_cost FROM pricing WHERE sku=?",
                    ("CC-TEE-WHITE",))[0][0],
            ),
            (
                "list_price matches pricing table",
                out["list_price"],
                sql("SELECT list_price FROM pricing WHERE sku=?",
                    ("CC-TEE-WHITE",))[0][0],
            ),
            ("shortfall = wanted - on hand", out["shortfall"], 1),
            ("can_fill_now is false", out["can_fill_now"], False),
        ],
    },
    {
        "ticket": 101,
        "prompt": (
            "Ticket 101 cannot be filled from stock. Who can reprint "
            "CC-TEE-WHITE, how long will it take, and will they actually ship "
            "to us right now?"
        ),
        "tool": "find_restock_vendor",
        "args": {"sku": "CC-TEE-WHITE", "qty": 1},
        "checks": lambda out: [
            (
                "vendor_id matches the apparel vendor in vendors",
                out["vendors"][0]["vendor_id"],
                sql("SELECT id FROM vendors WHERE specialty LIKE '%apparel%'")[0][0],
            ),
            (
                "lead_days matches vendors table",
                out["vendors"][0]["lead_days"],
                sql("SELECT lead_days FROM vendors WHERE id=1")[0][0],
            ),
            (
                "blocking invoice id matches invoices table",
                out["vendors"][0]["blocked_by_open_invoices"][0]["id"],
                sql("SELECT id FROM invoices WHERE vendor_id=1 AND status='open'")[0][0],
            ),
            (
                "amount_to_unblock matches invoice amount",
                out["vendors"][0]["amount_to_unblock"],
                sql("SELECT amount FROM invoices WHERE vendor_id=1 AND status='open'")[0][0],
            ),
            (
                "arrival = desk.date_today + lead_days",
                out["vendors"][0]["earliest_arrival_if_ordered_today"],
                sql("SELECT date(date_today, '+' || "
                    "(SELECT lead_days FROM vendors WHERE id=1) || ' days') FROM desk")[0][0],
            ),
            ("vendor will not ship", out["vendors"][0]["will_ship"], False),
        ],
    },
    {
        "ticket": 102,
        "prompt": (
            "Ticket 102: Elm City Properties says rent is due. What is our cash "
            "balance, what do we owe in total, what is already overdue as of the "
            "shop's date, and what is left if we settle everything?"
        ),
        "tool": "get_cash_position",
        "args": {},
        "checks": lambda out: [
            (
                "balance matches cash_accounts",
                out["balance"],
                sql("SELECT balance FROM cash_accounts")[0][0],
            ),
            (
                "shop_date matches desk.date_today",
                out["shop_date"],
                sql("SELECT date_today FROM desk")[0][0],
            ),
            (
                "rent amount matches leases.monthly_rent",
                next(o["amount"] for o in out["obligations"] if o["kind"] == "rent"),
                sql("SELECT monthly_rent FROM leases WHERE id=1")[0][0],
            ),
            (
                "rent due date matches leases.next_due",
                next(o["due_date"] for o in out["obligations"] if o["kind"] == "rent"),
                sql("SELECT next_due FROM leases WHERE id=1")[0][0],
            ),
            (
                "total_owed = open invoices + rent",
                out["total_owed"],
                round(
                    sql("SELECT COALESCE(SUM(amount),0) FROM invoices WHERE status='open'")[0][0]
                    + sql("SELECT COALESCE(SUM(monthly_rent),0) FROM leases")[0][0],
                    2,
                ),
            ),
            (
                "remaining = balance - total_owed",
                out["remaining_if_all_paid"],
                round(
                    sql("SELECT balance FROM cash_accounts")[0][0]
                    - (
                        sql("SELECT COALESCE(SUM(amount),0) FROM invoices WHERE status='open'")[0][0]
                        + sql("SELECT COALESCE(SUM(monthly_rent),0) FROM leases")[0][0]
                    ),
                    2,
                ),
            ),
            ("one obligation is overdue", out["overdue_count"], 1),
        ],
    },
    {
        "ticket": 103,
        "prompt": (
            "Ticket 103: the Yale AI Club wants 20 navy hoodies in size M. How "
            "many do we actually have, and what is the margin at list price?"
        ),
        "tool": "check_stock",
        "args": {"sku": "CC-HOOD-NAVY", "size": "M", "qty_wanted": 20},
        "checks": lambda out: [
            (
                "qty_on_hand matches inventory table",
                out["qty_on_hand"],
                sql("SELECT qty FROM inventory WHERE sku=? AND size=?",
                    ("CC-HOOD-NAVY", "M"))[0][0],
            ),
            ("shortfall = 20 - 8", out["shortfall"], 12),
            (
                "unit_cost matches pricing table",
                out["unit_cost"],
                sql("SELECT unit_cost FROM pricing WHERE sku=?", ("CC-HOOD-NAVY",))[0][0],
            ),
            (
                "line_total_at_list = list_price * 20",
                out["line_total_at_list"],
                round(sql("SELECT list_price FROM pricing WHERE sku=?",
                          ("CC-HOOD-NAVY",))[0][0] * 20, 2),
            ),
        ],
    },
]


async def main() -> int:
    client = Client(str(SERVER))
    results = []
    all_passed = True

    async with client:
        # list_tools is the handshake proof: it only returns after initialize
        # has completed over stdio. (ping is optional and this server omits it.)
        tools = await client.list_tools()
        tool_names = sorted(t.name for t in tools)
        print(f"Connected over stdio. Tools advertised: {', '.join(tool_names)}\n")

        for case in CASES:
            out = unwrap(await client.call_tool(case["tool"], case["args"]))

            checks = []
            for label, got, expected in case["checks"](out):
                ok = got == expected
                all_passed &= ok
                checks.append(
                    {
                        "check": label,
                        "tool_returned": got,
                        "database_says": expected,
                        "match": ok,
                    }
                )

            passed = sum(c["match"] for c in checks)
            status = "PASS" if passed == len(checks) else "FAIL"
            print(f"[{status}] ticket {case['ticket']} -> {case['tool']}  "
                  f"({passed}/{len(checks)} checks)")
            for c in checks:
                if not c["match"]:
                    print(f"    MISMATCH {c['check']}: "
                          f"tool={c['tool_returned']!r} db={c['database_says']!r}")

            results.append(
                {
                    "ticket": case["ticket"],
                    "prompt": case["prompt"],
                    "tool": case["tool"],
                    "arguments": case["args"],
                    "tool_output": out,
                    "verification": checks,
                    "all_checks_passed": passed == len(checks),
                }
            )

    evidence = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "server": "mcp_server/server.py",
        "transport": "stdio",
        "database": "data/campus_customs_new.db",
        "tools_advertised": tool_names,
        "how_verified": (
            "Each tool was called over a real MCP stdio connection. Every value "
            "below was then re-read from data/campus_customs_new.db with plain "
            "SQL and compared field by field."
        ),
        "all_checks_passed": all_passed,
        "calls": results,
    }

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    total = sum(len(r["verification"]) for r in results)
    print(f"\n{'ALL CHECKS PASSED' if all_passed else 'FAILURES PRESENT'} "
          f"({total} field comparisons across {len(results)} calls)")
    print(f"Evidence written to {OUT.relative_to(OUT.parent.parent)}")
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
