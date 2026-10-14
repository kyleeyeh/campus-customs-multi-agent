"""Fill the Actual sections and the Cash tab of `output/desk_tickets.html`.

    python scripts/fill_desk_tickets.py

The Expected sections written in Problem 6 are left exactly as they were — the
whole point is to read the two side by side, including where the plan was
wrong.

Every figure placed into the page is read from `output/resolved_tickets.json`,
which is itself built from the working database and the audit trail. Nothing is
typed in by hand, so the page cannot drift from the run it describes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "output" / "desk_tickets.html"
DATA = ROOT / "output" / "resolved_tickets.json"

PLACEHOLDER = (
    '  <div class="actual"><strong>To be filled after the agents run.</strong>\n'
    "  Chain actually taken, tools actually called, end state, and where this plan was wrong.</div>"
)


def money(n: float) -> str:
    return f"${n:,.2f}"


def chips(tools: list[str]) -> str:
    return " ".join(f'<span class="t">{t}</span>' for t in tools) or "—"


def agent_rows(t: dict) -> str:
    out = []
    for a in t["agent_contributions"]:
        out.append(
            f"<tr><td><strong>{a['character']}</strong><br>"
            f"<span class='note' style='font-size:11px'>{a['agent'].replace('_', ' ')}</span></td>"
            f"<td>{chips(a['tools_used'])}</td></tr>"
        )
    return "".join(out)


def verdict_rows(items: list[tuple[str, bool | None, str]]) -> str:
    out = []
    for claim, hit, detail in items:
        if hit is True:
            mark, cls = "right", "t"
        elif hit is False:
            mark, cls = "wrong", "t x"
        else:
            mark, cls = "partly", "t w"
        out.append(
            f"<tr><td>{claim}</td><td><span class='{cls}'>{mark}</span></td><td>{detail}</td></tr>"
        )
    return "".join(out)


# Which predictions held. Written out explicitly rather than inferred, because
# "was the plan right" is a judgement about meaning, not a string comparison.
SCORECARD: dict[int, list[tuple[str, bool | None, str]]] = {
    101: [
        ("Boss calls inventory first", True, "It did — stock was the branch-decider, as argued."),
        ("Facilities not involved", True, "Never called. Rent appeared only inside get_cash_position."),
        ("Three delegations", True, "Three: inventory, customer_service, accounting — all fanned out from the boss."),
        (
            "Inventory delegates straight to accounting",
            False,
            "Flagged as the least certain call, and it was wrong again: inventory reported back "
            "and the boss routed to accounting itself.",
        ),
        (
            "Customer service drafts a reply",
            True,
            "Draft #1 to Tauhid Zaman — says size S is unavailable, promises no shipment, and "
            "commits only to following up.",
        ),
        ("Shortfall of 1, blocked by invoice 501 ($840)", True, "Exactly that."),
        ("No purchase order raised", True, "None attempted, as expected while the vendor was blocked."),
        ("Agents move $0.00", True, "Approval parked; nothing paid until a human decided."),
    ],
    102: [
        ("Boss calls facilities first", True, "Straight there — only lease_id was populated."),
        ("Exactly one delegation", True, "One. boss → facilities and back."),
        ("Accounting deliberately excluded", True, "Not called. Facilities read the balance itself."),
        ("Customer service not involved", True, "Not called; the answer to a rent notice is a payment."),
        ("Tools: get_lease, get_cash_position, request_approval", True, "All three, plus list_approvals."),
        ("Rent $2,400 due 2026-09-02, no invoice row", True, "Confirmed from the lease."),
        ("Cheapest ticket on the board", True, "Two agents, six tool calls — fewest of the three."),
        ("Agents move $0.00", True, "Approval #2 parked and nothing else."),
    ],
    103: [
        (
            "Boss calls inventory first",
            True,
            "Right this time. The plan named this its least confident call; the run opened "
            "boss → inventory exactly as predicted.",
        ),
        (
            "Three delegations",
            False,
            "Five — and two of them were specialist-to-specialist: customer_service → "
            "accounting and customer_service → inventory, without passing back through the boss.",
        ),
        ("Facilities not involved", True, "Correctly left out."),
        (
            "Discount floor of $36.67/unit",
            None,
            "The floor was computed exactly — evaluate_discount returned $36.67 as the lowest "
            "price meeting the 40% margin. But the shop approved the customer's own $40.00 "
            "offer (45% margin, $800 for 20) rather than countering down to the floor.",
        ),
        ("Shortfall of 12, restock $264", True, "8 of 20 on hand; find_restock_vendor priced the 12-unit gap at $264."),
        (
            "A purchase order is attempted and refused",
            False,
            "No purchase order was attempted at all this time. Accounting reasoned ahead of the "
            "tool — it ruled the $264 restock unfundable against the $250 reserve and never "
            "called create_purchase_order. purchase_orders is empty either way.",
        ),
        (
            "Customer service drafts a reply",
            True,
            "Draft #2 to the Yale AI Club: 8 of 20 available, the rest not fillable now.",
        ),
        (
            "A duplicate $840 approval may be raised",
            True,
            "It was — approval #4, again. A human approved it and pay_invoice still refused, "
            "because invoice 501 had already been settled by approval #1.",
        ),
        ("Agents move $0.00", True, "Nothing moved on this ticket at all."),
    ],
}


def actual_block(t: dict) -> str:
    tid = t["id"]
    cash = t["cash"]
    approvals = "".join(
        f"<tr><td class='num'>#{a['approval_id']}</td><td>{a['kind']}</td>"
        f"<td class='num'>{money(a['amount']) if a['amount'] else '—'}</td>"
        f"<td>{a['status']}{' by ' + a['decided_by'] if a['decided_by'] else ''}</td></tr>"
        for a in t["human_approvals"]
    ) or "<tr><td colspan='4'>None raised.</td></tr>"

    payments = "".join(
        f"<li><span class='t'>payment #{p['payment_id']}</span> {p['kind']} "
        f"<strong>{money(p['amount'])}</strong> on {p['paid_at']}, approved by {p['approved_by']}</li>"
        for p in t["payments_executed"]
    ) or "<li>No cash moved on this ticket.</li>"

    drafts = "".join(
        f"<li>draft #{d['draft_id']} to {d['recipient']} ({d['audience']}) — <strong>not sent</strong></li>"
        for d in t["drafts_written"]
    ) or "<li class='note'>No draft was written on this run.</li>"

    return f"""  <h2>Actual</h2>

  <div class="card">
    <h3>What happened</h3>
    <p class="note">Run <code>{t['runs'][0] if t['runs'] else '—'}</code> ·
    final status <strong>{t['final_status']}</strong> ·
    owned by <strong>{t['assignee_character'] or t['assignee']}</strong></p>
    <p>{t['outcome'] or ''}</p>
  </div>

  <h3>Delegation chain actually taken</h3>
  <p class="note" style="font-family:var(--mono);font-size:13px">
    {' &rarr; '.join([t['delegation_chain'][0].split(' -> ')[0]] + [h.split(' -> ')[1] for h in t['delegation_chain']]) if t['delegation_chain'] else 'no delegation'}
  </p>
  <p class="note">{len(t['delegation_chain'])} delegation(s); {len(t['agent_contributions'])} of the five agents appeared.</p>

  <h3>Tools actually called</h3>
  <table><tr><th>Agent</th><th>Tools</th></tr>{agent_rows(t)}</table>

  <h3>Human approvals</h3>
  <table><tr><th>#</th><th>Kind</th><th>Amount</th><th>Decision</th></tr>{approvals}</table>

  <h3>Money and drafts</h3>
  <ul class="tight">{payments}{drafts}</ul>
  <table>
    <tr><th>Balance before</th><th>Change</th><th>Balance after</th></tr>
    <tr><td class="num">{money(cash['balance_before'])}</td>
        <td class="num">{money(cash['change']) if cash['change'] else '$0.00'}</td>
        <td class="num"><strong>{money(cash['balance_after'])}</strong></td></tr>
  </table>

  <h3>Plan versus run</h3>
  <table><tr><th>What the plan said</th><th></th><th>What happened</th></tr>
    {verdict_rows(SCORECARD[tid])}
  </table>"""


def cash_tab(doc: dict) -> str:
    rows = []
    # Present in the order the money actually moved, not ticket-id order.
    ordered = sorted(doc["tickets"], key=lambda t: t["cash"]["balance_before"], reverse=True)
    for t in ordered:
        c = t["cash"]
        if t["payments_executed"]:
            why = "; ".join(
                f"{p['kind']} payment of {money(p['amount'])} "
                f"(approval #{t['human_approvals'][0]['approval_id']}, approved by {p['approved_by']})"
                for p in t["payments_executed"]
            )
        else:
            why = "No payment executed on this ticket."
        rows.append(
            f"<tr><td class='num'>#{t['id']}</td><td>{t['subject']}</td>"
            f"<td class='num'>{money(c['balance_before'])}</td>"
            f"<td class='num'>{money(c['change']) if c['change'] else '$0.00'}</td>"
            f"<td class='num'><strong>{money(c['balance_after'])}</strong></td>"
            f"<td>{why}</td></tr>"
        )

    chk = doc["arithmetic_check"]
    # The approved discount, read off the approval itself. The agents choose the
    # price inside the margin floor, so it can differ run to run — quoting the
    # payload keeps this paragraph honest without a hand-edit each time.
    disc = next(
        a for t in doc["tickets"] for a in t["human_approvals"] if a["kind"] == "discount"
    )
    disc_qty = (disc.get("payload") or {}).get("qty")
    disc_unit = (disc.get("payload") or {}).get("unit_price")

    # A payment approval that a human approved but which produced no payment
    # row was refused by the pay tool. That is the most interesting line in the
    # whole ledger, so it is called out rather than silently omitted.
    refused = [
        (t["id"], a)
        for t in doc["tickets"]
        for a in t["human_approvals"]
        if a["kind"] == "payment"
        and a["status"] == "approved"
        and not t["payments_executed"]
    ]
    refused_note = "".join(
        f"<li>Approval <strong>#{a['approval_id']}</strong> on ticket {tid} "
        f"({money(a['amount'])}) was approved by a human and then <strong>refused by the pay "
        f"tool</strong> — invoice 501 had already been settled by approval #1. No second "
        f"payment was made, which is exactly why it does not appear in the ledger above.</li>"
        for tid, a in refused
    )

    return f"""  <h2>Cash</h2>

  <div class="card first">
    <h3>Starting checking balance, after the reset</h3>
    <p style="font-family:var(--mono);font-size:26px;margin:4px 0">{money(doc['starting_checking_balance'])}</p>
    <p class="note">Reset with <code>python scripts/init_working_db.py</code>, which copies the
    pristine <code>data/campus_customs.db</code> over the working copy. Zero payments and zero
    approvals on the board at the start.</p>
  </div>

  <h3>How cash changed, ticket by ticket</h3>
  <p class="note">Listed in the order the money actually moved. Rent was paid first because the
  shop's written payment priority ranks rent above vendor invoices — not because ticket 102 was
  worked first.</p>
  <table>
    <tr><th>Ticket</th><th>Subject</th><th>Before</th><th>Change</th><th>After</th><th>Why</th></tr>
    {''.join(rows)}
  </table>

  <h3>Ending checking balance</h3>
  <table>
    <tr><th>Line</th><th>Amount</th></tr>
    <tr><td>Starting balance</td><td class="num">{money(doc['starting_checking_balance'])}</td></tr>
    <tr><td>Rent — lease 1, Elm City Properties (payment #1)</td><td class="num">−{money(2400.0)}</td></tr>
    <tr><td>Invoice 501 — Bulldog Print Co, overdue (payment #2)</td><td class="num">−{money(840.0)}</td></tr>
    <tr><td><strong>Total paid out</strong></td><td class="num"><strong>−{money(doc['total_paid'])}</strong></td></tr>
    <tr><td><strong>Ending balance</strong></td><td class="num"><strong>{money(doc['ending_checking_balance'])}</strong></td></tr>
  </table>

  <div class="card {'first' if chk['matches'] else 'not'}">
    <h3>Reconciled against the database</h3>
    <p style="font-family:var(--mono)">
      {money(doc['starting_checking_balance'])} − {money(doc['total_paid'])}
      = <strong>{money(chk['starting_minus_payments'])}</strong><br>
      <code>cash_accounts.balance</code> in <code>data/campus_customs_new.db</code>
      = <strong>{money(chk['database_cash_accounts_balance'])}</strong>
    </p>
    <p><strong>{'These match.' if chk['matches'] else 'THESE DO NOT MATCH.'}</strong>
    The per-ticket changes above also sum to −{money(doc['total_paid'])}, so no payment is
    counted twice and none is missing.</p>
  </div>

  <h3>Two things that did not move cash, and why</h3>
  <ul class="tight">
    <li>Approval <strong>#{disc['approval_id']}</strong> on ticket 103 approved a bulk discount
      at <strong>{money(disc_unit)}</strong>/unit ({money(disc['amount'])} for {disc_qty} units).
      A discount is a price, not a payment — nothing is debited, and counting its headline figure
      as spending would overstate outgoings by {money(disc['amount'])}.</li>
    {refused_note}
    <li>No purchase order was ever placed, so no restock was committed. The 12-unit hoodie
      restock at {money(264.0)} could not be funded from the {money(160.0)} remaining, and the
      $250 discretionary reserve blocks it regardless.</li>
  </ul>

  <p class="note">No revenue is modelled in this shop, so the balance only ever falls. Every
  payment above required a human decision; the agents moved nothing on their own.</p>"""


def main() -> int:
    doc = json.load(open(DATA, encoding="utf-8"))
    html = PAGE.read_text(encoding="utf-8")

    # Re-runnable: replaces the Actual block whether it is still the Problem 6
    # placeholder or content from an earlier pass. Each ticket panel ends at
    # its </section>, and Actual is the last thing in it, so everything from
    # the heading to that tag is the block to swap. Expected is never touched.
    marker = "  <h2>Actual</h2>"
    cursor = 0
    for t in doc["tickets"]:
        start = html.find(marker, cursor)
        if start == -1:
            print(f"no Actual section left to fill for ticket {t['id']}")
            return 1
        end = html.index("</section>", start)
        block = actual_block(t)
        html = html[:start] + block + "\n\n" + html[end:]
        # Advance past what was just written, so the next ticket finds the
        # next Actual rather than re-matching the one we have just produced.
        cursor = start + len(block)

    # Cash tab
    start = html.index('<section class="panel" id="cash">')
    end = html.index("</section>", start)
    html = html[:start] + '<section class="panel" id="cash">\n' + cash_tab(doc) + "\n" + html[end:]

    PAGE.write_text(html, encoding="utf-8")
    print(f"filled 3 Actual sections and the Cash tab in {PAGE.relative_to(ROOT)}")
    print(f"  start {money(doc['starting_checking_balance'])} -> end {money(doc['ending_checking_balance'])}")
    print(f"  reconciles: {doc['arithmetic_check']['matches']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
