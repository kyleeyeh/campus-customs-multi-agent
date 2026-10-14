"""Run the Campus Customs agent team against the ticket board.

    python -m backend.team --ticket 101      # one ticket
    python -m backend.team --all             # every open ticket
    python -m backend.team --list            # read the board, no model calls

The runner owns the lifecycle: it starts the MCP server once, builds the five
agents, hands the boss a ticket, and writes the run's bookends to the audit
trail. Everything between those bookends is logged by `backend/agents.py` as the
agents work.

ONE SERVER, ONE RUN
-------------------
The MCP subprocess is started once and shared by all five agents for the whole
session. Starting one per agent would quintuple the handshake cost and give five
different connections to one SQLite file.

RESET BEFORE A FULL RUN
-----------------------
`--all` resolves tickets for real: it writes approvals, drafts and ticket
statuses to the working database. Run it twice without resetting and the second
run sees a board the first one already changed. Reset first:

    python scripts/init_working_db.py

`--all` prints this reminder and pauses unless `--yes` is passed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from typing import Any

from pydantic_ai.usage import RunUsage

from backend.agents import Counters, TeamDeps, build_team, capture_messages, run_usage_limits
from backend.audit import AUDIT_PATH, AuditTrail, summarise
from backend.mcp_client import build_toolset
from backend.model_provider import model_name
from backend.models import AgentName, RunBudget, RunResult, TicketOutcome


def _unwrap(result: Any) -> Any:
    """FastMCP wraps a bare return value under a `result` key. Unwrap it."""
    data = getattr(result, "structured_content", None)
    if isinstance(data, dict):
        return data.get("result", data)
    if getattr(result, "data", None) is not None:
        return result.data
    return data


async def _read_board(client) -> dict[str, Any]:
    """Which tickets are open, and what is the shop's date — over MCP, not SQL."""
    return _unwrap(await client.call_tool("list_open_tickets", {}))


