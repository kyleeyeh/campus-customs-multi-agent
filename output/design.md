# The Rosebud Operations Desk — design notes

**Campus Customs Multi-Agent Operations** · Kyle Yeh · MGT 403 Homework 5

What the dashboard looks like, why it looks that way, and the creative choices
that are doing real work rather than decorating.

Run it:

```bash
cd frontend && npm run dev          # http://localhost:5173
```

It expects the backend from Problem 7 at `http://localhost:8000`.

---

## The conceit

This is the front desk of a small-town motel that happens to run an apparel
shop. Warm paper, a green neon sign, a brass ledger, and five people who dress
very differently from one another.

That framing was not chosen because Schitt's Creek is funny. It was chosen
because **a motel front desk is genuinely the right metaphor for this
application**. Someone sits at it. Work arrives whether they want it or not.
They hand things to whoever handles that, they watch, and periodically they are
the only one who can authorise something. That is exactly what this dashboard
is for, so the theme and the function point in the same direction instead of
fighting each other.

## Layout: one screen, three columns

```
┌──────────────────── ROSEBUD · the sign / status bar ────────────────────┐
│  THE BOARD      │  THE CAST (five, always visible)   │  THE LEDGER      │
│  3 tickets      │                                    │  $1,000.00       │
│  pick one       │  ON THE FLOOR                      │  obligations     │
│                 │  live feed of who did what         │                  │
│  [Send in the   │                                    │  AWAITING MOIRA  │
│   team]         │  HOW IT WENT                       │  approve/decline │
│  reset          │  per-agent summary after the run   │                  │
└─────────────────┴────────────────────────────────────┴──────────────────┘
```

No routing, no tabs, no modals. **A desk you sit at should show you everything
at once.** The three columns map to the three questions a person actually has:
*what needs doing*, *what is happening*, *what is it costing me and what do I
have to decide*. Clicking a ticket never navigates away from any of that.

Reading order left-to-right matches the order the work flows: ticket → agents →
money. The one thing demanding human action sits bottom-right, which is where a
right-handed person's hand already is.

## How the agents read differently

Each agent is played by the character who **already does that job on the show**.
This is the fastest legend the interface has: once you know David runs a shop
and panics about empty shelves, you know what the inventory agent does without
reading its label.

| Agent | Character | Why them |
|---|---|---|
| boss | **Johnny Rose** | Ran a business, now runs a small one. Makes the final call, delegates the rest. |
| inventory | **David Rose** | Rose Apothecary is his. Curates stock, is personally offended by a shortfall. |
| accounting | **Patrick Brewer** | He literally does the books at the shop. Calm, and says the uncomfortable number out loud. |
| facilities | **Stevie Budd** | Runs the motel. The property, the lease and the landlord are hers. |
| customer service | **Alexis Rose** | PR background. Writes the charming note that doesn't promise anything. |

**Moira Rose is deliberately not an agent.** She presides over approvals — the
one thing no agent on this team is permitted to do. No MCP tool can approve
anything; the capability does not exist on the agent tool surface. Giving that
boundary a face makes it obvious rather than a footnote, and it is the single
most important rule in the whole system. Her panel is the only one with its own
colour, its own serif voice, and a named person attached.

Each character's colour comes from how they actually dress — Johnny's navy
suits, David's black-and-white knitwear, Patrick's blue button-downs, Stevie's
olive flannel, Alexis's blush, Moira's plum. That colour then identifies them
everywhere: avatar, the left border of their lines in the feed, their name in
the ticket list, their chip in the summary. Nothing is tinted just to look
pretty — **colour means identity**, consistently.

### All five are always on screen

The cast row shows everyone, dimmed to 58% until they appear in the run. This is
the most useful thing on the page: at a glance you can see that **ticket 102
only ever involved Stevie, while 101 pulled in four people.** A roster that only
rendered active agents would hide exactly that contrast — and the shape of the
delegation is the interesting part of a multi-agent system.

The agent currently working gets a glowing ring, three bouncing dots, and a line
of narration in their own voice (`counting what's actually on the shelf…`).
Finished agents stay lit and show the line they signed off with. Agents never
called stay dim and say something idle. Three states, no legend needed.

## The live feed

Delegation depth becomes **indentation**. A reply from someone a specialist
pulled in sits further right than the boss's own line, so the shape of the
conversation is visible before you read a word of it.

Three editorial filters keep it a conversation rather than a log dump:

- **Framework noise is removed.** pydantic-ai's `final_result` is how an agent
  returns its answer, and the `delegate` tool duplicates the handoff we already
  draw more legibly with an arrow. Neither is a thing a person did.
