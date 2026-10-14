"""Campus Customs MCP server.

Exposes the shop's database to the agent team as tools. Every agent in this
homework — boss, inventory, accounting, facilities, customer service — calls
these tools rather than touching SQL directly.

Reads and writes `data/campus_customs_new.db` (the working copy). The pristine
`data/campus_customs.db` is never touched.

Run with:  python mcp_server/server.py        (stdio transport)

DESIGN RULE: these tools never invent data. Every number returned is either
read straight from a table or computed from values in the tables (for example,
an arrival date is the shop date plus the vendor's recorded `lead_days`).
When a tool cannot find something, it says so in an `error` field instead of
guessing a plausible answer.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# Allow `python mcp_server/server.py` to find the app package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastmcp import FastMCP

from app import db, policy
from app.payloads import payload_ref
from app.config import APPROVER_NAME

mcp = FastMCP("campus-customs")


# ---------------------------------------------------------------------------
# Tool 1 — stock lookup                       (tickets 101 and 103)
# ---------------------------------------------------------------------------
@mcp.tool()
def check_stock(sku: str, size: str, qty_wanted: int = 1) -> dict[str, Any]:
    """Check units on hand for one SKU in one size, and whether an order can be filled.

    Stock is tracked per (sku, size) pair, so the size is required: a SKU can be
    well stocked overall while the requested size is at zero.

    Args:
        sku: Product code, e.g. "CC-TEE-WHITE".
        size: Size code, e.g. "S", "M", "L", "XL", "OS".
        qty_wanted: Units the customer is asking for. Defaults to 1.

    Returns on-hand quantity, the shortfall if any, and the product's cost and
    list price, so the caller can price the order without a second call.
    """
    row = db.query_one(
        "SELECT sku, name, size, qty, location FROM inventory WHERE sku=? AND size=?",
        (sku, size),
    )
    if row is None:
        # Report what sizes DO exist rather than silently returning zero -- a
        # missing row and a row with qty 0 are different facts.
        known = db.query("SELECT size, qty FROM inventory WHERE sku=? ORDER BY size", (sku,))
        if not known:
            return {"error": f"No inventory record for SKU {sku!r}.", "sku": sku}
        return {
            "error": f"No inventory record for SKU {sku!r} in size {size!r}.",
            "sku": sku,
            "sizes_on_file": {k["size"]: k["qty"] for k in known},
        }

    price = db.query_one(
        "SELECT unit_cost, list_price FROM pricing WHERE sku=?", (sku,)
    )

    on_hand = row["qty"]
    shortfall = max(0, qty_wanted - on_hand)

    result: dict[str, Any] = {
        "sku": sku,
        "name": row["name"],
        "size": size,
        "qty_on_hand": on_hand,
        "qty_wanted": qty_wanted,
        "shortfall": shortfall,
        "can_fill_now": shortfall == 0,
        "location": row["location"],
    }
    if price:
        result["unit_cost"] = price["unit_cost"]
        result["list_price"] = price["list_price"]
        result["line_total_at_list"] = round(price["list_price"] * qty_wanted, 2)
    else:
        result["pricing_note"] = f"No pricing row for {sku!r}."
    return result


# ---------------------------------------------------------------------------
# Tool 2 — restock sourcing                   (ticket 101, and 103's shortfall)
# ---------------------------------------------------------------------------
@mcp.tool()
def find_restock_vendor(sku: str, qty: int = 1) -> dict[str, Any]:
    """Find which vendors can resupply a SKU, how fast, and whether they will ship.

    A vendor is only usable if BOTH tests pass:
      1. their `specialty` covers the product category, and
      2. they have no open unpaid invoice with us — a vendor will not ship new
         product while one stands.

    Args:
        sku: Product code to resupply.
        qty: Units needed, used to cost the restock.

    Returns each candidate vendor with lead time, the arrival date implied by
    that lead time, any blocking invoice, and the cost to restock.
    """
    price = db.query_one("SELECT unit_cost FROM pricing WHERE sku=?", (sku,))
    item = db.query_one("SELECT name FROM inventory WHERE sku=? LIMIT 1", (sku,))
    if price is None and item is None:
        return {"error": f"Unknown SKU {sku!r}; not in pricing or inventory.", "sku": sku}

    name = item["name"] if item else sku
    today = db.shop_today()

    # Category is inferred from the SKU pattern and the product name only --
    # both are data in the database, not outside knowledge.
    category = _category_for(sku, name)

    candidates = []
    for v in db.query("SELECT id, name, specialty, lead_days FROM vendors ORDER BY id"):
        if not _specialty_matches(v["specialty"], category):
            continue

        open_invoices = db.query(
            "SELECT id, amount, due_date, status, description FROM invoices "
            "WHERE vendor_id=? AND status='open' ORDER BY due_date",
            (v["id"],),
        )
        for inv in open_invoices:
            inv["is_overdue"] = db.is_overdue(inv["due_date"])

        blocked = bool(open_invoices)
        candidates.append(
            {
                "vendor_id": v["id"],
                "vendor_name": v["name"],
                "specialty": v["specialty"],
                "lead_days": v["lead_days"],
                "will_ship": not blocked,
                "blocked_by_open_invoices": open_invoices,
                "amount_to_unblock": round(sum(i["amount"] for i in open_invoices), 2)
                if blocked
                else 0.0,
                # Arrival assumes an order placed today that is not blocked.
                "earliest_arrival_if_ordered_today": db.add_days(today, v["lead_days"]),
            }
        )

    unit_cost = price["unit_cost"] if price else None
    return {
        "sku": sku,
        "product_name": name,
        "inferred_category": category,
        "qty": qty,
        "unit_cost": unit_cost,
        "restock_cost": round(unit_cost * qty, 2) if unit_cost is not None else None,
        "shop_date": today,
        "vendors": candidates,
        "any_vendor_can_ship": any(c["will_ship"] for c in candidates),
        "note": (
            "No vendor whose specialty covers this product can ship right now."
            if candidates and not any(c["will_ship"] for c in candidates)
            else None
        ),
    }


def _category_for(sku: str, name: str) -> str:
    """Infer a product category from the SKU code and product name."""
    text = f"{sku} {name}".lower()
    if "tee" in text or "hood" in text or "shirt" in text:
        return "apparel"
    if "mug" in text or "hat" in text or "cap" in text:
        return "small goods"
    return "general"


def _specialty_matches(specialty: str, category: str) -> bool:
    """Does a vendor's recorded specialty cover this category?"""
    s = specialty.lower()
    if category == "apparel":
        return "apparel" in s or "print" in s or "reprint" in s
    if category == "small goods":
        return "mug" in s or "small goods" in s or "gift" in s
    # A courier ships anything but manufactures nothing; it is not a source
    # for new product, so it is not offered as a restock candidate.
    return False


