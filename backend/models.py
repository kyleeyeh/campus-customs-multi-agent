"""Data types for the Campus Customs agent team.

Everything that crosses a boundary — between two agents, between an agent and
the audit trail, between a run and whatever reads its result — is typed here.

WHY TYPES AND NOT FREE TEXT
---------------------------
A multi-agent team degrades in a specific way: the boss asks a specialist for
an answer, the specialist writes four paragraphs, and the boss re-reads and
re-interprets prose it already paid for. Structured returns stop that. A
specialist hands back a small object with the facts it used and what it
recommends, and the boss reads fields rather than re-reasoning over text.

It also makes the audit trail worth keeping: `facts_used` tells a reader which
database values a recommendation actually rested on, which is the difference
between an auditable decision and a plausible-sounding one.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Who is on the team
# ---------------------------------------------------------------------------
class AgentName(str, Enum):
    """The five roles. Delegation targets are validated against this."""

    BOSS = "boss"
    INVENTORY = "inventory"
    ACCOUNTING = "accounting"
    FACILITIES = "facilities"
    CUSTOMER_SERVICE = "customer_service"

    @classmethod
    def values(cls) -> list[str]:
        return [m.value for m in cls]


# ---------------------------------------------------------------------------
# What a specialist hands back
# ---------------------------------------------------------------------------
class SpecialistReport(BaseModel):
    """The structured answer every non-boss agent returns.

    Deliberately small. A specialist that needs to say more than this is
    usually reasoning in prose where it should be calling a tool.
    """

    agent: str = Field(description="Which agent produced this report.")
    summary: str = Field(
        description="Two or three sentences. What you found and what it means."
    )
    facts_used: list[str] = Field(
        default_factory=list,
        description=(
            "The concrete database values this rests on, each with its number, "
            "e.g. 'inventory CC-TEE-WHITE/S qty=0'. Not prose."
        ),
    )
    recommendation: str = Field(
        description="What you think the shop should do, in one or two sentences."
    )
    policy_cited: list[str] = Field(
        default_factory=list,
        description="Policy rules relied on, e.g. 'margin floor 40%'.",
    )
    blocked_on: str | None = Field(
        default=None,
        description="What stops this from being finished now, if anything.",
    )
    approval_ids: list[int] = Field(
        default_factory=list,
        description="Approval rows raised while producing this report.",
    )
    draft_ids: list[int] = Field(
        default_factory=list, description="Draft messages written."
    )


# ---------------------------------------------------------------------------
# What the boss hands back
# ---------------------------------------------------------------------------
TicketStatus = Literal["open", "waiting_approval", "resolved", "declined"]


class TicketOutcome(BaseModel):
    """The boss's final word on one ticket."""

    ticket_id: int
    status: TicketStatus = Field(
        description=(
            "'waiting_approval' if anything is parked with a human. "
            "'resolved' only if nothing is pending. 'declined' if the shop "
            "cannot or should not do it."
        )
    )
    assignee: str = Field(description="The agent that did the substantive work.")
    resolution: str = Field(
        description="Two to four sentences a shop owner could read and act on."
    )
    delegated_to: list[str] = Field(
        default_factory=list, description="Agents consulted, in order."
    )
    facts_used: list[str] = Field(
        default_factory=list, description="Database values the decision rested on."
    )
    policy_cited: list[str] = Field(default_factory=list)
    approval_ids: list[int] = Field(
        default_factory=list, description="Approvals parked for a human."
    )
    draft_ids: list[int] = Field(default_factory=list)
    money_moved: float = Field(
        default=0.0,
        description="Cash actually spent during this run. Zero unless a human had already approved.",
    )
    next_step: str | None = Field(
        default=None, description="What the human needs to do next, if anything."
    )


# ---------------------------------------------------------------------------
# Delegation
# ---------------------------------------------------------------------------
class DelegationRequest(BaseModel):
    """One agent asking another for help. Any agent may ask any other."""

    to_agent: AgentName
    task: str = Field(description="The specific question. Not 'help with ticket 101'.")
    context: str = Field(
        default="",
        description="Facts the callee needs that it cannot look up itself.",
    )


# ---------------------------------------------------------------------------
# Budgets — the token guardrail
# ---------------------------------------------------------------------------
class RunBudget(BaseModel):
    """Hard ceilings for one ticket's run.

    These exist because multi-agent chat is the fastest way to burn a token
    budget: every delegation re-sends a system prompt and a tool schema. The
    limits are enforced by the runner, not suggested in a prompt.
    """

    max_delegation_depth: int = Field(
        default=2, description="boss -> specialist -> specialist. No deeper."
    )
    max_delegations_per_run: int = Field(
        default=6, description="Total delegate() calls across the whole ticket."
    )
    max_requests_per_agent: int = Field(
        default=8, description="Model round-trips inside one agent's loop."
    )
    max_tool_calls_per_run: int = Field(default=30)
    total_tokens_limit: int = Field(
        default=120_000, description="Shared across every agent in the run."
    )


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------
AuditEvent = Literal[
    "run_start",
    "agent_start",
    "model_request",
    "tool_call",
    "tool_result",
    "delegation",
    "delegation_result",
    "agent_end",
    "budget_refused",
    "error",
    "run_end",
]


class AuditStep(BaseModel):
    """One row of `output/audit_trail.json`.

    Written per agent-loop step. The point is that someone who was not here can
    reconstruct what happened: which agent, acting for which ticket, called
    which tool with which arguments, what came back, which model answered, and
    what it cost.
    """

    run_id: str
    seq: int = Field(description="Monotonic within a run. Orders the trail.")
    ts: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"),
        description="Real wall-clock UTC — when this ran, not the shop's calendar.",
    )
    shop_date: str | None = Field(
        default=None, description="desk.date_today — the shop's 'now'."
    )
    ticket_id: int | None = None
    event: AuditEvent
    agent: str | None = None
    to_agent: str | None = Field(default=None, description="Set on a delegation.")
    depth: int = 0
    model: str | None = Field(
        default=None, description="Proves which model answered. Must be gpt-6-luna."
    )
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    tool_result: Any | None = None
    content: str | None = Field(default=None, description="Message or summary text.")
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    duration_ms: int | None = None
    error: str | None = None


class RunResult(BaseModel):
    """What a single ticket run produced, returned to the caller and logged."""

    run_id: str
    ticket_id: int
    outcome: TicketOutcome | None = None
    steps_logged: int = 0
    delegations: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    duration_s: float = 0.0
    error: str | None = None