- **Tool results are hidden — except refusals.** The call says what happened;
  the result is a wall of JSON. But a refusal ("this payment would overdraw") is
  the most interesting thing that can occur, so those get their own amber
  treatment.
- **Tool calls are narrated in plain English**, with the raw tool name kept as a
  small chip beside it. `counting what's actually on the shelf` reads like work;
  `check_stock` keeps it auditable. You get both.

## Resolved tickets

A resolved ticket gets a **rotated rubber stamp**, not just a different pill
colour. The point is that the state of the board should be readable from across
the desk — you should be able to see what is done without reading any words.
Declined gets the same stamp in red.

The sign at the top keeps a running count (`2 open · 1 closed`), so the board's
state is also legible without looking at the board.

A ticket that is merely waiting on Moira reads **"needs Moira"** rather than
"waiting_approval". The dashboard never shows a raw status string; it says what
is actually true in words a shop owner would use.

## Cash

The balance is a **brass ledger**: monospace, right-aligned, ruled lines, warm
gold header. Monospace matters — figures should line up vertically when you
compare them, and a proportional font makes $2,400.00 and $840.00 hard to scan.

**When the balance falls it flashes red and shrinks back.** Cash only ever goes
down in this shop — no revenue is modelled — so a drop is always the most
consequential thing that has happened, and it earns the one piece of motion on
the page you cannot miss. The delta (`−$2,400.00`) sits under it.

Paid obligations stay in the list, struck through, with the name of the human
who approved them. A ledger you cannot read backwards isn't a ledger.

One honest detail: **"if every open obligation were settled" can go negative**,
and the panel says why. Once this month's rent is paid the lease rolls to the
next cycle, so a fresh rent obligation appears immediately. The number is
correct and it is telling you the shop cannot cover what is ahead of it — which
is the actual situation on this board, and not something to hide behind a
friendlier figure.

## The approval panel

The only place a human must act, so it gets the strongest visual separation on
the page: plum border, plum header, Moira's portrait and her voice in italic
serif.

Each request shows the amount large, the summary a human can decide on without
reading the thread, the agent's own rationale in quotes, and **who asked** in
that character's colour. Approve and Decline, nothing else.

Crucially: **when the backend approves but the tool then refuses** — a payment
that would overdraw — this panel reports the refusal, not the approval. Clicking
Approve is permission, not a guarantee. Pretending otherwise would be the one
genuinely dangerous lie this interface could tell, so the verdict box turns red
and quotes the tool's own words.

## The sign is the status indicator

The neon `ROSEBUD` glows green and flickers faintly while the backend answers.
If uvicorn is not running, **the neon goes dark** and the vacancy line reads
"back office unreachable."

The one piece of pure decoration on the page is also the health check. You learn
the backend is down by looking at the thing you were already looking at, instead
of finding a grey error box in a corner.

## Typography

- **Bodoni Moda** for headings and character names — a high-contrast fashion
  serif. It is the typeface Moira would choose, and it gives section headers the
  feel of a printed card rather than a web app.
- **Inter** for everything a person reads quickly.
- **JetBrains Mono** for every figure, date and SKU — anything you might need to
  compare or check against the database.

Three families, three jobs, no overlap.

## Things that are deliberately absent

- **No charts.** Three tickets and one balance. A chart here would be decoration
  pretending to be analysis.
- **No dark mode.** The desk is a warm paper surface; a dark version would be a
  different, worse metaphor.
- **No modals.** Approving is two clicks in place. A modal would hide the ledger
  at the exact moment you most want to see it.
- **No toast notifications.** The ledger flashing and the stamp appearing *are*
  the notifications, and they appear where the change actually happened.

## What makes it enjoyable to sit at

The honest answer is that the theme gives the interface **a sense of humour that
never costs you information**. David's idle line is "The shelves are curated,
thank you." It is a joke, and it also tells you he is the stock agent and that
he has not been called yet. Moira's "I have no pending business. Bask in it."
tells you the queue is empty.

Every flourish does a second job:

| Flourish | What it also tells you |
|---|---|
| Neon flicker | backend is alive |
| Dimmed cast members | who was *not* needed on this ticket |
| Bouncing dots | which agent is mid-thought right now |
| Rotated stamp | the ticket is closed, visible from across the room |
| Red flash on the balance | money actually moved, just now |
| Plum everywhere | a human has to do something |
| Character colour on a feed line | who is talking, without reading the name |

A dashboard people enjoy is one that rewards a glance. Each of these is
glanceable, and each is load-bearing. That is the whole design, really: make the
decoration carry the information, and the thing stops feeling like a form you
have to operate and starts feeling like a desk you sit at.
