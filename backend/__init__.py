"""Campus Customs multi-agent backend.

Layout:
    models.py          data types crossing every boundary
    model_provider.py  the single permitted model (gpt-6-luna via Portkey)
    mcp_client.py      the one connection to the MCP server, plus per-agent
                       tool allowlists
    prompts/           one system prompt per agent, as Markdown
    agents.py          the five agents and the any-to-any delegation wiring
    audit.py           append-only trail at output/audit_trail.json
    team.py            the runner / CLI entry point
"""