# ---------------------------------------------------------------------------
# Tool 3 — cash and obligations               (ticket 102, and the whole squeeze)
# ---------------------------------------------------------------------------
@mcp.tool()
def get_cash_position() -> dict[str, Any]:
    """Report cash on hand and every obligation owed, measured against the shop date.

    Gathers the checking balance, all open vendor invoices, and all lease rent
    due, flags which are overdue against `desk.date_today`, and totals what the
    shop owes. No revenue is modeled in this shop, so the balance only ever
    falls; this is the figure every spending decision must be checked against.
    """
    today = db.shop_today()
    account = db.query_one("SELECT name, balance, date FROM cash_accounts LIMIT 1")
    if account is None:
        return {"error": "No cash account on file."}

    obligations: list[dict[str, Any]] = []

    for inv in db.query(
        "SELECT i.id, i.amount, i.due_date, i.description, i.vendor_id, v.name AS vendor_name "
        "FROM invoices i LEFT JOIN vendors v ON v.id = i.vendor_id "
        "WHERE i.status='open' ORDER BY i.due_date"
    ):
        obligations.append(
            {
                "kind": "vendor_invoice",
                "ref_id": inv["id"],
                "description": inv["description"],
                "owed_to": inv["vendor_name"],
                "amount": inv["amount"],
                "due_date": inv["due_date"],
                "days_until_due": db.days_until(inv["due_date"]),
                "is_overdue": db.is_overdue(inv["due_date"]),
            }
        )

    for lease in db.query(
        "SELECT id, space_name, landlord, monthly_rent, next_due FROM leases ORDER BY next_due"
    ):
        obligations.append(
            {
                "kind": "rent",
                "ref_id": lease["id"],
                "description": f"Rent for {lease['space_name']}",
                "owed_to": lease["landlord"],
                "amount": lease["monthly_rent"],
                "due_date": lease["next_due"],
                "days_until_due": db.days_until(lease["next_due"]),
                "is_overdue": db.is_overdue(lease["next_due"]),
            }
        )

    obligations.sort(key=lambda o: o["due_date"])
    total_owed = round(sum(o["amount"] for o in obligations), 2)
    balance = account["balance"]

    paid = db.query(
        "SELECT id, kind, ref_id, amount, paid_at, approved_by FROM payments ORDER BY id"
    )

    return {
        "shop_date": today,
        "account": account["name"],
        "balance": balance,
        "obligations": obligations,
        "total_owed": total_owed,
        "remaining_if_all_paid": round(balance - total_owed, 2),
        "can_cover_all_obligations": total_owed <= balance,
        "overdue_count": sum(1 for o in obligations if o["is_overdue"]),
        "payments_made": paid,
        "note": "No revenue is modeled; this balance only decreases.",
    }


# ===========================================================================
# Problem 5 additions
#
# The three tools above answer questions. The tools below let the team work a
# ticket to a conclusion: read the board, judge a discount, park a request for
# a human, move money once a human has said yes, and write drafts that never
# leave the board.
#
# SAFETY MODEL for everything past this point:
#   * No tool moves money without an `approval_id` naming an approvals row
#     that a human has already set to 'approved'.
#   * No tool can drive the balance negative. It refuses instead.
#   * Nothing is ever sent anywhere. Drafts are rows in a table.
#   * Paid things cannot be paid twice.
# These are enforced here in code, not asked for in a prompt, because a prompt
# is advice and this is a rule.
# ===========================================================================


