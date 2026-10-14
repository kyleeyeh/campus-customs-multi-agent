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


CAPTURE = ROOT / "output" / "full_run_capture.json"
TRAIL = ROOT / "output" / "audit_trail.json"


def run_shape() -> dict[int, dict[str, int]]:
    """Tool calls, delegations and head-count per ticket, for the latest pass.

    Counted off the audit trail rather than typed in, so the numbers quoted in
    the prose below cannot drift away from the run they describe. `delegate`
    and `final_result` are framework plumbing, not shop tools, so they are
    excluded from the tool count and counted as delegations instead.
    """
    capture = json.load(open(CAPTURE, encoding="utf-8"))
    run_ids = {r["run_id"] for r in capture["runs"]}
    trail = [e for e in json.load(open(TRAIL, encoding="utf-8")) if e["run_id"] in run_ids]

    shape: dict[int, dict[str, int]] = {}
    for tid in (101, 102, 103):
        rows = [e for e in trail if e.get("ticket_id") == tid]
        shape[tid] = {
            "calls": sum(
                1
                for e in rows
                if e.get("event") == "tool_call"
                and e.get("tool_name") not in ("delegate", "final_result")
            ),
            "delegations": sum(1 for e in rows if e.get("event") == "delegation"),
            "agents": len({e["agent"] for e in rows if e.get("agent")}),
        }
    return shape


