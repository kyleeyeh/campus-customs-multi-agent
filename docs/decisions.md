# Design decisions

**Campus Customs Multi-Agent Operations** · Kyle Yeh · MGT 403 · Homework 5

Choices made while building this project, with the reasoning behind them. Several
were not specified by the assignment, so they were decided deliberately and
written down here rather than improvised inside the code.

The prompt-by-prompt record of the build is in [`../AI_prompts.md`](../AI_prompts.md).

---

## Decided in Problem 1 (setup)

| Decision | Choice | Why |
|---|---|---|
| Agent framework | ~~OpenAI Agents SDK~~ → **pydantic-ai** (changed in Problem 5) | Problem 5 specified pydantic-ai, so the framework changed. The reasoning that picked the original — an OpenAI-compatible endpoint and any-to-any delegation — holds for pydantic-ai too, and the approval flow below survived the switch unchanged. See "Decided in Problem 5". |
| Approval flow | Park and resume | An agent writes a pending row to `approvals` and ends its turn. Approving in the dashboard resumes the work. Survives a restart, and no HTTP request hangs waiting on a human. |
| Policy values | One file, `app/policy.py`, tagged `PROVISIONAL` | The assignment did not specify the margin floor, cash reserve, or payment priority. Centralizing them means agents cite a written rule instead of inventing a number per call, and a later problem can change one constant instead of forcing a refactor. |
| Model safety | `scripts/check_model_guard.py` | Points are deducted if any model other than `gpt-6-luna` appears. The script scans the repo for model identifiers and exits non-zero, so a stray copy-paste cannot be committed silently. |
| Database files | ~~Original committed, working copy gitignored~~ → **both committed** (changed in Problem 11) | Graders need `campus_customs.db` to reproduce. The working copy was originally gitignored as regenerable, but Problem 11 asks for both files so a grader can clone and see the resolved board without spending a token. `scripts/init_working_db.py` still restores it. |
| Secrets | `.env` gitignored, `.env.example` committed | The final submission is a public repo. The Portkey key must never reach it. |

## Schema extensions

Added to the working copy only; `campus_customs.db` is never modified.

| Table / column | Purpose |
|---|---|
| `approvals` | The human-in-the-loop queue. Stores the exact tool arguments as JSON so an approved request can be replayed faithfully. |
| `purchase_orders` | Restock commitments, with `expected_date` computed from the vendor's `lead_days`. |
| `drafts` | Customer, vendor, and landlord messages. **Has no `sent` status by design** — "drafts stay on the board" becomes a schema guarantee rather than a prompt the model might ignore. |
| `agent_messages` | One row per message, handoff, and tool call. This is what lets the dashboard show the team working instead of only final answers. |
| `runs` | Groups the activity for one ticket so a run can be paused for approval and resumed. |
| `tickets.assignee` / `.resolution` / `.resolved_at` | Which agent owns a ticket and how it ended. |

## Provisional policy values

In `app/policy.py`. Each is a named constant with its reasoning inline. **If a
later problem specifies the real value, change it there and the whole agent team
follows.**

| Constant | Value | Reasoning |
|---|---|---|
| `MIN_GROSS_MARGIN` | 40% | The hoodie carries a 62% margin at list ($22 cost / $58 list), so a 40% floor leaves genuine negotiating room while refusing sales near cost. |
| `BULK_DISCOUNT_MIN_QTY` | 12 | Below this, the answer is list price. |
| `CASH_RESERVE` | $250 | No revenue is modeled, so the balance only falls. A reserve stops the shop spending itself to zero on one discretionary purchase order. |
| `PAYMENT_PRIORITY` | rent → vendor invoice → purchase order | Losing the premises ends the business; a late vendor invoice costs goodwill and blocks shipments. Earlier due dates win within a tier. |
| `PURCHASE_ORDERS_NEED_APPROVAL` | true | A PO commits the shop to spend, so it is queued when raised, not only when cash later moves. |

Two rules in that file are **hard invariants, not provisional**: no negative cash
balance ever, and nothing is ever sent to a real customer or vendor.

## Technical notes

**`gpt-6-luna` rejects `max_tokens`.** It requires `max_completion_tokens`;
passing the wrong one returns a confusing HTTP 400 from the Azure backend behind
Portkey. Found by smoke-testing the model before writing any agent code.

**This project does not import the class root's `ai.py`.** That helper is pinned
to a different model, and the assignment permits only one. Everything model-related
lives in `app/config.py`.