# ---------------------------------------------------------------------------
# Tool 4 — read the board
# ---------------------------------------------------------------------------
@mcp.tool()
def list_open_tickets() -> dict[str, Any]:
    """List every ticket still open, with the links that say who should handle it.

    The boss agent calls this first. Which foreign key is populated is the
    routing signal: `sku` means a product question, `lease_id` means
    facilities, `invoice_id` means an unpaid bill is entangled with it.
    """
    rows = db.query(
        "SELECT id, type, requester, subject, sku, size, qty, lease_id, invoice_id, "
        "status, notes, assignee FROM tickets WHERE status='open' ORDER BY id"
    )
    for r in rows:
        r["links"] = [
            k for k in ("sku", "lease_id", "invoice_id") if r.get(k) not in (None, "")
        ]
    return {
        "shop_date": db.shop_today(),
        "open_count": len(rows),
        "tickets": rows,
    }


# ---------------------------------------------------------------------------
# Tool 5 — one ticket, fully resolved against every table it touches
# ---------------------------------------------------------------------------
@mcp.tool()
def get_ticket(ticket_id: int) -> dict[str, Any]:
    """Load one ticket together with the inventory, pricing, lease, invoice and
    vendor rows it references.

    Saves an agent four follow-up calls, and guarantees the linked rows are the
    ones the ticket actually points at rather than ones the model guessed.
    """
    t = db.query_one("SELECT * FROM tickets WHERE id=?", (ticket_id,))
    if t is None:
        return {"error": f"No ticket with id {ticket_id}."}

    out: dict[str, Any] = {"shop_date": db.shop_today(), "ticket": t}

    if t.get("sku"):
        out["pricing"] = db.query_one(
            "SELECT sku, unit_cost, list_price FROM pricing WHERE sku=?", (t["sku"],)
        )
        out["inventory_all_sizes"] = db.query(
            "SELECT sku, name, size, qty, location FROM inventory WHERE sku=? ORDER BY size",
            (t["sku"],),
        )
        if t.get("size"):
            row = db.query_one(
                "SELECT qty FROM inventory WHERE sku=? AND size=?", (t["sku"], t["size"])
            )
            on_hand = row["qty"] if row else 0
            want = t.get("qty") or 0
            out["requested_size_position"] = {
                "size": t["size"],
                "qty_on_hand": on_hand,
                "qty_wanted": want,
                "shortfall": max(0, want - on_hand),
            }

    if t.get("lease_id"):
        lease = db.query_one("SELECT * FROM leases WHERE id=?", (t["lease_id"],))
        if lease:
            lease["days_until_due"] = db.days_until(lease["next_due"])
            lease["is_overdue"] = db.is_overdue(lease["next_due"])
        out["lease"] = lease

    if t.get("invoice_id"):
        inv = db.query_one(
            "SELECT i.*, v.name AS vendor_name, v.lead_days, v.specialty "
            "FROM invoices i LEFT JOIN vendors v ON v.id=i.vendor_id WHERE i.id=?",
            (t["invoice_id"],),
        )
        if inv:
            inv["days_until_due"] = db.days_until(inv["due_date"])
            inv["is_overdue"] = db.is_overdue(inv["due_date"])
        out["invoice"] = inv

    out["approvals"] = db.query(
        "SELECT id, kind, summary, amount, status, requested_by, decided_by "
        "FROM approvals WHERE ticket_id=? ORDER BY id",
        (ticket_id,),
    )
    out["drafts"] = db.query(
        "SELECT id, audience, recipient, subject, status FROM drafts WHERE ticket_id=? ORDER BY id",
        (ticket_id,),
    )
    return out


# ---------------------------------------------------------------------------
# Tool 6 — lease detail                                        (facilities)
# ---------------------------------------------------------------------------
@mcp.tool()
def get_lease(lease_id: int) -> dict[str, Any]:
    """Full lease terms with the rent due date measured against the shop date.

    Rent is the one obligation with no invoice row — it lives only on `leases`,
    so the facilities agent needs a tool that reads that table directly.
    """
    lease = db.query_one("SELECT * FROM leases WHERE id=?", (lease_id,))
    if lease is None:
        return {"error": f"No lease with id {lease_id}."}

    paid = db.query(
        "SELECT id, amount, paid_at, approved_by FROM payments "
        "WHERE kind='rent' AND ref_id=? ORDER BY id",
        (lease_id,),
    )
    lease["days_until_due"] = db.days_until(lease["next_due"])
    lease["is_overdue"] = db.is_overdue(lease["next_due"])
    lease["shop_date"] = db.shop_today()
    lease["rent_payments_recorded"] = paid
    lease["already_paid_for_this_cycle"] = bool(paid)
    return lease


