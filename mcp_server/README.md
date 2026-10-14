# Campus Customs MCP server

The shared tool layer for the agent team. Every agent in this homework — boss,
inventory, accounting, facilities, and customer service — reaches the shop's
data through this server instead of writing SQL. One definition of a tool, one
set of rules, used by all five agents.

## What it is for

The agents have to answer questions about a real shop: is this size in stock,
who can reprint it, how fast, can we afford it, what is already overdue. Putting
those questions behind MCP tools means:

- **No invented data.** Every value a tool returns is read from a table or
  computed from table values. If a tool cannot find something it returns an
  `error` field rather than a plausible-looking guess.
- **The shop's clock, not the real one.** "Today" is `desk.date_today`
  (2026-08-31), so every overdue test and lead-time date is measured correctly.
- **One place to enforce the rules.** Business rules live in code, not in a
  prompt the model might ignore.

## Database

Reads and writes `data/campus_customs_new.db`, the working copy.

The pristine `data/campus_customs.db` is never opened for writing — it exists so
a run can be reset. Read-only connections are opened with SQLite's `mode=ro`
URI, so inspection cannot mutate anything by accident. Reset with:

```bash
python scripts/init_working_db.py
```

## Tools

Seventeen tools: eleven read-only, six that write. Two of them (`list_tickets`,
`confirm_purchase_order`) are human/dashboard-facing and are deliberately NOT on
any agent's allowlist. Every one of them is called by
the agent team in `backend/` — nothing in this project reaches past this server
into the database.

| | Tool | Reads / writes |
|---|---|---|
| **Reading the shop** | `check_stock` | `inventory`, `pricing` |
| | `find_restock_vendor` | `vendors`, `invoices`, `pricing`, `inventory`, `desk` |
| | `get_cash_position` | `cash_accounts`, `invoices`, `leases`, `payments`, `desk` |
| | `list_open_tickets` | `tickets` |
| | `get_ticket` | `tickets` + every table it links to |
| | `get_lease` | `leases`, `payments`, `desk` |
| | `evaluate_discount` | `pricing` (+ policy) |
| | `list_approvals` | `approvals` |
| | `get_shop_policy` | *(serves `app/policy.py`)* |
| **Asking a human** | `request_approval` | writes `approvals` |
| **Moving money** | `pay_invoice` | writes `invoices`, `payments`, `cash_accounts` |
| | `pay_rent` | writes `leases`, `payments`, `cash_accounts` |
| | `create_purchase_order` | writes `purchase_orders` |
| **Board state** | `save_draft_message` | writes `drafts` |
| | `update_ticket` | writes `tickets` |
| **Human-side only** | `list_tickets` | `tickets`, `approvals` |
| *(no agent allowlist)* | `confirm_purchase_order` | writes `purchase_orders` |

### The rules the write tools enforce

These are in code here, not in an agent's prompt, because a prompt is advice and
these are rules:

- **No payment without a human.** `pay_invoice` and `pay_rent` refuse unless an
  `approvals` row is already `approved` and names the human who decided. No tool
  on this server can approve anything — approval enters from outside the team.
- **An approval authorises one obligation.** The stored `payload.ref_id` must
  match what is being paid, so an approval cannot be replayed against a
  different bill.
- **No negative balance, ever.** Checked inside the write transaction. The tool
  refuses rather than overdrawing.
- **The cash reserve binds discretionary spend only.** A new purchase order must
  leave $250 behind; an obligation already owed may be paid toward zero.
  Refusing rent to protect a cushion would cost the shop its premises.
- **Nothing is paid twice**, and **no ticket closes while an approval is
  pending**.
- **Nothing is ever sent.** There is no send tool, and `drafts` has no `sent`
  status.

Verified by `python scripts/test_guardrails.py` — 19 checks over a real MCP
connection, no model calls, deterministic.

### `check_stock(sku, size, qty_wanted=1)`

Units on hand for one SKU in one size, plus the shortfall and the item's cost
and list price.

Stock is keyed on the **(sku, size) pair**, so size is required — a SKU can look
well stocked while the requested size sits at zero. If the size has no row at
all, the tool returns the sizes that do exist rather than reporting zero, since
"no record" and "none left" are different facts.

*Reads:* `inventory`, `pricing`

### `find_restock_vendor(sku, qty=1)`

Which vendors can resupply a SKU, how fast, and whether they will actually ship.

A vendor is only usable if both tests pass: their `specialty` covers the product
category, and they have no open unpaid invoice with us. The second test matters
because a vendor will not ship new product while one stands — so an unpaid bill
blocks a restock. The tool reports the blocking invoice and the amount needed to
clear it, plus the arrival date implied by the vendor's `lead_days`.

The local courier is deliberately not offered as a restock source: it ships
goods but manufactures none.

*Reads:* `vendors`, `invoices`, `pricing`, `inventory`, `desk`

