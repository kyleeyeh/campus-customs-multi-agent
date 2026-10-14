"""FastAPI backend for the Campus Customs dashboard.

Start it from the `backend/` folder:

    uvicorn main:app --reload --port 8000

Interactive docs at http://localhost:8000/docs

WHERE THE DATA COMES FROM
-------------------------
Every shop fact served here is read through the MCP server over
`data/campus_customs_new.db` — the same tool layer the agents use. The backend
does not open SQLite to answer a question. One path to the data means one place
enforcing the shop's rules.

There is exactly one deliberate exception, and it is the whole point of this
problem: **recording a human's approval decision**. No MCP tool can approve
anything, because no agent may ever approve anything — not even its own request.
So the approval write enters from outside the agent tool surface entirely, as a
single targeted UPDATE in `_record_human_decision` below. Once the decision is
recorded, the *execution* goes straight back through MCP (`pay_invoice`,
`pay_rent`, `confirm_purchase_order`), so every rule about overdrafts, double
payments and approval scope still applies.

Put plainly: agents prepare payments, this backend is what actually moves money,
and the MCP tools still get to refuse.

RUNS ARE SLOW, SO THEY ARE BACKGROUNDED
---------------------------------------
A ticket takes 15–35 seconds of model time. Blocking an HTTP request that long
makes for a dashboard that looks broken, so `POST /tickets/{id}/run` returns
immediately with a `run_id` and the work continues in the background. The board
polls `GET /events` to watch it happen. Pass `?wait=true` to block instead,
which is convenient from curl.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import subprocess
import sys
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

# Allow `uvicorn main:app` from inside backend/ to import the backend package.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.config import APPROVER_NAME, WORKING_DB
from app.payloads import payload_ref
from backend.agents import build_team
from backend.audit import AUDIT_PATH, read_trail, summarise
from backend.mcp_client import build_toolset
from backend.model_provider import model_name
from backend.models import RunBudget
from backend.team import run_ticket

# ---------------------------------------------------------------------------
# App state
# ---------------------------------------------------------------------------
BUDGET = RunBudget()

# One in-flight run per ticket. A dashboard with an eager button should not be
# able to start the same ticket three times.
_runs: dict[str, dict[str, Any]] = {}
_active_tickets: set[int] = set()
_run_lock = asyncio.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the MCP server once for the life of the process, and build the team.

    Starting a server per request would pay the handshake cost on every call and
    open a new SQLite connection each time.
    """
    toolset, client = build_toolset()
    async with toolset:
        app.state.toolset = toolset
        app.state.client = client
        app.state.team = build_team(toolset)
        yield


