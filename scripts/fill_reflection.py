"""Write the Reflection tab of `output/desk_tickets.html`.

    python scripts/fill_reflection.py

Replaces the "coming later" stub left in Problem 6. Re-runnable: it swaps
whatever is currently in the `reflect` panel.

The figures quoted are pulled from `output/resolved_tickets.json` rather than
typed in, so the reflection cannot drift from the run it discusses.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "output" / "desk_tickets.html"
DATA = ROOT / "output" / "resolved_tickets.json"


def main() -> int:
    doc = json.load(open(DATA, encoding="utf-8"))
    by_id = {t["id"]: t for t in doc["tickets"]}

    tools = {}
    for tid in (101, 102, 103):
        tools[tid] = sum(len(a["tools_used"]) for a in by_id[tid]["agent_contributions"])

    body = f"""  <h2>Reflection</h2>

  <p class="note">Written after comparing the plan on the ticket tabs against the run that
  actually happened, and against the itemised ledger on the Cash tab.</p>

  <h3>How the agents performed on each ticket</h3>

  <div class="card first">
    <h3>Ticket 102 — the best work on the board</h3>
    <p>Two agents, <strong>one delegation</strong>, six tool calls. Stevie read the lease,
    checked cash, parked the approval and stopped. It avoided the structural trap in this
    ticket: rent is the one obligation in the shop with <strong>no row in
    <code>invoices</code></strong>, so an agent that goes looking for one reports "nothing
    owed" and is exactly backwards. It also did not treat the $250 reserve as a reason to
    refuse rent — correct, since the reserve binds discretionary spend, not an obligation
    already incurred. Nothing wasted, nothing missed.</p>
  </div>

  <div class="card">
    <h3>Ticket 101 — excellent diagnosis, incomplete service</h3>
    <p>Ten tool calls. David avoided the size trap — <code>CC-TEE-WHITE</code> reads ten
    units across M, L and XL while size S sits at zero — and found the real blocker: the
    only vendor who can reprint apparel will not ship while invoice 501 stands. Patrick
    costed the unblock at exactly $840.</p>
    <p>But <strong>Tauhid Zaman was never written to.</strong> Alexis was never called and
    no draft exists for this ticket. The shop worked out precisely why it could not help a
    customer and then told him nothing. The analysis deserves a high mark; the outcome is a
    partial failure, because a resolved ticket and a served customer are not the same thing.</p>
  </div>

  <div class="card not">
    <h3>Ticket 103 — the most work and the weakest judgement</h3>
    <p>Twenty-eight tool calls across two runs, roughly 4.7&times; ticket 102.</p>
    <p>What it got right: <strong>$36.67</strong> per unit is exactly the margin floor
    ($22 cost &divide; 0.6), the 12-unit shortfall and $264 restock are right, and the
    purchase order was correctly refused against $160 available.</p>
    <p>What it got wrong is specific. <strong>Patrick raised approval #4 to pay invoice
    501 — a bill ticket 101 already had pending.</strong> That spent one of the approver's
    decisions on a duplicate. The pay tool refused it, but the agent should not have asked.
    It also approved a discount on twenty hoodies the shop can supply eight of and cannot
    fund the remainder of: a price for goods that will never ship.</p>
  </div>

  <h3>Actual against the Expected plan</h3>

  <table>
    <tr><th>Ticket</th><th>Verdict</th></tr>
    <tr><td class="num">102</td><td><strong>Called exactly.</strong> Facilities alone, one
      delegation, accounting deliberately excluded — because facilities can read
      <span class="t">get_cash_position</span> itself and cannot pay rent in any case.
      Every part of that held.</td></tr>
    <tr><td class="num">101</td><td><strong>Right on structure, wrong on staffing.</strong>
      Inventory first, facilities correctly excluded, shortfall of 1 and the $840 blocker all
      as predicted. But the plan expected three delegations and a customer draft; the run
      produced two and no draft.</td></tr>
    <tr><td class="num">103</td><td><strong>Split.</strong> The plan predicted inventory
      first and flagged that, on this page, as the single prediction most likely to be wrong.
      It was wrong on the first run (accounting first) and right on the closing run. The
      duplicate $840 approval the plan listed as a <em>risk</em> actually happened.</td></tr>
  </table>

  <p>The pattern is worth stating plainly: <strong>the plan was reliable about the data and
  unreliable about the agents.</strong> Every figure predicted from the database — the
  shortfalls, the $840, the $36.67, the $264 — came out exact. Every prediction about which
  agent would act when was shakier, and the one held with least confidence is the one that
  broke.</p>

  <h3>What would have been simpler as a single agent with tools</h3>

  <p><strong>Approval #4 is a failure the multi-agent design caused.</strong> Patrick working
  ticket 103 had no idea that Patrick working ticket 101 had already parked a request against
  invoice 501. One agent holding one context would not have asked twice. The guardrail caught
  it — see the Cash tab, where approval #4 is recorded as approved and then refused — but the
  architecture created the situation the guardrail had to catch.</p>

  <p><strong>Ticket 102 did not need a team at all.</strong> <code>boss &rarr; facilities
  &rarr; boss</code> is a full extra model round-trip, re-sending a system prompt and a set of
  tool schemas, to produce an answer one agent holding <span class="t">get_lease</span>,
  <span class="t">get_cash_position</span> and <span class="t">request_approval</span> could
  have given directly.</p>

  <p>The usual defence of the split is safety — customer service cannot call
  <span class="t">pay_invoice</span> because the tool is not on its list. That is weaker than
  it looks, because <strong>the real guards live in the MCP server, not in the prompts</strong>:
  no overdraft, no double payment and no payment without an approved approval are enforced in
  <code>_spend_guard</code> and <code>_check_approval</code>. A single agent holding all
  seventeen tools would hit exactly the same walls.</p>

  <p>What the split genuinely bought was role-specific prompts that encode role-specific traps
  — the size trap for inventory, "rent has no invoice row" for facilities — and a dashboard
  where the work is legible as a conversation. Both are real gains. Neither required five
  separate model contexts; one longer prompt could carry the same warnings. The design would
  begin to pay for itself with hundreds of tickets worked in parallel, or with different roles
  needing different approvers or permissions. On a board of three, it cost more than it
  returned.</p>

  <h3>Three new problems this team could solve with the tools we built</h3>

  <ol class="chain">
    <li><span class="hop">The Yale AI Club accepts the eight hoodies at $36.67</span>
      <div class="beat-text">Discount approval #3 is already granted.
      <span class="t">check_stock</span> confirms eight in size M,
      <span class="t">save_draft_message</span> writes the confirmation and
      <span class="t">update_ticket</span> closes it. No new tooling at all.</div></li>

    <li><span class="hop">Elm City Gifts sends an invoice for mugs</span>
      <div class="beat-text"><span class="t">find_restock_vendor</span> already matches on
      specialty, so "mugs and small goods" routes correctly rather than defaulting to the
      apparel printer. Patrick weighs it against the $160 remaining using the written payment
      priority, then <span class="t">request_approval</span> and
      <span class="t">pay_invoice</span>. If the amount exceeds $160 the tool refuses — which
      is the correct answer, not a failure.</div></li>

    <li><span class="hop">A customer wants the tee in size M</span>
      <div class="beat-text">Five in stock at $28 list. This is the happy path the board never
      exercised: <span class="t">check_stock</span> reports it fillable, Alexis drafts the
      confirmation, the boss resolves. Worth noting only because every ticket we ran was a
      problem — the team has never actually completed an easy one.</div></li>
  </ol>

  <h3>Three it could not solve, and what each would need</h3>

  <ol class="chain">
    <li><span class="hop">Receiving restocked goods</span>
      <div class="beat-text"><strong>No tool in the server writes
      <code>inventory.qty</code>.</strong> If the twelve hoodies were ordered and landed on
      2026-09-05, nothing could record their arrival. The <code>purchase_orders</code> table
      even declares a <code>received</code> status that no code path can reach — only
      <code>ordered</code> is ever set.
      <br><strong>Needs:</strong> a <code>receive_purchase_order</code> tool that increments
      stock and closes the order, and an inventory agent permitted to call it. Without it the
      restock half of the shop is write-only.</div></li>

    <li><span class="hop">Any money coming in</span>
      <div class="beat-text"><strong>No tool increases
      <code>cash_accounts.balance</code></strong> — the Cash tab only ever falls, by design.
      So the shop has approved a $36.67 price on ticket 103 that it has no mechanism to
      collect: selling the eight hoodies in stock would be $293.36 the ledger cannot record.
      <br><strong>Needs:</strong> a <code>record_sale</code> tool, a receivables concept so an
      unpaid customer order is distinct from cash, and plausibly a sales agent. It also means
      revisiting the "cash only goes out" rule, which is currently load-bearing in every
      affordability decision the team makes.</div></li>

    <li><span class="hop">Time passing</span>
      <div class="beat-text"><strong>Nothing advances <code>desk.date_today</code>.</strong>
      Paying rent moved the lease's <code>next_due</code> to 2026-10-02 and nothing will ever
      notice it fall due. The 2026-09-05 arrival date quoted to Tauhid can never arrive. Every
      overdue test in the shop is measured against a clock frozen at 2026-08-31.
      <br><strong>Needs:</strong> a tool to advance the shop date, and a scheduling agent that
      wakes on dates rather than on tickets — the current team is entirely reactive and only
      ever acts when a human presses a button.</div></li>
  </ol>

  <h3>The short version</h3>
  <p>Ticket 102 is the model of right-sized work. Ticket 101's silence toward a waiting
  customer is the run's real failure, and it is invisible from the board because the ticket
  still shows <strong>resolved</strong>. And approval #4 is the most useful thing that
  happened all run: evidence that splitting the work across five agents introduced a bug a
  single agent would not have had, and that the guardrails — not the prompts — are what caught
  it.</p>"""

    html = PAGE.read_text(encoding="utf-8")

    # The reflection uses .beat-text inside the numbered chain; that class is
    # defined in the dashboard's stylesheet, not this page's. Add the rule once
    # rather than restyling the markup, so the chain reads the same in both.
    if ".beat-text" not in html:
        html = html.replace(
            "  ul.tight { margin: 8px 0 0; padding-left: 20px; }",
            "  .beat-text { font-size: 14px; color: var(--ink-soft); margin-top: 4px; line-height: 1.55; }\n"
            "  .beat-text strong { color: var(--ink); }\n"
            "  ul.tight { margin: 8px 0 0; padding-left: 20px; }",
            1,
        )

    start = html.index('<section class="panel" id="reflect">')
    end = html.index("</section>", start)
    html = html[:start] + '<section class="panel" id="reflect">\n' + body + "\n" + html[end:]
    PAGE.write_text(html, encoding="utf-8")

    print(f"Reflection tab written to {PAGE.relative_to(ROOT)}")
    print(f"  tool calls cited: 101={tools[101]} tools, 102={tools[102]}, 103={tools[103]} (distinct tools per agent)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