# ---------------------------------------------------------------------------
# Tool 7 — discount arithmetic against written policy        (ticket 103)
# ---------------------------------------------------------------------------
@mcp.tool()
def evaluate_discount(sku: str, qty: int, proposed_unit_price: float) -> dict[str, Any]:
    """Test a proposed discounted price against the shop's margin floor.

    Does the arithmetic in code so the answer cannot drift: gross margin is
    (price - cost) / price. The policy floor and the bulk-order minimum come
    from `app/policy.py`, so an agent quotes a written rule instead of
    inventing one.

    Args:
        sku: Product being discounted.
        qty: Units in the proposed order.
        proposed_unit_price: The per-unit price being asked for.
    """
    price = db.query_one("SELECT unit_cost, list_price FROM pricing WHERE sku=?", (sku,))
    if price is None:
        return {"error": f"No pricing row for SKU {sku!r}.", "sku": sku}
    if proposed_unit_price <= 0:
        return {"error": "proposed_unit_price must be greater than zero."}

    cost = price["unit_cost"]
    lst = price["list_price"]
    margin = (proposed_unit_price - cost) / proposed_unit_price
    floor_price = cost / (1 - policy.MIN_GROSS_MARGIN)

    meets_margin = margin >= policy.MIN_GROSS_MARGIN
    meets_qty = qty >= policy.BULK_DISCOUNT_MIN_QTY

    return {
        "sku": sku,
        "qty": qty,
        "unit_cost": cost,
        "list_price": lst,
        "proposed_unit_price": round(proposed_unit_price, 2),
        "gross_margin_at_proposed": round(margin, 4),
        "margin_floor": policy.MIN_GROSS_MARGIN,
        "meets_margin_floor": meets_margin,
        "lowest_price_meeting_floor": round(floor_price, 2),
        "discount_off_list": round(1 - (proposed_unit_price / lst), 4),
        "bulk_minimum_qty": policy.BULK_DISCOUNT_MIN_QTY,
        "meets_bulk_minimum": meets_qty,
        "order_total_at_proposed": round(proposed_unit_price * qty, 2),
        "order_total_at_list": round(lst * qty, 2),
        "margin_given_away": round((lst - proposed_unit_price) * qty, 2),
        "acceptable_under_policy": meets_margin and meets_qty,
        "requires_human_approval": policy.DISCOUNTS_NEED_APPROVAL,
        "note": (
            "Policy satisfied, but a discount is still a human decision."
            if meets_margin and meets_qty
            else "Below the margin floor or under the bulk minimum. Decline or counter at "
            f"${floor_price:,.2f}/unit."
        ),
    }