### `get_cash_position()`

Cash on hand and every obligation owed, measured against the shop date.

Returns the checking balance, all open vendor invoices and all lease rent due,
flags which are overdue, and totals the lot. Rent has no invoice row, so it is
gathered from `leases` directly. No revenue is modeled in this shop, so the
balance only ever falls — this is the figure every spending decision is checked
against.

*Reads:* `cash_accounts`, `invoices`, `leases`, `payments`, `desk`

### `list_open_tickets()` · `get_ticket(ticket_id)`

The board, and one ticket resolved against every table it references.

Which foreign key is populated is the routing signal: `sku` means a product
question, `lease_id` means facilities, `invoice_id` means an unpaid bill is
entangled with it. `get_ticket` returns the linked inventory, pricing, lease,
invoice and vendor rows in one call, so an agent does not spend four round-trips
re-fetching things the ticket already points at.

*Reads:* `tickets`, `inventory`, `pricing`, `leases`, `invoices`, `vendors`,
`approvals`, `drafts`

### `get_lease(lease_id)`

Lease terms with the rent due date measured against the shop date, plus whether
rent has already been recorded for this cycle.

Rent is the one obligation with **no invoice row** — it lives only on `leases` —
so the facilities agent needs a tool that reads that table directly.

*Reads:* `leases`, `payments`, `desk`

### `evaluate_discount(sku, qty, proposed_unit_price)`

Margin arithmetic against the written floor, done in code so it cannot drift.
Returns the gross margin at the proposed price, whether it clears policy, and
**the lowest price that would** — so an agent can counter rather than simply
refuse.

*Reads:* `pricing`, plus the constants in `app/policy.py`

### `request_approval(...)` · `list_approvals(status=None)`

The human-in-the-loop queue. An agent parks a request and ends its turn; the row
lands as `pending` and only a human moves it on. `payload` stores the exact
arguments to replay, so an approved request is executed faithfully rather than
re-derived.

*Writes:* `approvals` · *Reads:* `approvals`

### `pay_invoice(invoice_id, approval_id)` · `pay_rent(lease_id, approval_id)`

The two tools that move money. Both refuse without an approved approval, refuse
to overdraw, and refuse to pay the same thing twice. On success they debit cash
and write an audit row to `payments` naming the human who approved it.

`pay_rent` also advances the lease's `next_due` by a month, which is what stops
the same cycle being paid again.

*Writes:* `payments`, `cash_accounts`, and `invoices` or `leases`

### `create_purchase_order(...)`

Raises a costed **draft** PO. The cost comes from `pricing.unit_cost` and the
expected date from the vendor's `lead_days`, so neither number is invented. It
refuses immediately if the shop cannot fund it while keeping the reserve, and
flags when the chosen vendor is blocked by an open invoice.

A draft is not an order — it still needs `request_approval`.

*Writes:* `purchase_orders` · *Reads:* `vendors`, `pricing`, `invoices`,
`cash_accounts`, `desk`

### `save_draft_message(...)`

Writes a customer, vendor or landlord message to the board. Returns
`sent: False`, because there is nothing on this server that could make it true.

*Writes:* `drafts`

### `update_ticket(ticket_id, status=None, assignee=None, resolution=None)`

Records who owned a ticket and how it ended. Refuses to mark a ticket `resolved`
while it still has a pending approval — that would hide a decision a human has
not made.

*Writes:* `tickets` · *Reads:* `approvals`

### `list_tickets(status=None)` · `confirm_purchase_order(po_id, approval_id)`

Added for the dashboard in Problem 7, and **on no agent's allowlist**.

`list_tickets` returns the whole board including resolved and declined tickets,
with `is_open` / `is_resolved` flags and any approvals still pending. The agents
keep `list_open_tickets` instead, which is correctly a work queue rather than an
archive.

`confirm_purchase_order` is the "approve a purchase" half of a human decision.
It refuses without an approved approval row and refuses to place the same order
twice. It moves no cash — in this model a PO is a commitment, and payment
happens separately — so there is no debit to guard here.

*Reads:* `tickets`, `approvals` · *Writes:* `purchase_orders`

### `get_shop_policy()`

The shop's written rules and numbers, served from the same `app/policy.py` the
write tools enforce. Agents cite policy instead of inventing thresholds, and
what an agent is told can never drift from what the tools do.

## Running it

Not required for the problem that built it, but it runs:

```bash
pip install -r requirements.txt
python mcp_server/server.py
```

Built with [FastMCP](https://github.com/jlowin/fastmcp) 4.x, stdio transport.

> **Version note.** The `mcp` package reached 2.x and renamed its bundled
> `FastMCP` class to `MCPServer`, so `from mcp.server.fastmcp import FastMCP`
> no longer resolves. This server uses the standalone `fastmcp` package, which
> keeps the FastMCP name and API.
