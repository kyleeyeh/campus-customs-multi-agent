"""Append-only audit trail at `output/audit_trail.json`.

WHAT GETS RECORDED
------------------
One row per agent-loop step: the run starting, each agent being entered, every
model round-trip, every MCP tool call with its arguments, every tool result,
every delegation from one agent to another, and the run ending. Enough that
someone who was not present can reconstruct the decision — not just its
conclusion.

Each row names the model that answered. That is deliberate: the assignment
permits exactly one model, and a trail that records which model produced each
step turns that from a claim into evidence.

APPEND, NEVER WIPE
------------------
The file accumulates across runs. Every write re-reads what is on disk, adds to
it, and writes the whole array back through a temporary file and an atomic
replace, so an interrupted write cannot truncate the history that was already
there. A run that crashes keeps every step it logged before the crash.

The file is a JSON array rather than JSON Lines because the assignment names it
`.json` and a reader should be able to `json.load` it in one call. At this
scale (hundreds of rows) rewriting the array per step is irrelevant; if this
ever grew to millions of rows, JSON Lines would be the right change.

FILENAME
--------
`audit_trail.json`. Problem 5 asked for `audit_train.json`; Problem 9 asked for
`audit_trail.json`, which is taken as the correction of a typo rather than a
request for a second file. Every row written under the old name was migrated
into this one, so no history was lost in the rename.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from app.config import ROOT
from backend.models import AuditStep

AUDIT_PATH = ROOT / "output" / "audit_trail.json"

# Tool results can be large (a full ticket join, a vendor list). Truncate so one
# verbose call cannot dominate the file, but keep enough to audit the decision.
MAX_RESULT_CHARS = 2000
MAX_CONTENT_CHARS = 1200

_lock = threading.Lock()


def _truncate(value: Any, limit: int) -> Any:
    """Shorten oversized values, marking clearly that we did so."""
    if value is None:
        return None
    if isinstance(value, str):
        if len(value) <= limit:
            return value
        return value[:limit] + f"... [truncated, {len(value)} chars total]"
    try:
        blob = json.dumps(value, default=str)
    except (TypeError, ValueError):
        return _truncate(str(value), limit)
    if len(blob) <= limit:
        return value
    return {
        "_truncated": True,
        "_original_chars": len(blob),
        "preview": blob[:limit] + "...",
    }


def _read_existing() -> list[dict[str, Any]]:
    """Load the trail so far. A corrupt or missing file never loses a run."""
    if not AUDIT_PATH.exists() or AUDIT_PATH.stat().st_size == 0:
        return []
    try:
        with AUDIT_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else [data]
    except json.JSONDecodeError:
        # Preserve the damaged file rather than silently overwriting evidence.
        salvage = AUDIT_PATH.with_suffix(".corrupt.json")
        AUDIT_PATH.replace(salvage)
        return []


def _write_atomic(rows: list[dict[str, Any]]) -> None:
    """Write via a temp file + replace, so a crash mid-write cannot truncate."""
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = AUDIT_PATH.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, default=str)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(AUDIT_PATH)


class AuditTrail:
    """Sequenced, append-only writer for one run.

    `seq` is monotonic within a run, so the trail can be ordered even though
    several runs may interleave in the same file.
    """

    def __init__(self, run_id: str, ticket_id: int | None = None) -> None:
        self.run_id = run_id
        self.ticket_id = ticket_id
        self._seq = 0
        self.steps_logged = 0

    def log(self, **fields: Any) -> AuditStep:
        """Validate one step, append it to the file, and return it."""
        self._seq += 1
        fields.setdefault("ticket_id", self.ticket_id)

        if "tool_result" in fields:
            fields["tool_result"] = _truncate(fields["tool_result"], MAX_RESULT_CHARS)
        if "content" in fields:
            fields["content"] = _truncate(fields["content"], MAX_CONTENT_CHARS)
        if "tool_args" in fields and fields["tool_args"] is not None:
            fields["tool_args"] = _truncate(fields["tool_args"], MAX_RESULT_CHARS)
            if not isinstance(fields["tool_args"], dict):
                fields["tool_args"] = {"_value": fields["tool_args"]}

        step = AuditStep(run_id=self.run_id, seq=self._seq, **fields)

        with _lock:
            rows = _read_existing()
            rows.append(step.model_dump(mode="json", exclude_none=True))
            _write_atomic(rows)

        self.steps_logged += 1
        return step


def read_trail(run_id: str | None = None) -> list[dict[str, Any]]:
    """Read the trail back, optionally filtered to one run. For tests and the UI."""
    rows = _read_existing()
    if run_id is None:
        return rows
    return [r for r in rows if r.get("run_id") == run_id]


def summarise(run_id: str | None = None) -> dict[str, Any]:
    """Quick counts over the trail — what ran, which tools, which models."""
    rows = read_trail(run_id)
    tools: dict[str, int] = {}
    models: dict[str, int] = {}
    agents: dict[str, int] = {}
    for r in rows:
        if r.get("event") == "tool_call" and r.get("tool_name"):
            tools[r["tool_name"]] = tools.get(r["tool_name"], 0) + 1
        if r.get("model"):
            models[r["model"]] = models.get(r["model"], 0) + 1
        if r.get("agent"):
            agents[r["agent"]] = agents.get(r["agent"], 0) + 1
    # `run_end` repeats the run's totals for convenience, so it must be excluded
    # here or every token would be counted twice.
    per_request = [r for r in rows if r.get("event") == "model_request"]
    run_ends = [r for r in rows if r.get("event") == "run_end"]

    return {
        "rows": len(rows),
        "runs": len({r.get("run_id") for r in rows}),
        "agents": agents,
        "tool_calls": tools,
        "models_seen": models,
        "input_tokens": sum(r.get("input_tokens") or 0 for r in per_request),
        "output_tokens": sum(r.get("output_tokens") or 0 for r in per_request),
        "cost_usd": round(sum(r.get("cost_usd") or 0.0 for r in run_ends), 6),
    }