# ---------------------------------------------------------------------------
# Tool 8 — the approval queue (write)
# ---------------------------------------------------------------------------
@mcp.tool()
def request_approval(
    ticket_id: int,
    kind: str,
    summary: str,
    rationale: str,
    requested_by: str,
    amount: float | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Park a request for a human and stop. This is how an agent asks permission.

    No agent may approve anything, including its own request. The row lands as
    'pending' and only a human decision moves it on.

    Args:
        ticket_id: Ticket this request belongs to.
        kind: One of 'payment', 'purchase_order', 'discount'.
        summary: One line a human can decide on without reading the thread.
        rationale: Which policy rule or database fact drives the request.
        requested_by: The agent asking.
        amount: Money involved, if any.
        payload: Exact arguments to replay when approved, e.g.
            {"tool": "pay_invoice", "invoice_id": 501}.
    """
    allowed = {"payment", "purchase_order", "discount"}
    if kind not in allowed:
        return {"error": f"kind must be one of {sorted(allowed)}; got {kind!r}."}
    if not db.query_one("SELECT id FROM tickets WHERE id=?", (ticket_id,)):
        return {"error": f"No ticket with id {ticket_id}."}

    with db.connect(write=True) as conn:
        cur = conn.execute(
            "INSERT INTO approvals (ticket_id, kind, summary, payload, rationale, "
            "amount, requested_by, status) VALUES (?,?,?,?,?,?,?,'pending')",
            (
                ticket_id,
                kind,
                summary,
                json.dumps(payload or {}),
                rationale,
                amount,
                requested_by,
            ),
        )
        approval_id = cur.lastrowid

    return {
        "approval_id": approval_id,
        "status": "pending",
        "ticket_id": ticket_id,
        "kind": kind,
        "amount": amount,
        "note": (
            "Parked for human approval. Do NOT proceed as though this were granted; "
            "report that the ticket is waiting on a decision."
        ),
    }


@mcp.tool()
def list_approvals(status: str | None = None) -> dict[str, Any]:
    """List approval requests, optionally filtered by status.

    Lets an agent check whether a human has already decided something before
    asking again, and lets the boss see what a run is blocked on.

    Args:
        status: 'pending', 'approved' or 'rejected'. Omit for all.
    """
    if status:
        rows = db.query("SELECT * FROM approvals WHERE status=? ORDER BY id", (status,))
    else:
        rows = db.query("SELECT * FROM approvals ORDER BY id")
    return {"count": len(rows), "approvals": rows}


# ---------------------------------------------------------------------------
# Payment helpers — the guardrail every money tool shares
# ---------------------------------------------------------------------------
def _check_approval(approval_id: int, kind: str, ref_id: int) -> dict[str, Any] | None:
    """Return an error dict if this approval does not authorise this payment."""
    a = db.query_one("SELECT * FROM approvals WHERE id=?", (approval_id,))
    if a is None:
        return {"error": f"No approval with id {approval_id}. Call request_approval first."}
    if a["status"] != "approved":
        return {
            "error": f"Approval {approval_id} is '{a['status']}', not 'approved'.",
            "refused": True,
            "note": "A human has not authorised this. Nothing was paid.",
        }

    payload = json.loads(a["payload"] or "{}")
    declared = payload_ref(payload)

    # No resolvable reference means the approval's scope cannot be verified at
    # all. Refuse rather than treat "unknown" as "anything" -- an unscoped
    # approval would otherwise be replayable against any obligation.
    if declared is None:
        return {
            "error": (
                f"Approval {approval_id} has no obligation id in its payload "
                f"({sorted(payload)}), so its scope cannot be checked."
            ),
            "refused": True,
            "note": "Re-raise the request with ref_id set to the id being paid.",
        }

    # The approval must point at THIS obligation -- otherwise an approval for a
    # small invoice could be replayed to pay a large one.
    if declared != ref_id:
        return {
            "error": (
                f"Approval {approval_id} authorises {kind} ref_id={declared}, "
                f"not ref_id={ref_id}."
            ),
            "refused": True,
        }
    if not a["decided_by"]:
        return {"error": f"Approval {approval_id} has no human decider recorded.", "refused": True}
    return None


def _spend_guard(conn, amount: float, *, discretionary: bool) -> dict[str, Any] | None:
    """Refuse a spend that would break the cash rules. Returns an error dict or None.

    Two different floors, deliberately:
      * Contractual obligations (rent, an invoice we already owe) may spend down
        to zero but never below. Refusing to pay rent to protect a reserve would
        cost the shop its premises, which is worse than a thin balance.
      * Discretionary spend (a new purchase order) must leave the reserve intact.
    """
    row = conn.execute("SELECT balance FROM cash_accounts LIMIT 1").fetchone()
    balance = row["balance"]
    after = round(balance - amount, 2)

    if after < 0:
        return {
            "refused": True,
            "error": "REFUSED: this payment would overdraw the account.",
            "balance": balance,
            "amount": amount,
            "balance_after_would_be": after,
            "rule": "Negative balances are forbidden (hard invariant).",
        }
    if discretionary and after < policy.CASH_RESERVE:
        return {
            "refused": True,
            "error": "REFUSED: discretionary spend would break the cash reserve.",
            "balance": balance,
            "amount": amount,
            "balance_after_would_be": after,
            "cash_reserve": policy.CASH_RESERVE,
            "rule": f"Discretionary spend must leave at least ${policy.CASH_RESERVE:,.2f}.",
        }
    return None


# ---------------------------------------------------------------------------
# Tool 9 — pay a vendor invoice (write, human-gated)          (unblocks 101)
# ---------------------------------------------------------------------------
@mcp.tool()
def pay_invoice(invoice_id: int, approval_id: int) -> dict[str, Any]:
    """Pay an open vendor invoice. Requires an approved approval row.

    Refuses rather than overdrawing, refuses without human approval, and
    refuses to pay the same invoice twice. On success it debits cash, marks the
    invoice paid, and writes an audit row to `payments` naming the human who
    approved it.

    Args:
        invoice_id: The invoice to settle.
        approval_id: An approvals row a human has set to 'approved'.
    """
    inv = db.query_one("SELECT * FROM invoices WHERE id=?", (invoice_id,))
    if inv is None:
        return {"error": f"No invoice with id {invoice_id}."}
    if inv["status"] != "open":
        return {
            "refused": True,
            "error": f"Invoice {invoice_id} is already '{inv['status']}'. Not paying twice.",
        }

    bad = _check_approval(approval_id, "payment", invoice_id)
    if bad:
        return bad

    approval = db.query_one("SELECT decided_by FROM approvals WHERE id=?", (approval_id,))
    amount = inv["amount"]
    today = db.shop_today()

    with db.connect(write=True) as conn:
        stop = _spend_guard(conn, amount, discretionary=False)
        if stop:
            return stop
        conn.execute(
            "UPDATE cash_accounts SET balance = ROUND(balance - ?, 2) WHERE name = "
            "(SELECT name FROM cash_accounts LIMIT 1)",
            (amount,),
        )
        conn.execute("UPDATE invoices SET status='paid' WHERE id=?", (invoice_id,))
        cur = conn.execute(
            "INSERT INTO payments (kind, ref_id, amount, account, paid_at, approved_by) "
            "VALUES ('invoice', ?, ?, (SELECT name FROM cash_accounts LIMIT 1), ?, ?)",
            (invoice_id, amount, today, approval["decided_by"]),
        )
        payment_id = cur.lastrowid
        new_balance = conn.execute(
            "SELECT balance FROM cash_accounts LIMIT 1"
        ).fetchone()["balance"]

    vendor = db.query_one("SELECT name FROM vendors WHERE id=?", (inv["vendor_id"],))
    return {
        "paid": True,
        "payment_id": payment_id,
        "invoice_id": invoice_id,
        "amount": amount,
        "vendor": vendor["name"] if vendor else None,
        "paid_at": today,
        "approved_by": approval["decided_by"],
        "new_balance": new_balance,
        "note": "Invoice settled. This vendor's shipping block is now clear.",
    }


# ---------------------------------------------------------------------------
# Tool 10 — pay rent (write, human-gated)                      (ticket 102)
# ---------------------------------------------------------------------------
@mcp.tool()
def pay_rent(lease_id: int, approval_id: int) -> dict[str, Any]:
    """Pay one month's rent on a lease. Requires an approved approval row.

    Rent has no invoice row, so it is paid straight off the lease. On success
    the lease's `next_due` advances one month, which is what stops the same
    month being paid twice.

    Args:
        lease_id: The lease to pay.
        approval_id: An approvals row a human has set to 'approved'.
    """
    lease = db.query_one("SELECT * FROM leases WHERE id=?", (lease_id,))
    if lease is None:
        return {"error": f"No lease with id {lease_id}."}

    bad = _check_approval(approval_id, "payment", lease_id)
    if bad:
        return bad

    due = lease["next_due"]
    already = db.query_one(
        "SELECT id FROM payments WHERE kind='rent' AND ref_id=? AND paid_at >= ? ",
        (lease_id, db.shop_today()),
    )
    if already:
        return {
            "refused": True,
            "error": f"Rent for lease {lease_id} already recorded (payment {already['id']}).",
        }

    approval = db.query_one("SELECT decided_by FROM approvals WHERE id=?", (approval_id,))
    amount = lease["monthly_rent"]
    today = db.shop_today()

    with db.connect(write=True) as conn:
        stop = _spend_guard(conn, amount, discretionary=False)
        if stop:
            return stop
        conn.execute(
            "UPDATE cash_accounts SET balance = ROUND(balance - ?, 2) WHERE name = "
            "(SELECT name FROM cash_accounts LIMIT 1)",
            (amount,),
        )
        cur = conn.execute(
            "INSERT INTO payments (kind, ref_id, amount, account, paid_at, approved_by) "
            "VALUES ('rent', ?, ?, (SELECT name FROM cash_accounts LIMIT 1), ?, ?)",
            (lease_id, amount, today, approval["decided_by"]),
        )
        payment_id = cur.lastrowid
        conn.execute(
            "UPDATE leases SET next_due=? WHERE id=?", (_add_one_month(due), lease_id)
        )
        new_balance = conn.execute(
            "SELECT balance FROM cash_accounts LIMIT 1"
        ).fetchone()["balance"]

    return {
        "paid": True,
        "payment_id": payment_id,
        "lease_id": lease_id,
        "space": lease["space_name"],
        "landlord": lease["landlord"],
        "amount": amount,
        "paid_for_due_date": due,
        "next_due_now": _add_one_month(due),
        "paid_at": today,
        "approved_by": approval["decided_by"],
        "new_balance": new_balance,
    }


def _add_one_month(iso_date: str) -> str:
    """Advance an ISO date by one calendar month, clamping to month length."""
    from datetime import date

    d = date.fromisoformat(iso_date)
    year, month = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    # Clamp: the 31st of a 30-day month becomes the 30th.
    for day in range(d.day, 27, -1):
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            continue
    return date(year, month, d.day).isoformat()


# ---------------------------------------------------------------------------
# Tool 11 — raise a purchase order (write, human-gated)
# ---------------------------------------------------------------------------
@mcp.tool()
def create_purchase_order(
    ticket_id: int,
    vendor_id: int,
    sku: str,
    size: str,
    qty: int,
    created_by: str,
) -> dict[str, Any]:
    """Raise a restock purchase order as a DRAFT. It commits no money yet.

    Costed from `pricing.unit_cost` and dated from the vendor's `lead_days`, so
    both numbers come from the database rather than the model. The order is
    checked against the cash reserve immediately: a PO the shop cannot fund is
    refused at the point it is raised, not discovered later.

    A draft PO still needs human approval before it becomes a commitment —
    call `request_approval` with kind='purchase_order' after this succeeds.

    Args:
        ticket_id: Ticket driving the restock.
        vendor_id: Vendor to order from.
        sku: Product code.
        size: Size code.
        qty: Units to order.
        created_by: The agent raising it.
    """
    if qty <= 0:
        return {"error": "qty must be greater than zero."}
    vendor = db.query_one("SELECT * FROM vendors WHERE id=?", (vendor_id,))
    if vendor is None:
        return {"error": f"No vendor with id {vendor_id}."}
    price = db.query_one("SELECT unit_cost FROM pricing WHERE sku=?", (sku,))
    if price is None:
        return {"error": f"No pricing row for SKU {sku!r}; cannot cost this order."}
    if not db.query_one("SELECT id FROM tickets WHERE id=?", (ticket_id,)):
        return {"error": f"No ticket with id {ticket_id}."}

    open_invoices = db.query(
        "SELECT id, amount, due_date FROM invoices WHERE vendor_id=? AND status='open'",
        (vendor_id,),
    )
    unit_cost = price["unit_cost"]
    total = round(unit_cost * qty, 2)
    today = db.shop_today()

    with db.connect(write=True) as conn:
        stop = _spend_guard(conn, total, discretionary=True)
        if stop:
            stop["note"] = (
                "Purchase order NOT created. Report the shortfall rather than "
                "raising an order the shop cannot fund."
            )
            return stop
        cur = conn.execute(
            "INSERT INTO purchase_orders (ticket_id, vendor_id, sku, size, qty, unit_cost, "
            "total_cost, status, expected_date) VALUES (?,?,?,?,?,?,?,'draft',?)",
            (
                ticket_id,
                vendor_id,
                sku,
                size,
                qty,
                unit_cost,
                total,
                db.add_days(today, vendor["lead_days"]),
            ),
        )
        po_id = cur.lastrowid

    return {
        "purchase_order_id": po_id,
        "status": "draft",
        "vendor": vendor["name"],
        "sku": sku,
        "size": size,
        "qty": qty,
        "unit_cost": unit_cost,
        "total_cost": total,
        "expected_date": db.add_days(today, vendor["lead_days"]),
        "vendor_will_ship": not open_invoices,
        "blocking_invoices": open_invoices,
        "created_by": created_by,
        "requires_human_approval": policy.PURCHASE_ORDERS_NEED_APPROVAL,
        "note": (
            "Draft only. Call request_approval(kind='purchase_order') next."
            + (
                " WARNING: this vendor has an open invoice and will not ship until it is paid."
                if open_invoices
                else ""
            )
        ),
    }


# ---------------------------------------------------------------------------
# Tool 12 — write a draft message (write, never sends)
# ---------------------------------------------------------------------------
@mcp.tool()
def save_draft_message(
    ticket_id: int,
    audience: str,
    recipient: str,
    subject: str,
    body: str,
    created_by: str,
) -> dict[str, Any]:
    """Save a message as a DRAFT on the board. Nothing is ever sent.

    There is no send tool in this server and the `drafts` table has no 'sent'
    status, so "drafts stay on the board" is a property of the schema rather
    than a promise in a prompt.

    Args:
        ticket_id: Ticket the message belongs to.
        audience: 'customer', 'vendor' or 'landlord'.
        recipient: Who it is addressed to.
        subject: Subject line.
        body: Message text.
        created_by: The agent writing it.
    """
    allowed = {"customer", "vendor", "landlord"}
    if audience not in allowed:
        return {"error": f"audience must be one of {sorted(allowed)}; got {audience!r}."}
    if not db.query_one("SELECT id FROM tickets WHERE id=?", (ticket_id,)):
        return {"error": f"No ticket with id {ticket_id}."}
    if not body.strip():
        return {"error": "body is empty."}

    with db.connect(write=True) as conn:
        cur = conn.execute(
            "INSERT INTO drafts (ticket_id, audience, recipient, subject, body, status, created_by) "
            "VALUES (?,?,?,?,?,'draft',?)",
            (ticket_id, audience, recipient, subject, body, created_by),
        )
        draft_id = cur.lastrowid

    return {
        "draft_id": draft_id,
        "ticket_id": ticket_id,
        "audience": audience,
        "recipient": recipient,
        "subject": subject,
        "status": "draft",
        "sent": False,
        "note": "Saved to the board. This server has no ability to send anything.",
    }


# ---------------------------------------------------------------------------
# Tool 13 — close out a ticket (write)
# ---------------------------------------------------------------------------
@mcp.tool()
def update_ticket(
    ticket_id: int,
    status: str | None = None,
    assignee: str | None = None,
    resolution: str | None = None,
) -> dict[str, Any]:
    """Record who owned a ticket and how it ended.

    Allowed statuses are 'open', 'waiting_approval', 'resolved' and 'declined'.
    A ticket cannot be marked 'resolved' while it still has a pending approval —
    that would hide a decision a human has not made yet.

    Args:
        ticket_id: Ticket to update.
        status: New status, if changing.
        assignee: Agent that owns it.
        resolution: One or two sentences on how it ended.
    """
    t = db.query_one("SELECT * FROM tickets WHERE id=?", (ticket_id,))
    if t is None:
        return {"error": f"No ticket with id {ticket_id}."}

    allowed = {"open", "waiting_approval", "resolved", "declined"}
    if status is not None and status not in allowed:
        return {"error": f"status must be one of {sorted(allowed)}; got {status!r}."}

    pending = db.query(
        "SELECT id FROM approvals WHERE ticket_id=? AND status='pending'", (ticket_id,)
    )

    if status == "resolved" and pending:
        return {
            "refused": True,
            "error": (
                f"Ticket {ticket_id} has pending approval(s) "
                f"{[p['id'] for p in pending]}. Use status='waiting_approval'."
            ),
        }

    # The mirror of the rule above, and it matters just as much. A ticket set to
    # 'waiting_approval' with nothing actually pending claims to be blocked on a
    # human who has not been asked anything -- so no approval can ever clear it
    # and the ticket is stranded on the board forever. Either raise the request
    # or reach a verdict.
    if status == "waiting_approval" and not pending:
        return {
            "refused": True,
            "error": (
                f"Ticket {ticket_id} has no pending approvals, so it cannot be "
                "'waiting_approval' -- nothing would ever clear it."
            ),
            "note": (
                "Either call request_approval first, or close the ticket: "
                "'resolved' if the shop acted, 'declined' if it cannot or should not."
            ),
        }

    sets, params = [], []
    if status is not None:
        sets.append("status=?")
        params.append(status)
        if status in {"resolved", "declined"}:
            sets.append("resolved_at=?")
            params.append(db.shop_today())
    if assignee is not None:
        sets.append("assignee=?")
        params.append(assignee)
    if resolution is not None:
        sets.append("resolution=?")
        params.append(resolution)
    if not sets:
        return {"error": "Nothing to update."}

    params.append(ticket_id)
    with db.connect(write=True) as conn:
        conn.execute(f"UPDATE tickets SET {', '.join(sets)} WHERE id=?", tuple(params))

    return {"updated": True, "ticket": db.query_one("SELECT * FROM tickets WHERE id=?", (ticket_id,))}


# ===========================================================================
# Problem 7 additions — the human/dashboard side
#
# These two are NOT on any agent's allowlist (see backend/mcp_client.py). They
# exist for the FastAPI routes a human drives, and they live here rather than as
# SQL in the backend so that every write to shop state still goes through one
# tool layer with one set of rules.
# ===========================================================================


@mcp.tool()
def list_tickets(status: str | None = None) -> dict[str, Any]:
    """List tickets in any state, with their resolution if they have one.

    `list_open_tickets` deliberately returns only the work queue, which is the
    right view for the boss agent. A dashboard needs the whole board, including
    what has already been resolved or declined.

    Args:
        status: Filter to one status. Omit for every ticket.
    """
    sql = (
        "SELECT id, type, requester, subject, sku, size, qty, lease_id, invoice_id, "
        "status, notes, assignee, resolution, resolved_at FROM tickets"
    )
    rows = db.query(sql + " WHERE status=? ORDER BY id", (status,)) if status else db.query(
        sql + " ORDER BY id"
    )

    for r in rows:
        r["is_open"] = r["status"] == "open"
        r["is_resolved"] = r["status"] in {"resolved", "declined"}
        r["pending_approvals"] = [
            a["id"]
            for a in db.query(
                "SELECT id FROM approvals WHERE ticket_id=? AND status='pending'", (r["id"],)
            )
        ]

    return {
        "shop_date": db.shop_today(),
        "count": len(rows),
        "tickets": rows,
    }


@mcp.tool()
def confirm_purchase_order(purchase_order_id: int, approval_id: int) -> dict[str, Any]:
    """Turn an approved draft purchase order into a placed order.

    This is the "approve a purchase" half of the human decision. It commits the
    shop to the order but moves no cash — in this model a PO is a commitment and
    payment happens separately against the resulting invoice, so there is no
    debit here to guard.

    It still refuses without a human-approved approval row, and refuses to place
    the same order twice.

    Args:
        purchase_order_id: The draft PO to place.
        approval_id: An approvals row a human has set to 'approved'.
    """
    po = db.query_one("SELECT * FROM purchase_orders WHERE id=?", (purchase_order_id,))
    if po is None:
        return {"error": f"No purchase order with id {purchase_order_id}."}
    if po["status"] != "draft":
        return {
            "refused": True,
            "error": f"Purchase order {purchase_order_id} is already '{po['status']}'.",
        }

    bad = _check_approval(approval_id, "purchase_order", purchase_order_id)
    if bad:
        return bad

    with db.connect(write=True) as conn:
        conn.execute(
            "UPDATE purchase_orders SET status='ordered' WHERE id=?", (purchase_order_id,)
        )

    vendor = db.query_one("SELECT name FROM vendors WHERE id=?", (po["vendor_id"],))
    return {
        "ordered": True,
        "purchase_order_id": purchase_order_id,
        "vendor": vendor["name"] if vendor else None,
        "sku": po["sku"],
        "size": po["size"],
        "qty": po["qty"],
        "total_cost": po["total_cost"],
        "expected_date": po["expected_date"],
        "note": "Order placed. No cash moved — a PO is a commitment, not a payment.",
    }


# ---------------------------------------------------------------------------
# Tool 14 — the written policy the agents must cite
# ---------------------------------------------------------------------------
@mcp.tool()
def get_shop_policy() -> dict[str, Any]:
    """Return the shop's written policy numbers and hard rules.

    Agents cite these rather than inventing thresholds. Served from the same
    `app/policy.py` the tools enforce, so what an agent is told and what the
    tools do can never drift apart.
    """
    return {
        "min_gross_margin": policy.MIN_GROSS_MARGIN,
        "bulk_discount_min_qty": policy.BULK_DISCOUNT_MIN_QTY,
        "cash_reserve": policy.CASH_RESERVE,
        "cash_reserve_applies_to": "discretionary spend only (purchase orders)",
        "obligations_may_spend_to_zero": True,
        "allow_negative_balance": policy.ALLOW_NEGATIVE_BALANCE,
        "payment_priority": list(policy.PAYMENT_PRIORITY),
        "purchase_orders_need_approval": policy.PURCHASE_ORDERS_NEED_APPROVAL,
        "discounts_need_approval": policy.DISCOUNTS_NEED_APPROVAL,
        "every_payment_needs_approval": True,
        "approver": APPROVER_NAME,
        "allow_outbound_send": policy.ALLOW_OUTBOUND_SEND,
        "vendor_blocked_by_open_invoice": policy.VENDOR_BLOCKED_BY_OPEN_INVOICE,
        "policy_text": policy.as_prompt_text(),
    }


if __name__ == "__main__":
    mcp.run()