app = FastAPI(
    title="Campus Customs Operations API",
    description=(
        "Backend for the agent dashboard. Shop data is served through the MCP "
        "server; approvals are the one human-only write."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# The dashboard runs on its own dev-server port in the next problem.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# MCP plumbing
# ---------------------------------------------------------------------------
def _unwrap(result: Any) -> Any:
    """FastMCP wraps a bare return value under a `result` key."""
    data = getattr(result, "structured_content", None)
    if isinstance(data, dict):
        return data.get("result", data)
    if getattr(result, "data", None) is not None:
        return result.data
    return data


async def mcp(tool: str, **args: Any) -> Any:
    """Call one MCP tool and return its unwrapped payload."""
    return _unwrap(await app.state.client.call_tool(tool, args))


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------
class ApprovalDecision(BaseModel):
    """What a human sends when they click Approve or Reject."""

    decision: Literal["approved", "rejected"] = "approved"
    decided_by: str = Field(
        default=APPROVER_NAME,
        description="Name of the human deciding. Written to payments.approved_by.",
    )
    note: str | None = Field(default=None, description="Optional reason.")


class RunStarted(BaseModel):
    run_id: str
    ticket_id: int
    status: str
    message: str


# ---------------------------------------------------------------------------
# 1. The board
# ---------------------------------------------------------------------------
@app.get("/tickets", summary="Every ticket and whether it is open or resolved")
async def get_tickets() -> dict[str, Any]:
    """The whole board, including tickets already resolved or declined.

    Each ticket carries `is_open` / `is_resolved` so the dashboard does not have
    to know the status vocabulary, plus any approvals still pending on it.
    """
    board = await mcp("list_tickets")
    return {
        "shop_date": board["shop_date"],
        "count": board["count"],
        "open": sum(1 for t in board["tickets"] if t["is_open"]),
        "resolved": sum(1 for t in board["tickets"] if t["is_resolved"]),
        "tickets": board["tickets"],
    }


@app.get("/tickets/{ticket_id}", summary="One ticket with everything it links to")
async def get_one_ticket(ticket_id: int) -> dict[str, Any]:
    result = await mcp("get_ticket", ticket_id=ticket_id)
    if "error" in result:
        raise HTTPException(404, result["error"])
    return result


# ---------------------------------------------------------------------------
# 2. Run the agent team on a ticket
# ---------------------------------------------------------------------------
async def _execute_run(run_id: str, ticket_id: int, shop_date: str) -> None:
    """The background body of a run. Never raises — failures land in the record."""
    try:
        result = await run_ticket(app.state.team, ticket_id, shop_date, BUDGET, run_id=run_id)
        _runs[run_id].update(
            status="failed" if result.error else "done",
            finished_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            result=result.model_dump(mode="json"),
            error=result.error,
        )
    except Exception as exc:  # noqa: BLE001 - a crashed run must still be reportable
        _runs[run_id].update(
            status="failed",
            finished_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            error=f"{type(exc).__name__}: {exc}",
        )
    finally:
        _active_tickets.discard(ticket_id)


@app.post(
    "/tickets/{ticket_id}/run",
    summary="Run the agent team on one ticket",
    response_model=None,
)
async def run_agents(
    ticket_id: int,
    background: BackgroundTasks,
    wait: bool = Query(False, description="Block until the run finishes instead of polling."),
) -> dict[str, Any]:
    """Hand a ticket to the boss agent.

    Returns immediately with a `run_id`; poll `GET /events` or
    `GET /runs/{run_id}` to watch. A ticket already being worked is rejected
    rather than queued — two agents on one ticket would race each other's writes.

    Agents can park approvals, write drafts and set ticket status. They cannot
    move money: that needs `POST /approvals/{id}/approve`.
    """
    board = await mcp("list_tickets")
    known = {t["id"] for t in board["tickets"]}
    if ticket_id not in known:
        raise HTTPException(404, f"No ticket with id {ticket_id}. Board has {sorted(known)}.")

    async with _run_lock:
        if ticket_id in _active_tickets:
            raise HTTPException(409, f"Ticket {ticket_id} is already being worked.")
        _active_tickets.add(ticket_id)

    run_id = f"run-{ticket_id}-{uuid.uuid4().hex[:8]}"
    _runs[run_id] = {
        "run_id": run_id,
        "ticket_id": ticket_id,
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": model_name(),
    }

    if wait:
        await _execute_run(run_id, ticket_id, board["shop_date"])
        return _runs[run_id]

    background.add_task(_execute_run, run_id, ticket_id, board["shop_date"])
    return RunStarted(
        run_id=run_id,
        ticket_id=ticket_id,
        status="running",
        message="Run started. Poll /events or /runs/{run_id}.",
    ).model_dump()


@app.get("/runs/{run_id}", summary="Status and result of one run")
async def get_run(run_id: str) -> dict[str, Any]:
    if run_id not in _runs:
        raise HTTPException(404, f"No run {run_id} in this process.")
    return _runs[run_id]


@app.get("/runs", summary="Runs started since the server booted")
async def list_runs() -> dict[str, Any]:
    return {"count": len(_runs), "runs": list(_runs.values())}


# ---------------------------------------------------------------------------
# 3. Recent agent activity
# ---------------------------------------------------------------------------
# Rows the board cares about. `model_request` is omitted by default: it is one
# row per round-trip carrying only token counts, which is noise on a timeline.
BOARD_EVENTS = {
    "run_start",
    "delegation",
    "delegation_result",
    "tool_call",
    "tool_result",
    "budget_refused",
    "error",
    "run_end",
}


@app.get("/events", summary="Recent agent events — who said what, which tools ran")
async def get_events(
    limit: int = Query(80, ge=1, le=1000),
    since_seq: int | None = Query(None, description="Only events after this seq, for polling."),
    run_id: str | None = None,
    ticket_id: int | None = None,
    include_model_requests: bool = Query(
        False, description="Include per-round-trip token rows."
    ),
) -> dict[str, Any]:
    """The audit trail, shaped for a board that refreshes.

    Read from `output/audit_trail.json`, which the agents append to as they work.
    Each event says which agent acted, what it said or which tool it called, and
    at what delegation depth — which is what lets the dashboard draw the
    delegation path rather than just the final answer.

    Poll with `since_seq` set to the highest `seq` you have already drawn.
    """
    rows = read_trail(run_id)

    if ticket_id is not None:
        rows = [r for r in rows if r.get("ticket_id") == ticket_id]
    allowed = BOARD_EVENTS | ({"model_request"} if include_model_requests else set())
    rows = [r for r in rows if r.get("event") in allowed]
    if since_seq is not None:
        rows = [r for r in rows if r.get("seq", 0) > since_seq]

    recent = rows[-limit:]
    return {
        "count": len(recent),
        "total_matching": len(rows),
        "latest_seq": max((r.get("seq", 0) for r in recent), default=since_seq or 0),
        "events": [
            {
                "run_id": r.get("run_id"),
                "seq": r.get("seq"),
                "ts": r.get("ts"),
                "ticket_id": r.get("ticket_id"),
                "event": r.get("event"),
                "agent": r.get("agent"),
                "to_agent": r.get("to_agent"),
                "depth": r.get("depth", 0),
                "tool_name": r.get("tool_name"),
                "tool_args": r.get("tool_args"),
                "tool_result": r.get("tool_result"),
                "said": r.get("content"),
                "model": r.get("model"),
                "error": r.get("error"),
            }
            for r in recent
        ],
    }


@app.get("/events/summary", summary="Counts over the whole audit trail")
async def events_summary() -> dict[str, Any]:
    return {"audit_file": str(AUDIT_PATH.name), **summarise()}


# ---------------------------------------------------------------------------
# 4. Approvals — the human decision, and the only thing that moves cash
# ---------------------------------------------------------------------------
@app.get("/approvals", summary="Approval requests the agents have parked")
async def get_approvals(status: str | None = None) -> dict[str, Any]:
    """What is waiting on a human. The dashboard's Approve buttons come from here."""
    result = await mcp("list_approvals", status=status)
    return result


def _settlement_sentence(kind: str, execution: dict[str, Any], who: str) -> str:
    """One sentence recording what the human's decision actually did.

    Appended to a ticket's resolution when the approval closes it, so the
    ticket's final word says what happened rather than what was pending.
    """
    amount = execution.get("amount")
    paid_at = execution.get("paid_at")
    balance = execution.get("new_balance")

    # A refusal is a decision too, and the ticket's final word must say so
    # rather than implying money changed hands. This is the line that appears
    # when a human approves something the tools then decline to do.
    if execution.get("refused") or "error" in execution:
        return (
            f"NOT EXECUTED: {who} approved this request, but the tool refused it — "
            f"{execution.get('error', 'see the run log')} No cash moved."
        )

    if kind == "payment" and amount is not None:
        target = (
            f"invoice {execution['invoice_id']}"
            if "invoice_id" in execution
            else f"rent on lease {execution.get('lease_id')}"
        )
        return (
            f"SETTLED: {who} approved payment of ${amount:,.2f} for {target} "
            f"on {paid_at}; checking balance is now ${balance:,.2f}."
        )
    if kind == "purchase_order":
        return (
            f"SETTLED: {who} approved purchase order "
            f"{execution.get('purchase_order_id')} "
            f"(${execution.get('total_cost', 0):,.2f}, expected "
            f"{execution.get('expected_date')}). No cash moved — a PO is a commitment."
        )
    if kind == "discount":
        return f"SETTLED: {who} approved the discount. No ledger entry."
    return f"SETTLED: {who} approved this request."


def _record_human_decision(approval_id: int, decision: str, who: str, note: str | None) -> None:
    """Write a human's decision onto an approval row.

    THE ONE DIRECT WRITE IN THIS BACKEND, and deliberately so. There is no MCP
    tool that can approve anything, because the strongest form of "no agent may
    approve its own request" is that the capability does not exist on the tool
    surface at all. Approval therefore enters from outside the agent system —
    here, from an HTTP request a human made.

    Only the decision fields are touched. Everything that happens *next* goes
    back through MCP, where the money guardrails live.
    """
    with sqlite3.connect(WORKING_DB) as conn:
        conn.execute(
            "UPDATE approvals SET status=?, decided_by=?, decided_at=datetime('now'), "
            "decision_note=? WHERE id=?",
            (decision, who, note, approval_id),
        )


@app.post("/approvals/{approval_id}/approve", summary="Approve a payment or purchase")
async def approve(approval_id: int, body: ApprovalDecision | None = None) -> dict[str, Any]:
    """Record a human decision and, if approved, actually execute it.

    This route is where cash changes. The agents only ever parked a request; the
    `payload` they stored says exactly what to replay, and this executes it
    through the MCP tool named there:

    | kind | executed by |
    |---|---|
    | `payment` → `pay_invoice` | `pay_invoice(invoice_id, approval_id)` |
    | `payment` → `pay_rent` | `pay_rent(lease_id, approval_id)` |
    | `purchase_order` | `confirm_purchase_order(po_id, approval_id)` |
    | `discount` | nothing mechanical — the decision *is* the outcome |

    The MCP tool re-checks everything even though this route just wrote the
    approval: it verifies the row really is approved, that the approval
    authorises *this* obligation, that the balance can take it, and that it has
    not already been paid. A refusal there is returned honestly rather than
    being smoothed over — if the shop cannot afford it, approving does not make
    it affordable.
    """
    body = body or ApprovalDecision()

    approvals = (await mcp("list_approvals"))["approvals"]
    row = next((a for a in approvals if a["id"] == approval_id), None)
    if row is None:
        raise HTTPException(404, f"No approval with id {approval_id}.")
    if row["status"] != "pending":
        raise HTTPException(
            409,
            f"Approval {approval_id} was already {row['status']}"
            + (f" by {row['decided_by']}." if row.get("decided_by") else "."),
        )

    _record_human_decision(approval_id, body.decision, body.decided_by, body.note)

    if body.decision == "rejected":
        return {
            "approval_id": approval_id,
            "decision": "rejected",
            "decided_by": body.decided_by,
            "executed": False,
            "note": "Nothing was paid. The ticket stays with the team.",
        }

    payload = json.loads(row.get("payload") or "{}")
    kind, tool = row["kind"], payload.get("tool")
    # The agent chooses its own payload keys and does not always pick `ref_id`
    # — the same request has arrived as `invoice_id` and as `lease_id`. Reading
    # one spelling meant passing None to the pay tool and silently doing
    # nothing. `payload_ref` resolves whichever it used.
    ref_id = payload_ref(payload)
    execution: dict[str, Any]

    if ref_id is None and kind != "discount":
        raise HTTPException(
            422,
            f"Approval {approval_id} has no obligation id in its payload "
            f"({sorted(payload)}); nothing to execute. The decision was recorded.",
        )

    if kind == "payment" and tool == "pay_invoice":
        execution = await mcp("pay_invoice", invoice_id=ref_id, approval_id=approval_id)
    elif kind == "payment" and tool == "pay_rent":
        execution = await mcp("pay_rent", lease_id=ref_id, approval_id=approval_id)
    elif kind == "purchase_order":
        po_id = payload.get("purchase_order_id", ref_id)
        execution = await mcp(
            "confirm_purchase_order", purchase_order_id=po_id, approval_id=approval_id
        )
    elif kind == "discount":
        execution = {
            "noted": True,
            "note": "Discount approved. No ledger entry — the price applies when the order is placed.",
        }
    else:
        execution = {
            "error": f"Approval {approval_id} has kind={kind!r} and payload tool={tool!r}; "
            "nothing to execute. The decision was still recorded.",
        }

    refused = bool(execution.get("refused")) or "error" in execution

    # Close the ticket once nothing is outstanding on it.
    #
    # The agents correctly leave a ticket at 'waiting_approval' — they cannot
    # know what a human will decide. Something still has to finish the job
    # after the decision, or a fully-settled ticket sits on the board asking
    # for an approval that has already happened.
    #
    # This turns on the state of the QUEUE, not on whether *this* execution
    # succeeded. Gating it on success stranded ticket 103 in a real run: its
    # second request was approved and then refused by the pay tool (the invoice
    # was already settled), so the close was skipped and the ticket sat at
    # 'waiting_approval' with nothing pending — exactly the unreachable state
    # `update_ticket` was taught to reject. A refusal is still a decision. What
    # matters is whether anything is left for a human to decide.
    closed = False
    still_pending = [
        a
        for a in (await mcp("list_approvals", status="pending"))["approvals"]
        if a["ticket_id"] == row["ticket_id"]
    ]
    if not still_pending:
        # Closing a ticket without updating its resolution leaves the
        # human-readable record contradicting reality: the agent wrote
        # "approval 1 is still pending" BEFORE a human decided, and that
        # sentence would survive as the ticket's final word after the money
        # had actually moved. The settlement is appended rather than
        # replacing the agent's analysis, which is still the useful part.
        current = await mcp("get_ticket", ticket_id=row["ticket_id"])
        prior = (current.get("ticket") or {}).get("resolution") or ""
        settled = _settlement_sentence(kind, execution, body.decided_by)
        resolution = f"{prior.strip()} {settled}".strip() if prior else settled

        result = await mcp(
            "update_ticket",
            ticket_id=row["ticket_id"],
            status="resolved",
            resolution=resolution,
        )
        closed = bool(result.get("updated"))

    cash = await mcp("get_cash_position")

    return {
        "approval_id": approval_id,
        "decision": "approved",
        "decided_by": body.decided_by,
        "kind": kind,
        "executed": not refused,
        "execution": execution,
        "ticket_closed": closed,
        "balance_after": cash["balance"],
        "note": (
            "Approved, but the tool refused to execute it. See `execution`."
            if refused
            else "Approved and executed. Cash has moved."
        ),
    }


# ---------------------------------------------------------------------------
# 5. Cash
# ---------------------------------------------------------------------------
@app.get("/cash", summary="Current checking balance and what is owed")
async def get_cash() -> dict[str, Any]:
    """The checking balance from `cash_accounts`, with its obligations.

    No revenue is modelled in this shop, so this number only ever falls.
    """
    pos = await mcp("get_cash_position")
    return {
        "account": pos["account"],
        "balance": pos["balance"],
        "shop_date": pos["shop_date"],
        "total_owed": pos["total_owed"],
        "remaining_if_all_paid": pos["remaining_if_all_paid"],
        "overdue_count": pos["overdue_count"],
        "obligations": pos["obligations"],
        "payments_made": pos["payments_made"],
    }


# ---------------------------------------------------------------------------
# 6. Reset
# ---------------------------------------------------------------------------
@app.post("/reset", summary="Reset the working database to the original values")
async def reset(
    clear_audit: bool = Query(
        False,
        description="Also archive the audit trail. Off by default — the trail is append-only history.",
    ),
) -> dict[str, Any]:
    """Rebuild `campus_customs_new.db` from the pristine original.

    The pristine `campus_customs.db` is never written to; this copies from it,
    so a fresh run starts from exactly the board the assignment shipped.

    The audit trail is **not** cleared by default. It is append-only history
    across runs, and wiping it on every reset would destroy the record of what
    the agents did. Pass `clear_audit=true` to archive it to a timestamped file
    — archived, not deleted.
    """
    if _active_tickets:
        raise HTTPException(
            409,
            f"Tickets {sorted(_active_tickets)} are mid-run. Resetting now would pull the "
            "board out from under them.",
        )

    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "init_working_db.py")],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise HTTPException(500, f"Reset failed: {proc.stderr.strip()}")

    archived = None
    if clear_audit and AUDIT_PATH.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        archived = AUDIT_PATH.with_name(f"audit_trail.{stamp}.json")
        AUDIT_PATH.replace(archived)

    _runs.clear()
    cash = await mcp("get_cash_position")
    board = await mcp("list_tickets")

    return {
        "reset": True,
        "detail": proc.stdout.strip().splitlines(),
        "balance": cash["balance"],
        "open_tickets": sum(1 for t in board["tickets"] if t["is_open"]),
        "audit_archived_to": archived.name if archived else None,
        "audit_note": (
            "Audit trail left intact (append-only history)."
            if not archived
            else f"Audit trail archived to {archived.name}."
        ),
    }


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.get("/health", summary="Is the backend up and is MCP answering")
async def health() -> dict[str, Any]:
    started = time.perf_counter()
    cash = await mcp("get_cash_position")
    return {
        "ok": True,
        "model": model_name(),
        "mcp": "connected",
        "mcp_latency_ms": int((time.perf_counter() - started) * 1000),
        "shop_date": cash["shop_date"],
        "balance": cash["balance"],
        "active_runs": sorted(_active_tickets),
    }
