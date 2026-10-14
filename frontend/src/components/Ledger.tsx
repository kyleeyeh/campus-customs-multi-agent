/**
 * The checking balance, as a brass motel ledger.
 *
 * The number flashes red and shrinks back when it falls. Since cash only ever
 * goes down in this shop — no revenue is modelled — a drop is always the most
 * consequential thing that has happened, and it deserves to be the one piece of
 * motion on the page you cannot miss.
 *
 * Paid obligations stay in the list, struck through, rather than disappearing.
 * A ledger you can't read backwards isn't a ledger.
 */

import { useEffect, useRef, useState } from "react";
import type { Cash } from "../types";

const money = (n: number) =>
  n.toLocaleString("en-US", { style: "currency", currency: "USD" });

export function Ledger({ cash }: { cash: Cash | null }) {
  const [delta, setDelta] = useState<number | null>(null);
  const [dropped, setDropped] = useState(false);
  const prev = useRef<number | null>(null);

  useEffect(() => {
    if (!cash) return;
    if (prev.current != null && cash.balance < prev.current) {
      setDelta(cash.balance - prev.current);
      setDropped(true);
      const t = setTimeout(() => setDropped(false), 1400);
      prev.current = cash.balance;
      return () => clearTimeout(t);
    }
    prev.current = cash.balance;
  }, [cash?.balance]);

  if (!cash) {
    return (
      <section className="card">
        <div className="card-head">
          <h2>The Ledger</h2>
        </div>
        <div className="empty">No figures yet.</div>
      </section>
    );
  }

  const paidRefs = new Set(cash.payments_made.map((p) => `${p.kind}:${p.ref_id}`));

  return (
    <section className="card">
      <div className="card-head">
        <h2>The Ledger</h2>
        <span className="hint">{cash.account}</span>
      </div>

      <div className="ledger-total">
        <div className="ledger-label">Checking balance</div>
        <div className={`ledger-amount${dropped ? " dropped" : ""}`}>
          {money(cash.balance)}
        </div>
        <div className="ledger-delta">{delta ? money(delta) : ""}</div>
      </div>

      <div className="ledger-rows">
        {cash.obligations.map((o) => {
          const settled = paidRefs.has(
            `${o.kind === "vendor_invoice" ? "invoice" : o.kind}:${o.ref_id}`,
          );
          return (
            <div
              key={`${o.kind}-${o.ref_id}`}
              className={`ledger-row${o.is_overdue && !settled ? " overdue" : ""}${settled ? " paid" : ""}`}
            >
              <span className="who">
                {o.owed_to}
                <small>
                  {o.description} · due {o.due_date}
                  {o.is_overdue && !settled
                    ? ` · ${Math.abs(o.days_until_due)}d overdue`
                    : ""}
                </small>
              </span>
              <span className="amt">{money(o.amount)}</span>
            </div>
          );
        })}

        {cash.payments_made.map((p) => (
          <div key={`pay-${p.id}`} className="ledger-row paid">
            <span className="who">
              Paid · {p.kind}
              <small>
                {p.paid_at} · approved by {p.approved_by}
              </small>
            </span>
            <span className="amt">−{money(p.amount)}</span>
          </div>
        ))}

        <div className="ledger-row" style={{ borderTop: "1px solid var(--rule-strong)" }}>
          <span className="who">
            <strong>If every open obligation were settled</strong>
            {/* Once this month's rent is paid the lease rolls to the next
                cycle, so a fresh rent obligation reappears immediately. The
                figure can therefore go negative without anything being wrong —
                it is telling you the shop cannot cover what is ahead of it,
                which is the actual situation. */}
            <small>
              {cash.remaining_if_all_paid < 0
                ? "includes the next rent cycle — the shop cannot cover all of it"
                : "against the current balance"}
            </small>
          </span>
          <span
            className="amt"
            style={{
              fontWeight: 700,
              color: cash.remaining_if_all_paid < 250 ? "var(--alarm)" : "inherit",
            }}
          >
            {money(cash.remaining_if_all_paid)}
          </span>
        </div>
      </div>
    </section>
  );
}
