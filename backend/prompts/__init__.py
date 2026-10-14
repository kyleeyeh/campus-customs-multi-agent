"""Loader for the agent prompts.

Each agent's system prompt is a separate Markdown file in this directory, one
file per agent, named for the role. Keeping them out of the Python means the
prompt can be read and edited as prose — which is what it is — without
scrolling past framework code, and a diff on a prompt change is legible.

TEMPLATE TOKENS
---------------
Two placeholders are substituted at load time:

* `{policy}` — the shop's written policy, rendered from `app/policy.py`.
* `{team}` — the current agent roster, from `backend/models.py`.

Both exist so the numbers live in exactly one place. If the margin floor
changes in `policy.py`, every prompt that quotes it changes with it, and the
tools that enforce it cannot drift away from the prompts that describe it.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from app import policy
from backend.models import AgentName

PROMPT_DIR = Path(__file__).resolve().parent

FILENAMES: dict[AgentName, str] = {
    AgentName.BOSS: "boss.md",
    AgentName.INVENTORY: "inventory.md",
    AgentName.ACCOUNTING: "accounting.md",
    AgentName.FACILITIES: "facilities.md",
    AgentName.CUSTOMER_SERVICE: "customer_service.md",
}


def _team_roster() -> str:
    return "\n".join(
        f"- `{name}`" for name in AgentName.values()
    )


@lru_cache(maxsize=None)
def load(agent: AgentName) -> str:
    """Return the fully rendered system prompt for one agent."""
    path = PROMPT_DIR / FILENAMES[agent]
    if not path.exists():
        raise FileNotFoundError(f"Missing prompt file for {agent.value}: {path}")
    text = path.read_text(encoding="utf-8")
    return text.replace("{policy}", policy.as_prompt_text()).replace(
        "{team}", _team_roster()
    )


def all_prompts() -> dict[str, str]:
    """Every rendered prompt, for inspection and the write-up."""
    return {a.value: load(a) for a in AgentName}
