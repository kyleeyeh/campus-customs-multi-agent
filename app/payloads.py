"""How an approval payload names the obligation it points at.

WHY THIS IS ITS OWN MODULE
--------------------------
An agent writes its own approval payload, and it does not reliably reach for
the same key. A request to pay invoice 501 has come back as `{"ref_id": 501}`,
as `{"invoice_id": 501}`, and for rent as `{"lease_id": 1}`. All three name the
same thing.

That cost a real bug. The backend read only `ref_id`, so a payload spelled
`invoice_id` resolved to `None`, the pay tool was handed `invoice_id=None`, and
approving a payment silently did nothing while reporting a decision.

The second half was worse. The MCP scope check compared `payload["ref_id"]`
against the obligation being paid and treated `None` as "no constraint" — so an
approval whose payload used any other spelling had **no scope enforcement at
all** and could have been replayed against a different, larger obligation.

Both the FastAPI route and the MCP guardrail now resolve the reference through
this one function. They cannot disagree about what an approval authorises,
because there is only one definition of it.

Tightening a prompt to insist on `ref_id` would not have been a fix. The model
is free to write what it likes; the system has to be correct regardless.
"""

from __future__ import annotations

from typing import Any

# Checked in order. `ref_id` is what the prompts ask for; the rest are the
# spellings actually observed coming back from the agents.
REF_KEYS: tuple[str, ...] = (
    "ref_id",
    "invoice_id",
    "lease_id",
    "purchase_order_id",
    "po_id",
)


def payload_ref(payload: dict[str, Any]) -> int | None:
    """Return the obligation id in an approval payload, whatever it was called.

    Returns `None` when no reference can be found — which callers must treat as
    "scope unverifiable, refuse", never as "unconstrained".
    """
    for key in REF_KEYS:
        value = payload.get(key)
        # bool is an int subclass; True must not become obligation 1.
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
    return None