**pydantic-ai sends `reasoning_effort`, and Azure rejects it alongside function
tools.** The framework infers a reasoning profile from the `gpt-` prefix. The
resulting 400 reads:

> Function tools with reasoning_effort are not supported for gpt-6-luna-global
> in /v1/chat/completions.

Every agent here uses tools, so without `openai_reasoning_effort='none'` the
entire team fails on its first tool call. Pinned in `backend/model_provider.py`.

**`AgentRunResult.usage` is a property, not a method** in pydantic-ai 2.x.
Calling it raises `TypeError: 'RunUsage' object is not callable`.

**`.mcp.json` is read at session startup only.** Writing or editing it has no
effect on a running session, and neither does changing the working directory
mid-session. A restart is always required. More importantly, the file is
discovered from the **session's root folder** — opening the class root instead of
the project folder means it is never found, and this fails *silently*, with the
tools simply absent and no error logged anywhere.

---

## Decided in Problem 4 (connecting the MCP server)

| Decision | Choice | Why |
|---|---|---|
| `.mcp.json` launch path | Repo-relative `mcp_server/server.py` with a bare `python` command | Anyone cloning the public repo gets a working config. No absolute paths, no reference to a local virtualenv. A user-scope registration with absolute paths was considered for convenience and rejected — it would fix one machine and leave the repo broken for graders. |
| MCP approval | `.claude/settings.local.json` with `enableAllProjectMcpServers: true`, **gitignored** | Pre-approves the one server this project defines, for this folder only. Kept out of the repo because it is a machine-local editor setting and the submission is public. |
| Who applies harness config | The human, not the assistant | Edits to `~/.claude.json` and `.claude/settings.*` are refused by the permission system as self-modification. The correct response is to diagnose, hand over the exact command, and report the refusal — not to find a way around it. |
| Evidence standard for tool tests | A real call from the caller that is actually being claimed | Problem 4 asked that the *vibe coder* be able to call the tools. A client-script result is not that, even though it exercises the same protocol. The distinction was reported rather than glossed, and the problem was reopened until the tools loaded for real. |

## Decided in Problem 5 (the agent team)

| Decision | Choice | Why |
|---|---|---|
| Agent framework | pydantic-ai 2.54 (`pydantic-ai-slim[openai,mcp]`) | Specified by the problem. The slim package with two extras rather than the full install — nothing here needs the other providers, and a public repo should not ask a grader to download them. |
| One model object | Built once in `backend/model_provider.py`, shared by all five agents | Exactly one place a model name can enter the system, and it reads from `app/config.py`. No agent file names a model. |
| Token ceilings | pydantic-ai `UsageLimits`, never `max_tokens` | This model rejects `max_tokens` and wants `max_completion_tokens`. `UsageLimits` counts client-side and sends nothing on the wire, so it sidesteps the incompatibility *and* bounds the whole delegation tree rather than one response. |
| Shared budget | One `RunUsage` threaded through every nested call | A budget spent three delegations deep is visible at the top. Per-agent budgets would let a run cost five times its cap. |
| Delegation limits | depth 2, six per ticket, cycle guard on the call stack | Any-to-any connectivity can cycle, and each hop re-sends a system prompt and tool schemas. Limits are enforced in `agents.py`, not requested in a prompt. |
| Refused delegation | Returns an explanatory dict, never raises | The caller reads the refusal, learns it must answer with what it has, and finishes. A crashed run is a worse failure than a narrower answer. |
| Per-agent tool allowlists | 5–8 tools each, filtered from one shared toolset | Safety and cost at once. Customer service cannot call `pay_invoice` because the tool is invisible to it; and a schema re-sent on every request across five agents is real money. |
| Prompts as Markdown | One file per agent in `backend/prompts/`, with `{policy}` and `{team}` substituted at load | A prompt is prose and should be editable and diffable as prose. The tokens keep policy numbers single-sourced, so what an agent is told cannot drift from what the tools enforce. |
| Structured returns | `SpecialistReport` / `TicketOutcome` | Stops the boss re-reading and re-interpreting prose it already paid for. `facts_used` makes a recommendation checkable against the database. |
| Audit format | JSON array, atomic replace per write | The assignment names the file `.json`, so a reader should be able to `json.load` it in one call. At hundreds of rows the rewrite cost is irrelevant; at millions, JSON Lines would be the right change. |
| Audit writes directly to disk | Not through MCP | The no-second-layer rule is about *shop facts*. The trail is observability, not shop state, and routing it through a tool would put the logger inside the thing it logs. |
| Runner reads the board over MCP | `list_open_tickets`, not SQL | The orchestrator obeys the same rule as the agents. One path to the data, including for bookkeeping. |

