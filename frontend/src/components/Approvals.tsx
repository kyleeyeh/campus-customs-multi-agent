/**
 * Moira's desk — the approvals panel.
 *
 * This is the only place on the board where a human has to do something, so it
 * is the only panel with its own colour (plum), its own typeface treatment, and
 * a named person presiding over it. Moira is not an agent and cannot be one:
 * no agent on this team may approve anything, including its own request. Giving
 * that power a face makes the boundary obvious rather than a footnote.
 *
 * When the backend approves but the tool then refuses — a payment that would
 * overdraw, say — this panel reports the refusal rather than the approval.
 * Clicking Approve is permission, not a guarantee, and pretending otherwise
 * would be the one genuinely dangerous lie this interface could tell.
 */

import { useState } from "react";
import type { Approval, ApprovalResult } from "../types";
import { castFor, MOIRA } from "../cast";

const money = (n: number) =>
  n.toLocaleString("en-US", { style: "currency", currency: "USD" });

interface Props {
  approvals: Approval[];
  onDecide: (id: number, decision: "approved" | "rejected") => Promise<ApprovalResult>;
}

export function Approvals({ approvals, onDecide }: Props) {
  const [busy, setBusy] = useState<number | null>(null);
  const [verdicts, setVerdicts] = useState<Record<number, ApprovalResult>>({});

  const pending = approvals.filter((a) => a.status === "pending");

  async function decide(id: number, decision: "approved" | "rejected") {
    setBusy(id);
    try {
      const result = await onDecide(id, decision);
      setVerdicts((v) => ({ ...v, [id]: result }));
    } catch (err) {
      setVerdicts((v) => ({
        ...v,
        [id]: {
          approval_id: id,
          decision,
          decided_by: "—",
          executed: false,
          note: err instanceof Error ? err.message : "Something went wrong.",
        },
      }));
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="card moira">
      <div className="card-head">
        <h2>Awaiting Moira</h2>
        <span className="hint">{pending.length} pending</span>
      </div>

      <div className="moira-intro">
        <div className="avatar">{MOIRA.initials}</div>
        <div>
          <div className="cast-name">{MOIRA.character}</div>
          <div className="moira-quote">
            {pending.length ? MOIRA.waiting : MOIRA.quiet}
          </div>
        </div>
      </div>

      {pending.length === 0 && (
        <div className="empty" style={{ paddingTop: 18 }}>
          Nothing requires a signature.
        </div>
      )}

      {pending.map((a) => {
        const asker = castFor(a.requested_by);
        const verdict = verdicts[a.id];
        return (
          <div className="ask" key={a.id}>
            <div className="ask-head">
              <span className="ask-kind">
                {a.kind.replace("_", " ")} · ticket {a.ticket_id}
              </span>
              <span className="ask-amt">{a.amount ? money(a.amount) : "—"}</span>
            </div>

            <div className="ask-summary">{a.summary}</div>
            {a.rationale && <div className="ask-why">“{a.rationale}”</div>}

            <div className="ask-by">
              asked for by{" "}
              <span style={{ color: asker?.color, fontWeight: 600 }}>
                {asker?.character ?? a.requested_by}
              </span>
            </div>

            <div className="ask-actions">
              <button
                className="btn btn-approve"
                disabled={busy !== null}
                onClick={() => decide(a.id, "approved")}
              >
                {busy === a.id ? "Deciding…" : "Approve"}
              </button>
              <button
                className="btn btn-reject"
                disabled={busy !== null}
                onClick={() => decide(a.id, "rejected")}
              >
                Decline
              </button>
            </div>

            {verdict && (
              <div className={`verdict ${verdict.executed ? "ok" : "no"}`}>
                {verdict.executed ? (
                  <>
                    Done. {verdict.balance_after != null && (
                      <>Balance now <strong>{money(verdict.balance_after)}</strong>.</>
                    )}
                  </>
                ) : (
                  <>{verdict.note}</>
                )}
              </div>
            )}
          </div>
        );
      })}
    </section>
  );
}
