/**
 * The board: three tickets, pick one.
 *
 * A resolved ticket gets a rotated rubber stamp rather than just a different
 * colour. The point is that "done" should be readable from across the desk —
 * you should be able to see the state of the board without reading any words.
 */

import type { Ticket } from "../types";
import { castFor } from "../cast";

interface Props {
  tickets: Ticket[];
  selectedId: number | null;
  runningId: number | null;
  onSelect: (id: number) => void;
}

function wants(t: Ticket): string | null {
  if (t.sku) return `${t.sku} · ${t.size ?? "—"} × ${t.qty ?? 1}`;
  if (t.lease_id) return `lease ${t.lease_id}`;
  if (t.invoice_id) return `invoice ${t.invoice_id}`;
  return null;
}

function statusPill(t: Ticket, isRunning: boolean) {
  if (isRunning) return <span className="pill live">working</span>;
  switch (t.status) {
    case "resolved":
      return <span className="pill resolved">resolved</span>;
    case "declined":
      return <span className="pill declined">declined</span>;
    case "waiting_approval":
      return <span className="pill waiting">needs Moira</span>;
    default:
      return <span className="pill open">open</span>;
  }
}

export function TicketList({ tickets, selectedId, runningId, onSelect }: Props) {
  return (
    <section className="card">
      <div className="card-head">
        <h2>The Board</h2>
        <span className="hint">{tickets.length} tickets</span>
      </div>
      <div className="card-body flush">
        {tickets.length === 0 && <div className="empty">Nothing on the board.</div>}
        {tickets.map((t) => {
          const owner = castFor(t.assignee);
          const isRunning = runningId === t.id;
          return (
            <button
              key={t.id}
              className={`ticket${selectedId === t.id ? " selected" : ""}`}
              onClick={() => onSelect(t.id)}
            >
              <div className="ticket-top">
                <span className="ticket-id">#{t.id}</span>
                {statusPill(t, isRunning)}
              </div>
              <div className="ticket-subject">{t.subject}</div>
              <div className="ticket-who">
                {t.requester}
                {owner && (
                  <>
                    {" · "}
                    <span style={{ color: owner.color, fontWeight: 600 }}>
                      {owner.character.split(" ")[0]}
                    </span>
                  </>
                )}
              </div>
              {wants(t) && <div className="ticket-want">{wants(t)}</div>}
              {t.pending_approvals.length > 0 && !isRunning && (
                <div className="ticket-want" style={{ color: "var(--plum)" }}>
                  {t.pending_approvals.length} waiting on a decision
                </div>
              )}
              {t.status === "resolved" && <span className="stamp">Resolved</span>}
              {t.status === "declined" && <span className="stamp declined">Declined</span>}
            </button>
          );
        })}
      </div>
    </section>
  );
}
