"""Shop policy — the written rules the agents treat as ground truth.

WHY THIS FILE EXISTS
--------------------
Several decisions in this assignment (what discount is acceptable, how much
cash to keep in reserve, what gets paid first) are not derivable from the
database. Rather than let each agent invent a number on the fly, the shop's
policy is written down once, here, and the agents must read it and cite it.
That makes every decision auditable and reproducible instead of arbitrary.

STATUS OF THESE NUMBERS
-----------------------
Values marked PROVISIONAL were chosen by us as defensible defaults because
the assignment had not specified them yet. If a later problem states the real
policy, change the constant here and the whole agent team follows -- no other
file needs to be touched.
"""

from dataclasses import dataclass

# --- Discounting -----------------------------------------------------------
# PROVISIONAL. Gross margin floor on any discounted sale, as a fraction of the
# discounted unit price. At cost $22 / list $58 the hoodie carries a 62% margin
# at list, so a 40% floor leaves real room to negotiate while refusing to sell
# near or below cost.
MIN_GROSS_MARGIN = 0.40

# PROVISIONAL. Orders at or above this many units may be considered for a bulk
# discount at all. Below it, the answer is list price.
BULK_DISCOUNT_MIN_QTY = 12

# --- Cash ------------------------------------------------------------------
# PROVISIONAL. Operating floor for DISCRETIONARY spend only. No revenue is
# modeled in this assignment, so the balance only ever falls -- a reserve keeps
# the shop from spending itself to exactly zero on a single discretionary
# purchase order.
CASH_RESERVE = 250.00

# WHICH SPEND THE RESERVE BINDS -- resolved in Problem 5.
#
# The reserve and the board are in direct tension. Rent ($2,400) plus the open
# invoice ($840) is $3,240 against $3,400 cash, leaving $160 -- below the $250
# reserve. Read naively, the reserve would forbid paying the second obligation.
#
# That reading is wrong, and taking it would have the agents refuse rent to
# protect a cash cushion, which loses the premises. So the reserve binds
# DISCRETIONARY spend (new purchase orders) and not CONTRACTUAL obligations
# (rent, an invoice already owed). Money the shop already owes may be paid down
# to zero -- never below it.
#
# Enforced in `mcp_server/server.py::_spend_guard` via its `discretionary` flag,
# so this is a rule in code rather than a sentence in a prompt.
RESERVE_BINDS_DISCRETIONARY_ONLY = True

# Hard invariant, NOT provisional: the assignment forbids negative balances.
# The pay tool must refuse rather than overdraw, always.
ALLOW_NEGATIVE_BALANCE = False

# --- Payment priority ------------------------------------------------------
# PROVISIONAL. When cash cannot cover everything, obligations are settled in
# this order. Rent ranks first: losing the premises ends the business, whereas
# a late vendor invoice costs goodwill and blocks shipments. Within a tier,
# the earlier due_date wins.
PAYMENT_PRIORITY = ("rent", "vendor_invoice", "purchase_order")

# --- Approval --------------------------------------------------------------
# Hard rule from the assignment: a human approves anything that moves money.
# Set to 0.00 so that every payment, without exception, goes to the queue.
APPROVAL_REQUIRED_ABOVE = 0.00

# PROVISIONAL. A purchase order commits the shop to spend, so it is queued for
# approval when it is raised, not only when the invoice is later paid.
PURCHASE_ORDERS_NEED_APPROVAL = True

# PROVISIONAL. A discount is a giveaway of margin, so it is a human call too.
DISCOUNTS_NEED_APPROVAL = True

# --- Hard safety rails (never relax these) ---------------------------------
# Drafts for customers are written to the board and never sent. No email, no
# SMS, no vendor phone calls. This is a homework assignment.
ALLOW_OUTBOUND_SEND = False

# A vendor will not ship new product while it has an open unpaid invoice.
VENDOR_BLOCKED_BY_OPEN_INVOICE = True


@dataclass(frozen=True)
class PolicySnapshot:
    """What the agents are handed, so their reasoning can quote it."""

    min_gross_margin: float = MIN_GROSS_MARGIN
    bulk_discount_min_qty: int = BULK_DISCOUNT_MIN_QTY
    cash_reserve: float = CASH_RESERVE
    payment_priority: tuple = PAYMENT_PRIORITY
    purchase_orders_need_approval: bool = PURCHASE_ORDERS_NEED_APPROVAL
    discounts_need_approval: bool = DISCOUNTS_NEED_APPROVAL


def as_prompt_text() -> str:
    """Policy rendered for an agent system prompt."""
    return f"""SHOP POLICY (binding -- cite the rule you relied on):
- Minimum gross margin on any discounted sale: {MIN_GROSS_MARGIN:.0%} of the
  discounted unit price. Never sell below this.
- Bulk discounts may only be considered at {BULK_DISCOUNT_MIN_QTY}+ units.
- Cash reserve ${CASH_RESERVE:,.2f}: binds DISCRETIONARY spend only (new
  purchase orders). Money the shop already owes -- rent, an invoice already
  issued to us -- may be paid down to zero, never below. No revenue is
  modeled, so cash only goes out.
- Negative balances are forbidden. The pay tool refuses rather than overdraws.
- Payment priority when cash is short: {' > '.join(PAYMENT_PRIORITY)};
  earlier due dates first within a tier.
- A human must approve every payment, every purchase order, and every
  discount. Park the request for approval; never self-approve.
- A vendor will not ship while it has an open unpaid invoice with us.
- Customer and vendor messages are DRAFTS only. Nothing is ever sent.
"""
