"""Inspect the shop database: schema, contents, and how the open tickets link up.

    python scripts/inspect_db.py              # working copy
    python scripts/inspect_db.py --original   # pristine original
    python scripts/inspect_db.py --tickets    # just the ticket linkage view

Read-only. Never writes to either database.
"""

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import ORIGINAL_DB, WORKING_DB

# Tables that ship with the assignment, in a sensible reading order.
SHIPPED = [
    "desk",
    "tickets",
    "inventory",
    "pricing",
    "vendors",
    "leases",
    "cash_accounts",
    "invoices",
    "payments",
]


def connect(path: Path) -> sqlite3.Connection:
    # Read-only URI so inspection can never mutate the data.
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def show_schema(conn: sqlite3.Connection) -> None:
    tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    for name in tables:
        cols = list(conn.execute(f'PRAGMA table_info("{name}")'))
        count = conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
        print(f"\n{name}  ({count} rows)")
        for c in cols:
            pk = "  PK" if c["pk"] else ""
            null = "" if c["notnull"] else "  NULL ok"
            print(f"    {c['name']:<14} {c['type'] or 'ANY':<8}{pk}{null}")


def show_contents(conn: sqlite3.Connection) -> None:
    for name in SHIPPED:
        rows = list(conn.execute(f'SELECT * FROM "{name}"'))
        print(f"\n=== {name} ({len(rows)} rows)")
        if not rows:
            print("    (empty)")
            continue
        for r in rows:
            print("   ", dict(r))


def show_ticket_links(conn: sqlite3.Connection) -> None:
    """The three open tickets, resolved against every table they touch."""
    today = conn.execute("SELECT date_today FROM desk").fetchone()[0]
    cash = conn.execute(
        "SELECT name, balance FROM cash_accounts"
    ).fetchone()

    print("=" * 72)
    print(f"SHOP DATE (desk.date_today): {today}")
    print(f"CASH ({cash['name']}): ${cash['balance']:,.2f}   <- only ever decreases")
    print("=" * 72)

    for t in conn.execute("SELECT * FROM tickets ORDER BY id"):
        print(f"\n--- Ticket {t['id']}  [{t['type']}]  status={t['status']}")
        print(f"    subject   : {t['subject']}")
        print(f"    requester : {t['requester']}")
        print(f"    created   : {t['created_at']}")
        print(f"    notes     : {t['notes']}")

        # --- link: inventory + pricing, via sku/size
        if t["sku"]:
            inv = conn.execute(
                "SELECT * FROM inventory WHERE sku=? AND size=?",
                (t["sku"], t["size"]),
            ).fetchone()
            price = conn.execute(
                "SELECT * FROM pricing WHERE sku=?", (t["sku"],)
            ).fetchone()
            on_hand = inv["qty"] if inv else 0
            want = t["qty"] or 0
            short = max(0, want - on_hand)
            print(f"    -> inventory[{t['sku']}/{t['size']}]: on hand {on_hand}"
                  f", wants {want}" + (f", SHORT {short}" if short else ", covered"))
            if price:
                margin = (price["list_price"] - price["unit_cost"]) / price["list_price"]
                print(f"    -> pricing[{t['sku']}]: cost ${price['unit_cost']:.2f}"
                      f", list ${price['list_price']:.2f}, margin {margin:.0%}")
                if want:
                    print(f"       order at list = ${price['list_price'] * want:,.2f}")

        # --- link: invoices + the vendor behind them
        if t["invoice_id"]:
            inv_row = conn.execute(
                "SELECT * FROM invoices WHERE id=?", (t["invoice_id"],)
            ).fetchone()
            v = conn.execute(
                "SELECT * FROM vendors WHERE id=?", (inv_row["vendor_id"],)
            ).fetchone()
            overdue = inv_row["due_date"] < today
            print(f"    -> invoice {inv_row['id']}: ${inv_row['amount']:,.2f}"
                  f", due {inv_row['due_date']}, status {inv_row['status']}"
                  f"  {'** OVERDUE **' if overdue else ''}")
            print(f"    -> vendor {v['id']} {v['name']}: {v['specialty']}"
                  f", lead {v['lead_days']} days")
            if inv_row["status"] == "open":
                print(f"       !! {v['name']} will not ship while this invoice is open")

        # --- link: leases
        if t["lease_id"]:
            l = conn.execute(
                "SELECT * FROM leases WHERE id=?", (t["lease_id"],)
            ).fetchone()
            days = (
                conn.execute("SELECT julianday(?) - julianday(?)",
                             (l["next_due"], today)).fetchone()[0]
            )
            print(f"    -> lease {l['id']} {l['space_name']} ({l['landlord']})")
            print(f"       rent ${l['monthly_rent']:,.2f} due {l['next_due']}"
                  f"  ({int(days)} days out)")

    # --- the squeeze, spelled out
    print("\n" + "=" * 72)
    print("CASH PICTURE")
    print("=" * 72)
    balance = cash["balance"]
    obligations = []
    for inv in conn.execute("SELECT * FROM invoices WHERE status='open'"):
        obligations.append((f"invoice {inv['id']} ({inv['due_date']})", inv["amount"]))
    for l in conn.execute("SELECT * FROM leases"):
        obligations.append((f"rent lease {l['id']} ({l['next_due']})", l["monthly_rent"]))

    total = sum(a for _, a in obligations)
    print(f"  starting cash               ${balance:>10,.2f}")
    for label, amt in obligations:
        print(f"  less {label:<24} ${amt:>10,.2f}")
    print(f"  {'-' * 44}")
    print(f"  remaining after obligations ${balance - total:>10,.2f}")
    print(f"\n  Total obligations ${total:,.2f} vs cash ${balance:,.2f} -> "
          f"{'COVERED' if total <= balance else 'SHORTFALL'}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--original", action="store_true",
                    help="inspect the pristine original instead of the working copy")
    ap.add_argument("--tickets", action="store_true",
                    help="show only the open-ticket linkage view")
    args = ap.parse_args()

    path = ORIGINAL_DB if args.original else WORKING_DB
    print(f"# {path.name}\n")

    with connect(path) as conn:
        if args.tickets:
            show_ticket_links(conn)
        else:
            show_schema(conn)
            print("\n")
            show_contents(conn)
            print("\n")
            show_ticket_links(conn)


if __name__ == "__main__":
    main()