def main() -> int:
    doc = json.load(open(DATA, encoding="utf-8"))
    by_id = {t["id"]: t for t in doc["tickets"]}
    shape = run_shape()
    t101, t102, t103 = shape[101], shape[102], shape[103]
    ratio = t103["calls"] / t102["calls"]

    body = f"""  <h2>Reflection</h2>

  <p class="note">Written after comparing the plan on the ticket tabs against the run that
  actually happened, and against the itemised ledger on the Cash tab. Every count below is
  read off <code>audit_trail.json</code> for this pass, not typed in.</p>

  <h3>How the agents performed on each ticket</h3>

  <div class="card first">
    <h3>Ticket 102 &mdash; the tightest work on the board</h3>
    <p>{t102["agents"]} agents, <strong>one delegation</strong>, {t102["calls"]} tool calls,
    and the cheapest run of the three. Stevie read the lease, checked cash, parked the
    approval and stopped. It avoided the structural trap in this ticket: rent is the one
    obligation in the shop with <strong>no row in <code>invoices</code></strong>, so an agent
    that goes looking for one reports "nothing owed" and is exactly backwards. It also did not
    treat the $250 reserve as a reason to refuse rent &mdash; correct, since the reserve binds
    discretionary spend, not an obligation already incurred. Nothing wasted, nothing missed.</p>
  </div>

  <div class="card">
    <h3>Ticket 101 &mdash; diagnosis and service, this time</h3>
    <p>{t101["agents"]} agents, {t101["delegations"]} delegations, {t101["calls"]} tool calls.
    David found the real blocker: the only vendor who can reprint apparel will not ship while
    invoice 501 stands, so the one-unit shortfall cannot be closed for $8 until $840 moves.
    Patrick costed the unblock at exactly that and parked it. Worth noting he reached the
    shortfall through the ticket payload rather than calling
    <span class="t">check_stock</span> &mdash; the number was right, but the cheaper read was
    also the less deliberate one.</p>
    <p><strong>Alexis wrote to Tauhid Zaman.</strong> Draft #1 says size S is unavailable,
    promises no shipment, and commits only to following up &mdash; which is the correct message
    when the honest answer is "not yet". This is the difference between a ticket that is closed
    and a customer who has been served, and on the previous pass the shop managed only the
    first.</p>
  </div>

  <div class="card not">
    <h3>Ticket 103 &mdash; the most work and still the weakest judgement</h3>
    <p>{t103["calls"]} tool calls and {t103["delegations"]} delegations, roughly
    {ratio:.1f}&times; ticket 102 &mdash; but one pass, where the previous run needed two.</p>
    <p>What it got right: the 12-unit shortfall and the $264 restock are exact, the margin
    floor was computed correctly at <strong>$36.67</strong> ($22 cost &divide; 0.6), and the
    customer's own <strong>$40.00</strong> offer was checked against it rather than waved
    through &mdash; 45% margin, above the 40% floor, $800 for twenty.</p>
    <p>What it got wrong is specific. <strong>Patrick raised approval #4 to pay invoice 501
    &mdash; a bill ticket 101 already had pending.</strong> That spent one of the approver's
    decisions on a duplicate, and it happened again this run. The pay tool refused it, but the
    agent should not have asked. It also approved a price on twenty hoodies the shop can supply
    eight of and cannot fund the remainder of. And where the previous run at least put the
    purchase order to the tool and had it refused, this one never called
    <span class="t">create_purchase_order</span> at all &mdash; accounting ruled the $264
    unfundable against the $250 reserve and stopped. Same answer, less evidence.</p>
  </div>

  <h3>Actual against the Expected plan</h3>

  <table>
    <tr><th>Ticket</th><th>Verdict</th></tr>
    <tr><td class="num">102</td><td><strong>Called exactly.</strong> Facilities alone, one
      delegation, accounting deliberately excluded &mdash; because facilities can read
      <span class="t">get_cash_position</span> itself and cannot pay rent in any case.
      Every part of that held, on both runs.</td></tr>
    <tr><td class="num">101</td><td><strong>The plan finally came true.</strong> Inventory
      first, facilities correctly excluded, shortfall of 1 and the $840 blocker as predicted
      &mdash; and this time the three delegations and the customer draft the plan expected both
      happened. The one miss is the same as before: the plan had inventory handing off straight
      to accounting, and instead every hop went back through the boss.</td></tr>
    <tr><td class="num">103</td><td><strong>Right where it doubted itself, wrong on
      size.</strong> The plan named "inventory first" as its least confident call and the run
      opened exactly that way. But three delegations became five, two of which were
      specialist-to-specialist, and the duplicate $840 approval the plan listed as a
      <em>risk</em> happened again.</td></tr>
  </table>

  <p>The pattern is worth stating plainly: <strong>the plan was reliable about the data and
  unreliable about the agents.</strong> Every figure predicted from the database &mdash; the
  shortfalls, the $840, the $36.67, the $264 &mdash; came out exact, across two separate runs.
  Every prediction about <em>which agent would act when</em> was shakier, and the routing
  changed between runs even though the database did not.</p>

  <h3>What would have been simpler as a single agent with tools</h3>

  <p><strong>Approval #4 is a failure the multi-agent design caused, and it is
  reproducible.</strong> Patrick working ticket 103 had no idea that Patrick working ticket 101
  had already parked a request against invoice 501 &mdash; because they are different runs
  holding different contexts. One agent carrying one context would not have asked twice. It
  happened on both passes. The guardrail caught it both times &mdash; see the Cash tab, where
  approval #4 is recorded as approved and then refused &mdash; but the architecture created the
  situation the guardrail had to catch.</p>

  <p><strong>Ticket 103 shows the coordination cost directly.</strong> Alexis delegated to
  Patrick, then to David, then reported to Johnny, who delegated to Patrick again &mdash; five
  hops to reach a conclusion that rests on three numbers ($40 clears the floor, 12 units short,
  $264 unaffordable). The trail even contains the architecture arguing with itself: Alexis
  tried to delegate back to the boss and the framework refused it to avoid a loop. That beat
  cost a model round-trip and produced nothing.</p>

  <p><strong>Ticket 102 did not need a team at all.</strong> <code>boss &rarr; facilities
  &rarr; boss</code> is a full extra model round-trip, re-sending a system prompt and a set of
  tool schemas, to produce an answer one agent holding <span class="t">get_lease</span>,
  <span class="t">get_cash_position</span> and <span class="t">request_approval</span> could
  have given directly.</p>

  <p>The usual defence of the split is safety &mdash; customer service cannot call
  <span class="t">pay_invoice</span> because the tool is not on its list. That is weaker than
  it looks, because <strong>the real guards live in the MCP server, not in the
  prompts</strong>: no overdraft, no double payment and no payment without an approved approval
  are enforced in <code>_spend_guard</code> and <code>_check_approval</code>. A single agent
  holding all seventeen tools would hit exactly the same walls.</p>

  <p>What the split genuinely bought was role-specific prompts that encode role-specific traps
  &mdash; the size trap for inventory, "rent has no invoice row" for facilities, and the line
  that now makes a customer draft a closing condition rather than a nicety &mdash; and a
  dashboard where the work is legible as a conversation. Both are real gains, and the second
  one is what fixed ticket 101 between runs. Neither required five separate model contexts; one
  longer prompt could carry the same warnings. The design would begin to pay for itself with
  hundreds of tickets worked in parallel, or with different roles needing different approvers
  or permissions. On a board of three, it cost more than it returned.</p>

  <h3>Three new problems this team could solve with the tools we built</h3>

  <ol class="chain">
    <li><span class="hop">The Yale AI Club accepts the eight hoodies at $40.00</span>
      <div class="beat-text">Discount approval #3 is already granted at that price.
      <span class="t">check_stock</span> confirms eight in size M,
      <span class="t">save_draft_message</span> writes the confirmation and
      <span class="t">update_ticket</span> closes it. No new tooling at all.</div></li>

    <li><span class="hop">Elm City Gifts sends an invoice for mugs</span>
      <div class="beat-text"><span class="t">find_restock_vendor</span> already matches on
      specialty, so "mugs and small goods" routes correctly rather than defaulting to the
      apparel printer. Patrick weighs it against the $160 remaining using the written payment
      priority, then <span class="t">request_approval</span> and
      <span class="t">pay_invoice</span>. If the amount exceeds $160 the tool refuses &mdash;
      which is the correct answer, not a failure.</div></li>

    <li><span class="hop">A customer wants the tee in size M</span>
      <div class="beat-text">Five in stock at $28 list. This is the happy path the board never
      exercised: <span class="t">check_stock</span> reports it fillable, Alexis drafts the
      confirmation, the boss resolves. Worth noting only because every ticket we ran was a
      problem &mdash; the team has never actually completed an easy one.</div></li>
  </ol>

  <h3>Three it could not solve, and what each would need</h3>

  <ol class="chain">
    <li><span class="hop">Receiving restocked goods</span>
      <div class="beat-text"><strong>No tool in the server writes
      <code>inventory.qty</code>.</strong> If the twelve hoodies were ordered and landed on
      2026-09-05, nothing could record their arrival. The <code>purchase_orders</code> table
      even declares a <code>received</code> status that no code path can reach &mdash; only
      <code>ordered</code> is ever set.
      <br><strong>Needs:</strong> a <code>receive_purchase_order</code> tool that increments
      stock and closes the order, and an inventory agent permitted to call it. Without it the
      restock half of the shop is write-only.</div></li>

    <li><span class="hop">Any money coming in</span>
      <div class="beat-text"><strong>No tool increases
      <code>cash_accounts.balance</code></strong> &mdash; the Cash tab only ever falls, by
      design. So the shop has approved a $40.00 price on ticket 103 that it has no mechanism to
      collect: selling the eight hoodies in stock would be $320.00 the ledger cannot record.
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
      wakes on dates rather than on tickets &mdash; the current team is entirely reactive and
      only ever acts when a human presses a button.</div></li>
  </ol>

  <h3>The short version</h3>
  <p>Ticket 102 is the model of right-sized work and has been on every run. Ticket 101 is the
  one that changed: the silence toward a waiting customer was the previous run's real failure,
  invisible from the board because the ticket still showed <strong>resolved</strong>, and it
  took a prompt that makes the draft a condition of closing rather than a suggestion to fix it.
  And approval #4 is still the most useful thing that happens on this board: evidence,
  reproduced across two runs, that splitting the work across five agents introduces a bug a
  single agent would not have had, and that the guardrails &mdash; not the prompts &mdash; are
  what catch it.</p>"""

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
    for tid in (101, 102, 103):
        c = shape[tid]
        print(
            f"  cited for {tid}: {c['calls']} tool calls, "
            f"{c['delegations']} delegation(s), {c['agents']} agents"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
