"""The team's single connection to the Campus Customs MCP server.

ONE TOOL LAYER, NO SHORTCUTS
----------------------------
Every shop fact the agents use — stock, prices, vendors, cash, leases,
invoices, tickets — arrives through the MCP server over
`data/campus_customs_new.db`. The backend deliberately does **not** open the
database itself and does not wrap SQL in a convenience layer. A second path to
the same data would mean two places enforcing the shop's rules, and the second
one would eventually disagree with the first.

The only thing this backend writes directly is the audit trail, which is
observability rather than shop state.

ONE SUBPROCESS, NOT FIVE
------------------------
All five agents share one `MCPToolset`, so the server is launched once per run
rather than once per agent. The lifecycle is owned by `backend/team.py`.

PER-AGENT TOOL ALLOWLISTS
-------------------------
Each agent sees only the tools its role needs. This does two jobs at once:

* **Safety.** Customer service cannot call `pay_invoice`, because the tool is
  not on its list at all. The narrow path is the only path, rather than a
  prompt asking it nicely.
* **Tokens.** A tool schema is re-sent on every model request. Fifteen schemas
  across five agents, several round-trips each, is real money. Handing each
  agent five or six relevant tools instead of all fifteen cuts the per-request
  payload substantially and makes the model's choice easier.
"""

from __future__ import annotations

import sys
from pathlib import Path

from pydantic_ai.mcp import FastMCPClient, MCPToolset, StdioTransport
from pydantic_ai.tools import ToolDefinition

from app.config import ROOT
from backend.models import AgentName

SERVER_SCRIPT = ROOT / "mcp_server" / "server.py"

# Which MCP tools each role may call. Anything not listed is invisible to that
# agent. The boss gets read and routing tools but NOT the payment tools: it
# decides and delegates, and money is accounting's and facilities' business.
TOOL_ALLOWLIST: dict[AgentName, set[str]] = {
    AgentName.BOSS: {
        "list_open_tickets",
        "get_ticket",
        "get_shop_policy",
        "list_approvals",
        "update_ticket",
    },
    AgentName.INVENTORY: {
        "check_stock",
        "find_restock_vendor",
        "get_ticket",
        "create_purchase_order",
        "request_approval",
        "get_shop_policy",
    },
    AgentName.ACCOUNTING: {
        "get_cash_position",
        "evaluate_discount",
        "get_ticket",
        "pay_invoice",
        "create_purchase_order",
        "request_approval",
        "list_approvals",
        "get_shop_policy",
    },
    AgentName.FACILITIES: {
        "get_lease",
        "get_cash_position",
        "get_ticket",
        "pay_rent",
        "request_approval",
        "list_approvals",
        "get_shop_policy",
    },
    AgentName.CUSTOMER_SERVICE: {
        "get_ticket",
        "check_stock",
        "save_draft_message",
        "get_shop_policy",
    },
}


def build_toolset() -> tuple[MCPToolset, FastMCPClient]:
    """Launch the MCP server over stdio and return the shared toolset and client.

    `sys.executable` rather than a bare `python` so the server runs on the same
    interpreter as the backend — otherwise a machine with several Pythons can
    start a server that has no `fastmcp` installed.

    The client is returned alongside the toolset so the runner can make its own
    bookkeeping calls (which tickets are open, what the shop date is) over the
    *same* MCP connection. That keeps the rule intact: there is one path to the
    shop's data, and the orchestrator uses it too rather than reaching past it
    into SQLite.
    """
    if not SERVER_SCRIPT.exists():
        raise RuntimeError(f"MCP server not found at {SERVER_SCRIPT}")

    transport = StdioTransport(
        command=sys.executable,
        args=[str(SERVER_SCRIPT)],
        cwd=str(ROOT),
        env={"PYTHONUNBUFFERED": "1"},
    )
    client = FastMCPClient(transport)
    return MCPToolset(client, id="campus-customs"), client


def toolset_for(agent: AgentName, shared: MCPToolset):
    """Narrow the shared toolset to the tools this agent is allowed to call."""
    allowed = TOOL_ALLOWLIST[agent]

    def _filter(_ctx, tool_def: ToolDefinition) -> bool:
        return tool_def.name in allowed

    return shared.filtered(_filter)


def allowlist_report() -> dict[str, list[str]]:
    """Which agent may call which tool. Used in the harness write-up."""
    return {a.value: sorted(t) for a, t in TOOL_ALLOWLIST.items()}
