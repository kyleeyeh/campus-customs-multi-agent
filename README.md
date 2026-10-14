# Campus Customs — Multi-Agent Operations

Kyle Yeh · MGT 403 Homework 5

A small campus apparel shop run by a team of five AI agents, with a human in the
loop for anything that moves money.

Three pieces talk to each other:

- an **MCP server** that owns every fact about the shop,
- a **FastAPI backend** driving five [pydantic-ai](https://ai.pydantic.dev)
  agents, all running `gpt-6-luna` through Portkey,
- a **React dashboard** where a person watches the team work and approves
  payments.

Every agent reaches the shop through MCP tools. Nothing in the backend opens the
database to answer a question, so there is exactly one place the shop's rules
are enforced.

**The headline result:** the three tickets on the board were worked to
resolution, the agents moved **$0.00**, and the $3,240.00 that did move went
through a human clicking Approve. Starting balance $3,400.00, ending balance
**$160.00**, reconciled against `cash_accounts`. See
[`output/desk_tickets.html`](output/desk_tickets.html).

---

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env          # then paste your Portkey key into it
cd frontend && npm install && cd ..
```

Then, in two terminals:

```bash
# terminal 1 — backend (also starts the MCP server for you)
cd backend && uvicorn main:app --reload --port 8000

# terminal 2 — the dashboard
cd frontend && npm run dev
```

Open **http://localhost:5173**. Pick a ticket, press **Send in the team**, watch
the agents work, then approve what they park with Moira.

You do not need to start the MCP server yourself — the backend launches it as a
subprocess over stdio and shares one connection across all five agents. To run
it standalone (for inspection, or to let a different MCP client connect):

```bash
python mcp_server/server.py
```

`.mcp.json` at the repo root registers it for MCP-aware editors.

---

## The database

```
data/campus_customs.db       pristine original — NEVER written to
data/campus_customs_new.db   the working copy — everything happens here
```

Both are committed. The working copy ships **as the agents left it**, so you can
clone this repo and immediately see three resolved tickets and a $160.00
balance without running anything.

### Copy the original over the working copy for a clean run

```bash
python scripts/init_working_db.py
```

This copies `campus_customs.db` over `campus_customs_new.db` and re-applies the
added tables (`approvals`, `purchase_orders`, `drafts`, `agent_messages`,
`runs`). The original is only ever read, so this is always safe and always
returns you to the exact board the assignment shipped: three open tickets,
$3,400.00, no payments.

```bash
python scripts/init_working_db.py --migrate   # apply schema, keep current data
```

There is also a **Reset the shop** button on the dashboard, and a
`POST /reset` route, both of which run the same script.

### Reset before a full three-ticket run

**Do this every time.** A full run writes approvals, drafts, payments and ticket
statuses. Run it twice without resetting and the second pass sees a board the
first one already changed — tickets are already resolved, invoices already paid,
and the cash arithmetic will not reproduce.

```bash
python scripts/init_working_db.py     # <- reset FIRST
python scripts/full_run.py            # runs 101, 102, 103 and approves
```

`scripts/full_run.py` needs the backend already running on port 8000. It
deliberately does **not** reset by itself, so the board is never wiped without
someone meaning it.

To drive the run by hand instead, which is what produced the committed result:

```bash
python scripts/init_working_db.py
# start the backend and the dashboard, then from the board:
#   Send in the team on each ticket, then approve each request as Moira
```

---

## Everything you can run

| Command | What it does |
|---|---|
| `cd backend && uvicorn main:app --reload --port 8000` | API + agents + MCP server |
| `cd frontend && npm run dev` | the dashboard on :5173 |
| `python scripts/init_working_db.py` | reset the working copy from the original |
| `python scripts/full_run.py` | work all three tickets and approve (backend must be up) |
| `python scripts/test_guardrails.py` | 19 safety checks, no model calls — **resets the DB** |
| `python scripts/check_model_guard.py` | fail if any model but `gpt-6-luna` appears |
| `python scripts/inspect_db.py --tickets` | read-only look at the board |
| `python -m backend.team --list` | the board over MCP, no model calls |
| `python -m backend.team --ticket 101` | run one ticket from the command line |

---

## The team

| Agent | Played by | Owns |
|---|---|---|
| boss | Johnny Rose | Routing and the final call. The only agent that can close a ticket. |
| inventory | David Rose | Stock, shortfalls, restock sourcing. |
| accounting | Patrick Brewer | Cash, margins, invoices. Pays vendor invoices. |
| facilities | Stevie Budd | The premises. Pays rent. |
| customer_service | Alexis Rose | Drafts what the shop says. |

**Moira Rose is deliberately not an agent.** She presides over approvals — the
one thing no agent may do. Prompts are one file per agent in
[`backend/prompts/`](backend/prompts/).

---

## The rules, enforced in code

Not asked for in a prompt — enforced in the MCP server, where an agent cannot
talk its way past them:

- **Every payment needs a named human.** `pay_invoice` and `pay_rent` refuse
  unless an approval row is already `approved` and carries a `decided_by`.
- **No agent can approve anything.** There is no approve tool on the server.
- **An approval authorises one obligation**, and an approval whose scope cannot
  be determined is refused rather than treated as unlimited.
- **No negative balance, ever.** Checked inside the write transaction.
- **The $250 reserve binds discretionary spend only** — rent is never refused to
  protect a cash cushion.
- **Nothing is paid twice.**
- **Nothing is ever sent.** There is no send tool, and `drafts` has no `sent`
  status.

```bash
python scripts/test_guardrails.py    # 19/19, deterministic, no model calls
```

---

## Layout

```
.
├── app/              config, DB access, shop policy, approval-payload parsing
├── backend/          FastAPI + the five agents
│   ├── main.py       API routes (the approve route is what moves money)
│   ├── agents.py     the team and any-to-any delegation
│   ├── models.py     typed boundaries
│   ├── team.py       the runner
│   └── prompts/      one Markdown prompt per agent
├── mcp_server/       the 17 tools every agent uses
├── frontend/         React + Vite + TypeScript dashboard
├── scripts/          reset, full run, guardrail tests, model guard
├── data/             both database files
├── docs/             design decisions and why
└── output/           the write-ups and the evidence
```

### Where to look first

| File | |
|---|---|
| [`output/desk_tickets.html`](output/desk_tickets.html) | **Start here.** The plan, what actually happened, the itemised cash, and the reflection. |
| [`output/resolved_board.html`](output/resolved_board.html) | Screenshots of the dashboard for each resolved ticket. |
| [`output/harness.md`](output/harness.md) | Tables, tools, agents, routes, dashboard, safety rules. |
| [`output/resolved_tickets.json`](output/resolved_tickets.json) | Machine-readable outcome per ticket. |
| [`output/audit_trail.json`](output/audit_trail.json) | Every agent step across every run, append-only. |
| [`AI_prompts.md`](AI_prompts.md) | Every prompt typed while building this. |
| [`docs/decisions.md`](docs/decisions.md) | The decisions and the bugs behind them. |
| [`output/design.md`](output/design.md) | Why the dashboard looks the way it does. |

---

## One model

Every agent runs `gpt-6-luna` through Portkey. One place can name a model —
[`app/config.py`](app/config.py) — and `scripts/check_model_guard.py` scans the
repo to keep it that way. Two gotchas cost real time and are documented in
[`backend/model_provider.py`](backend/model_provider.py): this model rejects
`max_tokens`, and it refuses function tools unless `reasoning_effort` is
`'none'`.

## Secrets

`.env` is gitignored and is not in this repository. Copy `.env.example` to
`.env` and add your own `PORTKEY_API_KEY`. Nothing here will run without one.