## Cash reserve: which spend it binds

The $250 reserve from Problem 1 and the actual board are in direct conflict.
Rent ($2,400) plus invoice 501 ($840) is $3,240 against $3,400, leaving **$160 —
below the reserve**. Read literally, the reserve forbids paying the second
obligation.

That reading would have the agents refuse rent to protect a cash cushion, losing
the premises to save $90. So:

> The reserve binds **discretionary** spend — new purchase orders. **Contractual
> obligations** already owed may be paid down to zero, never below it.

Enforced by the `discretionary` flag on `_spend_guard` in
`mcp_server/server.py`, and documented at the constant in `app/policy.py`. The
hard invariant — no negative balance, ever — is unchanged and applies to both.

## Model-guard variants

The guard failed after the first live runs on forty "violations", every one of
them `gpt-6-luna-2026-09-22` (the dated snapshot the API returns in each
response, written against every audit row) plus one `gpt-6-luna-global` inside a
quoted Azure error message.

Neither is a second model — both are the permitted model under a name the
provider chose and we cannot control. The guard now accepts
`gpt-6-luna-<suffix>` and **prints the variants it found** rather than silently
widening, so the check stays honest about what it saw. It was re-verified by
planting a file naming a different model family and confirming the guard still
fails — that temporary file was deleted, and this document deliberately does not
quote the identifier, because the guard scans Markdown too.

## Decided in Problem 7 (backend routes)

| Decision | Choice | Why |
|---|---|---|
| Approval write | The **only** direct SQL in the backend | There is no MCP tool that approves anything, because the strongest form of "no agent may approve its own request" is that the capability is absent from the tool surface. Approval must therefore enter from outside the agent system. Only the decision fields are touched. |
| Approval execution | Straight back through MCP | `pay_invoice` / `pay_rent` / `confirm_purchase_order` re-check approval genuineness, scope, balance and double-payment. Approving records a decision; it does not grant an exemption. |
| Refusal reporting | Returned honestly as `executed: false` | A route that reported success because the human clicked approve would be lying about the shop's cash. Tested with a $5,000 approval against a $1,000 balance. |
| Run execution | Backgrounded, returns `run_id` | 15–35 s of model time per ticket. Blocking that long makes a dashboard look broken. `?wait=true` for curl. |
| Run concurrency | One in-flight run per ticket (409 otherwise) | Two agents on one ticket would race each other's writes. |
| `/reset` during a run | Refused with 409 | Resetting mid-run pulls the board out from under a working agent. |
| `/reset` and the audit trail | Trail kept by default; `?clear_audit=true` **archives**, never deletes | The trail is append-only history across runs. Wiping it on every reset would destroy the evidence of what the agents did. |
| `/events` default shape | `model_request` rows hidden | One row per round-trip carrying only token counts is noise on a timeline. Opt back in with a flag. |
| New MCP tools | `list_tickets`, `confirm_purchase_order` — on **no** agent allowlist | Both are human-side. `list_open_tickets` stays the boss's view because a work queue should not include an archive. |

## Decided in Problem 8 (the dashboard)

| Decision | Choice | Why |
|---|---|---|
| Casting | Each agent is the character who already does that job on the show | Makes the theme the legend. You learn the inventory agent's role by recognising David, not by reading a label. |
| Moira | **Not an agent** — she presides over approvals | No agent may approve anything, and no MCP tool can. Giving that boundary a face makes the system's most important rule visible. |
| Colour | Identity only — character colours, plum for "a human must act", green for "live" | Colour that means something stays readable. Colour applied for prettiness stops carrying information. |
| All five agents always on screen | Dimmed until they appear in the run | Shows who was *not* needed. A roster of only-active agents would hide the most interesting contrast between tickets. |
| Feed filtering | Hide `final_result` / `delegate`; hide tool results **except refusals** | The first two are framework mechanics, not things a person did. A refusal is the most interesting event that can occur. |
| Layout | One screen, three columns, no routing or modals | A desk should show everything at once. A modal would hide the ledger at the moment you most want to see it. |
| `payload_ref` lives in `app/` | Shared by the FastAPI route and the MCP guardrail | They enforce two halves of one rule; separate copies would eventually disagree. See below. |
| Ticket closing | The approve route closes a ticket when nothing is left pending | Agents cannot know what a human will decide, so they correctly stop at `waiting_approval`. Something still has to finish the job. |
| Audit history in the UI | Only loaded for non-`open` tickets, and only the latest run | The trail is append-only across resets, so a reset ticket would otherwise show beats from a run that no longer applies. |

