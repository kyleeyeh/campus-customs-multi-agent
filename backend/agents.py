"""The five-agent team, and the delegation that connects them.

FULL CONNECTIVITY
-----------------
Every agent carries a `delegate` tool whose target is any other agent on the
team, including the boss. There is no fixed hierarchy in the wiring: inventory
can ask accounting, accounting can ask facilities, customer service can ask the
boss. The boss is "in charge" because of what its prompt tells it to do and
because it is the only agent holding `update_ticket` — not because it is the
only one allowed to speak.

That is the point of the design, and also its main hazard. Any-to-any
delegation can cycle, and each hop re-sends a system prompt and a set of tool
schemas. So the connectivity is total but the traffic is bounded, by rules
enforced in this file rather than requested in a prompt:

* **Depth.** A chain may go boss -> specialist -> specialist and no deeper.
* **Volume.** A whole ticket gets a fixed number of delegations.
* **Cycles.** An agent already on the current call stack cannot be re-entered,
  so A -> B -> A is refused outright.
* **Tokens.** One shared `RunUsage` threads through every nested call, so the
  budget is for the entire tree rather than per agent.

A refused delegation returns an explanatory dict rather than raising. The
calling agent reads it, learns it must answer with what it has, and proceeds —
which is a better failure than a crashed run.

AUDIT
-----
After every agent run, its new messages are walked and written to the audit
trail: each model round-trip with its token counts, each tool call with its
arguments, each tool result. The agent never has to remember to log anything.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from typing import Any

from pydantic_ai import Agent, RunContext, UsageLimits
from pydantic_ai.messages import ModelRequest, ModelResponse, ToolCallPart, ToolReturnPart
from pydantic_ai.usage import RunUsage

from backend import prompts
from backend.audit import AuditTrail
from backend.mcp_client import toolset_for
from backend.model_provider import build_model, model_name
from backend.models import AgentName, RunBudget, SpecialistReport, TicketOutcome


# ---------------------------------------------------------------------------
# Shared run state
# ---------------------------------------------------------------------------
@dataclass
class Counters:
    """Mutable tallies shared by every agent in one run."""

    delegations: int = 0
    tool_calls: int = 0
    refusals: int = 0


@dataclass
class TeamDeps:
    """What every agent in a run can see.

    `usage`, `counters` and `audit` are shared objects, not copies — that is how
    a budget spent three levels down is visible at the top.
    """

    run_id: str
    ticket_id: int
    audit: AuditTrail
    budget: RunBudget
    usage: RunUsage
    shop_date: str | None = None
    depth: int = 0
    stack: tuple[str, ...] = ()
    counters: Counters = field(default_factory=Counters)


# ---------------------------------------------------------------------------
# Turning a finished run into audit rows
# ---------------------------------------------------------------------------
def capture_messages(
    deps: TeamDeps, agent: str, messages: list[Any], duration_ms: int | None = None
) -> int:
    """Write one audit row per model request and per tool call/result.

    Walks only the messages a run newly produced, so a nested agent's history
    is not logged twice by its caller.
    """
    tool_calls = 0
    for msg in messages:
        if isinstance(msg, ModelResponse):
            usage = getattr(msg, "usage", None)
            deps.audit.log(
                event="model_request",
                agent=agent,
                depth=deps.depth,
                shop_date=deps.shop_date,
                model=getattr(msg, "model_name", None) or model_name(),
                input_tokens=getattr(usage, "input_tokens", None),
                output_tokens=getattr(usage, "output_tokens", None),
                duration_ms=duration_ms,
            )
            for part in msg.parts:
                if isinstance(part, ToolCallPart):
                    tool_calls += 1
                    deps.counters.tool_calls += 1
                    deps.audit.log(
                        event="tool_call",
                        agent=agent,
                        depth=deps.depth,
                        shop_date=deps.shop_date,
                        model=model_name(),
                        tool_name=part.tool_name,
                        tool_args=_safe_args(part),
                    )
        elif isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, ToolReturnPart):
                    deps.audit.log(
                        event="tool_result",
                        agent=agent,
                        depth=deps.depth,
                        shop_date=deps.shop_date,
                        tool_name=part.tool_name,
                        tool_result=part.content,
                    )
    return tool_calls


def _safe_args(part: ToolCallPart) -> dict[str, Any]:
    """Tool arguments as a dict, whatever shape the model sent them in."""
    try:
        args = part.args_as_dict()
    except Exception:  # noqa: BLE001 - audit must never break a run
        args = {"_raw": str(getattr(part, "args", ""))}
    return args if isinstance(args, dict) else {"_value": args}


# ---------------------------------------------------------------------------
# Building the team
# ---------------------------------------------------------------------------
# The boss returns a ticket decision; everyone else returns a report.
OUTPUT_TYPES: dict[AgentName, type] = {
    AgentName.BOSS: TicketOutcome,
    AgentName.INVENTORY: SpecialistReport,
    AgentName.ACCOUNTING: SpecialistReport,
    AgentName.FACILITIES: SpecialistReport,
    AgentName.CUSTOMER_SERVICE: SpecialistReport,
}


def build_team(shared_toolset) -> dict[AgentName, Agent]:
    """Construct all five agents and wire delegation between every pair.

    One model object is shared by all five — there is exactly one model in this
    project and this is where that is guaranteed.
    """
    model = build_model()
    team: dict[AgentName, Agent] = {}

    for name in AgentName:
        team[name] = Agent(
            model,
            name=name.value,
            deps_type=TeamDeps,
            output_type=OUTPUT_TYPES[name],
            system_prompt=prompts.load(name),
            toolsets=[toolset_for(name, shared_toolset)],
            retries=2,
        )

    for name, agent in team.items():
        _attach_delegate(agent, name, team)

    return team


def _attach_delegate(agent: Agent, me: AgentName, team: dict[AgentName, Agent]) -> None:
    """Give one agent the ability to call any other agent on the team."""

    @agent.tool
    async def delegate(  # noqa: D401 - the docstring is the tool description
        ctx: RunContext[TeamDeps], to_agent: str, task: str, context: str = ""
    ) -> dict[str, Any]:
        """Ask another agent on the team for help, and wait for their report.

        Args:
            to_agent: One of boss, inventory, accounting, facilities,
                customer_service.
            task: The specific question you need answered. Be concrete — name
                the ticket, the SKU, the quantity.
            context: Facts the other agent needs that it cannot look up for
                itself, such as what another specialist has already told you.
        """
        deps = ctx.deps

        try:
            target = AgentName(to_agent)
        except ValueError:
            deps.counters.refusals += 1
            return {
                "delegated": False,
                "reason": f"No agent named {to_agent!r}. Team: {AgentName.values()}.",
            }

        refusal = _check_delegation_allowed(deps, me, target)
        if refusal is not None:
            deps.counters.refusals += 1
            deps.audit.log(
                event="budget_refused",
                agent=me.value,
                to_agent=target.value,
                depth=deps.depth,
                shop_date=deps.shop_date,
                content=refusal["reason"],
            )
            return refusal

        deps.counters.delegations += 1
        deps.audit.log(
            event="delegation",
            agent=me.value,
            to_agent=target.value,
            depth=deps.depth,
            shop_date=deps.shop_date,
            content=task,
        )

        child = replace(
            deps,
            depth=deps.depth + 1,
            stack=deps.stack + (me.value,),
        )
        prompt = _delegation_prompt(me, deps.ticket_id, task, context)

        started = time.perf_counter()
        try:
            result = await team[target].run(
                prompt,
                deps=child,
                usage=deps.usage,  # one shared budget for the whole tree
                usage_limits=run_usage_limits(deps.budget),
            )
        except Exception as exc:  # noqa: BLE001 - report, never crash the caller
            deps.audit.log(
                event="error",
                agent=target.value,
                depth=child.depth,
                shop_date=deps.shop_date,
                error=f"{type(exc).__name__}: {exc}",
            )
            return {
                "delegated": True,
                "agent": target.value,
                "failed": True,
                "error": f"{type(exc).__name__}: {exc}",
                "note": "Answer with what you already have; do not retry this delegation.",
            }

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        capture_messages(child, target.value, result.new_messages(), elapsed_ms)

        report = result.output
        payload = report.model_dump() if hasattr(report, "model_dump") else {"text": str(report)}

        deps.audit.log(
            event="delegation_result",
            agent=target.value,
            to_agent=me.value,
            depth=child.depth,
            shop_date=deps.shop_date,
            model=model_name(),
            content=getattr(report, "summary", None) or str(report),
            duration_ms=elapsed_ms,
        )
        return {"delegated": True, "agent": target.value, "report": payload}


def _check_delegation_allowed(
    deps: TeamDeps, me: AgentName, target: AgentName
) -> dict[str, Any] | None:
    """Return a refusal dict if this delegation breaks a budget or would cycle."""
    if target == me:
        return {
            "delegated": False,
            "reason": "You cannot delegate to yourself. Use your own tools.",
        }

    if target.value in deps.stack:
        return {
            "delegated": False,
            "reason": (
                f"{target.value} is already waiting on this chain "
                f"({' -> '.join(deps.stack + (me.value,))}). Refused to avoid a loop. "
                "Answer with what you have."
            ),
        }

    if deps.depth >= deps.budget.max_delegation_depth:
        return {
            "delegated": False,
            "reason": (
                f"Delegation depth limit ({deps.budget.max_delegation_depth}) reached. "
                "Answer using your own tools and say what you could not establish."
            ),
        }

    if deps.counters.delegations >= deps.budget.max_delegations_per_run:
        return {
            "delegated": False,
            "reason": (
                f"This ticket has used its {deps.budget.max_delegations_per_run} "
                "delegations. Conclude with what the team has already found."
            ),
        }

    return None


def _delegation_prompt(sender: AgentName, ticket_id: int, task: str, context: str) -> str:
    """The message a delegated agent actually receives."""
    lines = [
        f"You are being asked for help by the {sender.value} agent.",
        f"Ticket: {ticket_id}",
        "",
        f"What they need: {task}",
    ]
    if context.strip():
        lines += ["", f"Context they have already established: {context.strip()}"]
    lines += [
        "",
        "Use your tools to establish the facts, then return your report. "
        "Do not re-derive figures you have been given above.",
    ]
    return "\n".join(lines)


def run_usage_limits(budget: RunBudget) -> UsageLimits:
    """Client-side spend ceiling for a run.

    Deliberately *not* a `max_tokens` on the request: this model rejects
    `max_tokens` and wants `max_completion_tokens`, and sending either would cap
    a single response rather than the run. `UsageLimits` counts locally and
    sends nothing to the API, so it bounds the whole tree without touching the
    wire format.
    """
    return UsageLimits(
        request_limit=budget.max_requests_per_agent * (budget.max_delegations_per_run + 1),
        tool_calls_limit=budget.max_tool_calls_per_run,
        total_tokens_limit=budget.total_tokens_limit,
    )