async def run_ticket(
    team: dict[AgentName, Agent],  # noqa: F821 - Agent imported for typing only
    ticket_id: int,
    shop_date: str | None,
    budget: RunBudget,
    run_id: str | None = None,
) -> RunResult:
    """Hand one ticket to the boss and record everything that follows.

    `run_id` is accepted rather than always minted here so a caller that has
    already told someone else a run's name can pass it in. The FastAPI route
    does exactly that: it returns a run_id to the dashboard immediately, and if
    this function minted a second one the audit rows would be filed under an id
    nobody outside this function ever saw — making `GET /events?run_id=` match
    nothing and a run impossible to correlate with its own trail.
    """
    run_id = run_id or f"run-{ticket_id}-{uuid.uuid4().hex[:8]}"
    audit = AuditTrail(run_id, ticket_id)
    usage = RunUsage()
    counters = Counters()

    deps = TeamDeps(
        run_id=run_id,
        ticket_id=ticket_id,
        audit=audit,
        budget=budget,
        usage=usage,
        shop_date=shop_date,
        depth=0,
        stack=(),
        counters=counters,
    )

    audit.log(
        event="run_start",
        agent=AgentName.BOSS.value,
        shop_date=shop_date,
        model=model_name(),
        content=f"Resolving ticket {ticket_id}.",
    )

    started = time.perf_counter()
    outcome: TicketOutcome | None = None
    error: str | None = None

    try:
        result = await team[AgentName.BOSS].run(
            (
                f"Work ticket {ticket_id} to a conclusion. Read it first, delegate to "
                "whoever can answer the real question, and then record your decision "
                "with update_ticket."
            ),
            deps=deps,
            usage=usage,
            usage_limits=run_usage_limits(budget),
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        capture_messages(deps, AgentName.BOSS.value, result.new_messages(), elapsed_ms)
        outcome = result.output
    except Exception as exc:  # noqa: BLE001 - a failed ticket must still be auditable
        error = f"{type(exc).__name__}: {exc}"
        audit.log(
            event="error",
            agent=AgentName.BOSS.value,
            shop_date=shop_date,
            error=error,
        )

    duration = time.perf_counter() - started

    audit.log(
        event="run_end",
        agent=AgentName.BOSS.value,
        shop_date=shop_date,
        model=model_name(),
        content=(outcome.resolution if outcome else "Run failed."),
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cost_usd=float(usage.cost) if getattr(usage, "cost", None) is not None else None,
        duration_ms=int(duration * 1000),
        error=error,
    )

    return RunResult(
        run_id=run_id,
        ticket_id=ticket_id,
        outcome=outcome,
        steps_logged=audit.steps_logged,
        delegations=counters.delegations,
        tool_calls=counters.tool_calls,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cost_usd=float(usage.cost) if getattr(usage, "cost", None) is not None else 0.0,
        duration_s=round(duration, 2),
        error=error,
    )


async def main_async(args: argparse.Namespace) -> int:
    toolset, client = build_toolset()

    async with toolset:
        board = await _read_board(client)
        shop_date = board.get("shop_date")
        open_ids = [t["id"] for t in board.get("tickets", [])]

        if args.list:
            print(f"Shop date: {shop_date}")
            print(f"Open tickets ({len(open_ids)}):")
            for t in board.get("tickets", []):
                links = ", ".join(t.get("links") or []) or "none"
                print(f"  {t['id']}  {t['type']:<15} {t['subject']:<28} links: {links}")
            return 0

        if args.ticket:
            targets = [args.ticket]
        else:
            targets = open_ids
            if not targets:
                print("No open tickets. Reset with: python scripts/init_working_db.py")
                return 0

        budget = RunBudget()
        team = build_team(toolset)

        print(f"Shop date {shop_date} | model {model_name()} | audit -> {AUDIT_PATH.name}")
        print(f"Running {len(targets)} ticket(s): {targets}\n")

        results: list[RunResult] = []
        for tid in targets:
            print(f"--- ticket {tid} ---", flush=True)
            res = await run_ticket(team, tid, shop_date, budget)
            results.append(res)

            if res.error:
                print(f"  FAILED: {res.error}")
            elif res.outcome:
                o = res.outcome
                print(f"  status      : {o.status}")
                print(f"  assignee    : {o.assignee}")
                print(f"  delegated to: {', '.join(o.delegated_to) or 'nobody'}")
                print(f"  resolution  : {o.resolution}")
                if o.approval_ids:
                    print(f"  approvals   : {o.approval_ids}")
                if o.draft_ids:
                    print(f"  drafts      : {o.draft_ids}")
                if o.next_step:
                    print(f"  next step   : {o.next_step}")
            print(
                f"  [{res.duration_s}s, {res.delegations} delegations, "
                f"{res.tool_calls} tool calls, {res.input_tokens}+{res.output_tokens} tokens, "
                f"${res.cost_usd:.4f}]\n",
                flush=True,
            )

        print("=== audit trail ===")
        print(json.dumps(summarise(), indent=2))
        return 1 if any(r.error for r in results) else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Run the Campus Customs agent team.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--ticket", type=int, help="resolve a single ticket by id")
    g.add_argument("--all", action="store_true", help="resolve every open ticket")
    g.add_argument("--list", action="store_true", help="show the board; no model calls")
    ap.add_argument(
        "--yes", action="store_true", help="skip the reset reminder before a full run"
    )
    args = ap.parse_args()

    if args.all and not args.yes:
        print(
            "A full run writes approvals, drafts and ticket statuses to the working\n"
            "database. If you have run it before without resetting, the board is\n"
            "already changed and this run will not reproduce.\n\n"
            "  Reset first:  python scripts/init_working_db.py\n"
        )
        reply = input("Reset already done? [y/N] ").strip().lower()
        if reply not in {"y", "yes"}:
            print("Stopped. Nothing was run.")
            return 2

    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