## The approval-payload bug

Worth recording in full, because the naive fix would have been wrong.

The accounting agent wrote `{"tool": "pay_invoice", "invoice_id": 501}` where
the prompt asked for `ref_id`. Two failures followed:

1. **The payment silently did nothing.** The backend read only `ref_id`, got
   `None`, and passed `invoice_id=None` to the pay tool — while still reporting
   that a decision had been recorded.
2. **Scope enforcement vanished.** `_check_approval` compared
   `payload["ref_id"]` against the obligation being paid, and `None` compared
   equal to "no constraint". An approval spelled any other way therefore
   authorised *anything*, and could have been replayed against a larger
   obligation.

The fix is `app/payloads.py`: one `payload_ref` resolving `ref_id`,
`invoice_id`, `lease_id`, `purchase_order_id` and `po_id`, imported by both the
route and the guardrail so they cannot disagree. An approval with **no**
resolvable reference is now refused — "unknown scope" must never be read as
"unlimited scope".

**Tightening the prompt would not have been a fix.** The model is free to write
whatever payload it likes; correctness has to live in code that does not depend
on it choosing well.

## Decided in Problem 9 (the full run)

| Decision | Choice | Why |
|---|---|---|
| Audit filename | `audit_trail.json`; old rows migrated, `audit_train.json` deleted | Problem 5 said `audit_train`, Problem 9 said `audit_trail`. Treated as a typo correction, not a request for a second file. Two trails that disagree are worse than either alone. |
| Run id | Minted by the API, passed into `run_ticket` | Two ids for one run meant `GET /events?run_id=` could never match what the dashboard had been handed. |
| `waiting_approval` with nothing pending | Refused by `update_ticket` | The mirror of the existing rule. A ticket blocked on a request nobody made can never be cleared. |
| `declined` | Only for *requests*, never for an obligation already incurred | The boss declined the shop's own rent when first told it had to reach a verdict. Rent is not a request the shop may refuse. |
| Stale resolutions | The approve route appends what the decision did | A ticket reading "no payment has been made" after $2,400 was paid is worse than no resolution at all. |
| Payment attribution | Through the run capture's ledger, not payload matching | Ticket 103 also raised a request against invoice 501, so matching on the reference credited one payment to two tickets. |
| Cash reconciliation | Always against `cash_accounts`, never accumulated | Both arithmetic bugs below were caught this way and only this way. |

## Closing a ticket turns on the queue, not on success

Found when the approvals were clicked by hand rather than scripted.

Ticket 103's fourth request was approved by a human and then **refused** by
`pay_invoice`, because invoice 501 had already been settled by approval #1. The
approve route only closed a ticket when the execution *succeeded*, so the
refusal skipped the close — leaving ticket 103 at `waiting_approval` with
nothing pending. That is precisely the unreachable state `update_ticket` had
been taught to reject one problem earlier: a ticket blocked on a human who has
already decided everything.

A refusal **is** a decision. The route now closes on whether anything remains
pending for that ticket, regardless of whether this particular execution did
anything, and `_settlement_sentence` says plainly when a tool declined to
execute something a human approved rather than implying money moved.

**Why the scripted pass missed it:** the script approved in priority order and
the refusal happened to land last, so the ticket it stranded was closed by a
later re-run before anyone looked. Driving the real UI, one click at a time, is
what surfaced it.

## Two cash bugs, both in the checking code

Recorded because they are the exact failure mode the assignment warns about,
and because both were in the *verification*, not the application.

1. **A discount counted as spending.** Approval #3 approved a bulk price of
   $36.67/unit — a headline figure of $733.40 for 20 units. The checker summed
   approval amounts and reported an ending balance of **−$573.40** against a
   database reading **$160.00**. A discount is a price; it debits nothing. The
   checker now sums only approvals that produced a payment row.

2. **One payment credited to two tickets.** Ticket 103 raised its own request
   to pay invoice 501, which 101 had already settled. Matching payments to
   tickets by the payload's reference credited the same $840 twice, so
   per-ticket figures summed to $4,080 against $3,240 actually spent.
   Attribution now runs through the ledger, which records which approval
   produced which payment row.

Neither was visible from the board — every ticket showed `resolved` both times.
Only reconciling against `cash_accounts` caught them.

**The structural gap behind the second one:** `payments` has no `approval_id`
column, so there is no first-class link from a payment back to the approval
that authorised it. The run capture stands in for it. Adding that column is the
right fix and is left as a known gap rather than a silent one.

## Decided in the post-submission audit

Found by auditing the pushed repository against the assignment pages.

| Decision | Choice | Why |
|---|---|---|
| Agent narration in `resolved_tickets.json` | Read `content`, not `said` | `contributions()` in `scripts/build_outputs.py` looked for a `said` key that audit rows never had — the agent's words are written under `content` on `delegation_result` and `run_end`. All nine contributions had serialised as `"said": null` while the text sat in the trail the whole time. Regenerating changed exactly nine lines and left the arithmetic check at `matches: true`. |
| A customer draft is a closing condition | Hardened `backend/prompts/boss.md` | Ticket 101 diagnosed exactly why the shop could not help a named customer and then drafted nothing. The instruction existed but was conditional ("when a person is waiting"), which the boss read as discretionary against a prompt that elsewhere pushes delegation counts down. It is now owed to any ticket with a `requester`, checked before close, and explicitly worth going past the usual delegation count for. |

**The board was reset and re-run to prove the prompt fix.** Ticket 101 now
delegates to customer service and writes draft #1 to Tauhid Zaman. Everything
downstream was rebuilt from that run: `resolved_tickets.json`, the Actual
sections, the Cash tab, the Reflection, and three fresh board screenshots. The
ledger still reconciles to $160.00.

| Follow-on decision | Choice | Why |
|---|---|---|
| Prompt edits need a server restart | Restart before any run that is meant to test a prompt | `backend/prompts.load()` is `lru_cache`'d and `build_team()` runs once at startup, so a server started before an edit keeps the old prompt in memory. The first re-run was driven by a two-hour-old process and was discarded for exactly this reason. |
| Figures in the write-up are derived, not typed | `run_shape()` in `fill_reflection.py`; discount read from the approval payload in `fill_desk_tickets.py` | The re-run changed the discount from $36.67/unit to $40.00/unit and the tool-call counts with it. Anything hardcoded silently went stale. Counts now come from `audit_trail.json` and prices from the approval that was actually granted. |
| Plan-vs-run verdicts stay hand-written | `SCORECARD` in `fill_desk_tickets.py` | Whether a prediction "held" is a judgement about meaning, not a string comparison. It is re-scored by hand each run, which is why 101 flipped from *wrong* to *right* on the customer draft and 103 flipped the other way on the purchase order. |

**What the re-run cost elsewhere.** Two things improved unprompted: every ticket
closed in a single pass, and customer service started delegating to other
specialists directly rather than always reporting to the boss. One thing got
weaker: ticket 103 never called `create_purchase_order` at all, where the
earlier run put it to the tool and had it refused. Same conclusion, less
evidence. Recorded rather than smoothed over.

**One caveat on the approvals.** The earlier pass's approvals were clicked by
hand in the dashboard. This pass's were executed by `scripts/full_run.py`
against the same human approve route, in payment-priority order, with
`decided_by` set to the shop owner. No agent can reach that route either way, so
the boundary holds — but these `decided_by` values came from the script rather
than a click.

## Standing working rules

Instructions given once that apply to every problem from here on.

| Rule | Detail |
|---|---|
| **Document without being asked** | Finishing a problem includes updating `AI_prompts.md`, `output/harness.md`, and this file. No confirmation step — documentation is part of the work, not an offer made after it. |
| **Report failures plainly** | If something did not work, say so and show why. Never substitute an adjacent passing result for the one that was actually requested. |
| **Reset before a full run** | `python scripts/init_working_db.py` before any end-to-end ticket-resolution run, and raise it unprompted when a run is imminent. |
| **One model** | `gpt-6-luna` through Portkey, everywhere. `scripts/check_model_guard.py` before commits. |
| **Hard invariants** | Human approval on every payment; no negative cash balance; nothing sent to a real customer, vendor, or landlord. |
