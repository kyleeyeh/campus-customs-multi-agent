/**
 * The Rosebud Operations Desk.
 *
 * One screen, three columns: the board on the left, the cast and what they are
 * doing in the middle, the money and the decisions on the right. No routing, no
 * tabs — a desk you sit at should show you everything at once.
 *
 * POLLING
 * -------
 * A run takes 15–35 seconds, so `POST /tickets/{id}/run` returns a run_id and
 * this polls `/events?since_seq=` while it works. Only unseen events come back,
 * so a long run does not re-download its own history on every tick. When the
 * run ends, the board, ledger and approvals are refetched once — a ticket that
 * just resolved should look resolved immediately, not after the next poll.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "./api";
import type { AgentEvent, Approval, Board, Cash, RunRecord, Ticket } from "./types";
import { CAST } from "./cast";
import { Sign } from "./components/Sign";
import { TicketList } from "./components/TicketList";
import { CastRow, type AgentActivity } from "./components/CastRow";
import { Feed } from "./components/Feed";
import { Ledger } from "./components/Ledger";
import { Approvals } from "./components/Approvals";
import { Summary } from "./components/Summary";

const POLL_MS = 1200;

export default function App() {
  const [board, setBoard] = useState<Board | null>(null);
  const [cash, setCash] = useState<Cash | null>(null);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const [run, setRun] = useState<RunRecord | null>(null);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [online, setOnline] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);

  const seqRef = useRef(0);
  const running = run?.status === "running";

  /* ------------------------------------------------------------ loading -- */
  const refresh = useCallback(async () => {
    try {
      const [b, c, a] = await Promise.all([
        api.board(),
        api.cash(),
        api.approvals(),
      ]);
      setBoard(b);
      setCash(c);
      setApprovals(a.approvals);
      setOnline(true);
      setError(null);
      setSelectedId((cur) => cur ?? b.tickets[0]?.id ?? null);
    } catch (err) {
      if (err instanceof ApiError && err.offline) {
        setOnline(false);
        setError(err.message);
      } else {
        setError(err instanceof Error ? err.message : String(err));
      }
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  /* ---------------------------------------------------------- the runs -- */
  async function start(ticketId: number) {
    setStarting(true);
    setError(null);
    setEvents([]);
    seqRef.current = 0;
    try {
      const started = await api.startRun(ticketId);
      setRun({
        run_id: started.run_id,
        ticket_id: ticketId,
        status: "running",
        started_at: new Date().toISOString(),
        model: "",
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setStarting(false);
    }
  }

  // Poll for new activity while a run is in flight.
  useEffect(() => {
    if (!run || run.status !== "running") return;
    let cancelled = false;

    const tick = async () => {
      try {
        const page = await api.events({
          ticketId: run.ticket_id,
          sinceSeq: seqRef.current,
          limit: 200,
        });
        if (cancelled) return;
        if (page.events.length) {
          seqRef.current = page.latest_seq;
          setEvents((prev) => [...prev, ...page.events]);
        }

        // Approvals and cash are refreshed mid-run, not just at the end. An
        // agent parks a request several seconds before it finishes its turn,
        // and Moira's panel claiming "nothing pending" while the feed shows
        // request_approval scrolling past would be plainly wrong.
        const [a, c] = await Promise.all([api.approvals(), api.cash()]);
        if (cancelled) return;
        setApprovals(a.approvals);
        setCash(c);

        const record = await api.run(run.run_id);
        if (cancelled) return;
        if (record.status !== "running") {
          setRun(record);
          await refresh();
        }
      } catch {
        /* a dropped poll is not worth surfacing; the next tick retries */
      }
    };

    const id = setInterval(tick, POLL_MS);
    void tick();
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [run?.run_id, run?.status, refresh]);

  // Clicking a ticket that already ran should show what happened, not an empty
  // floor. Two constraints keep that honest:
  //
  //  * The audit trail outlives a database reset — deliberately, it is
  //    append-only history. So a ticket sitting at 'open' has NOT been worked
  //    on the board as it currently stands, and showing it beats from a
  //    pre-reset run would be straightforwardly misleading. Skip those.
  //  * A ticket that has been run more than once would otherwise show every
  //    run's beats concatenated, so only the most recent run is kept.
  const selectedStatus = board?.tickets.find((t) => t.id === selectedId)?.status;

  useEffect(() => {
    if (selectedId == null || running) return;
    if (selectedStatus === "open") return;
    if (events.some((e) => e.ticket_id === selectedId)) return;
    let cancelled = false;
    void (async () => {
      try {
        const page = await api.events({ ticketId: selectedId, limit: 200 });
        if (cancelled || !page.events.length) return;
        const latestRun = page.events[page.events.length - 1].run_id;
        setEvents((prev) => [
          ...prev,
          ...page.events.filter((e) => e.run_id === latestRun),
        ]);
      } catch {
        /* history is a nicety; the summary still stands without it */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedId, selectedStatus, running]);

  /* -------------------------------------------------------- derivations -- */
  const selected: Ticket | null = useMemo(
    () => board?.tickets.find((t) => t.id === selectedId) ?? null,
    [board, selectedId],
  );

  // Events belonging to the ticket on screen. Keeps the feed honest when you
  // click away from a ticket mid-run.
  const shownEvents = useMemo(
    () => events.filter((e) => e.ticket_id === selectedId),
    [events, selectedId],
  );

  const activity = useMemo(() => {
    const acc: Record<string, AgentActivity> = {};
    for (const key of Object.keys(CAST)) {
      acc[key] = { spoke: false, toolCalls: 0, lastTool: null, lastSaid: null };
    }
    for (const e of shownEvents) {
      const a = e.agent && acc[e.agent] ? acc[e.agent] : null;
      if (!a) continue;
      a.spoke = true;
      if (e.event === "tool_call" && e.tool_name !== "final_result") {
        a.toolCalls += 1;
        a.lastTool = e.tool_name;
      }
      if ((e.event === "delegation_result" || e.event === "run_end") && e.said) {
        a.lastSaid = e.said;
        a.lastTool = null;
      }
    }
    return acc;
  }, [shownEvents]);

  // Whoever acted most recently is "on stage".
  const activeAgent = useMemo(() => {
    for (let i = shownEvents.length - 1; i >= 0; i--) {
      const e = shownEvents[i];
      if (e.agent && e.agent in CAST && e.event !== "run_end") return e.agent;
    }
    return null;
  }, [shownEvents]);

  const pendingForSelected = approvals.filter(
    (a) => a.status === "pending" && (!selectedId || a.ticket_id === selectedId),
  );

  /* --------------------------------------------------------- decisions -- */
  async function decide(id: number, decision: "approved" | "rejected") {
    const result = await api.decide(id, decision);
    await refresh();
    return result;
  }

  async function doReset() {
    if (!confirm("Reset the shop to its original state? Any run so far is undone.")) return;
    try {
      await api.reset();
      setRun(null);
      setEvents([]);
      seqRef.current = 0;
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  const alreadyWorked = selected ? !selected.is_open : false;

  /* -------------------------------------------------------------- view -- */
  return (
    <div className="desk">
      <Sign
        online={online}
        shopDate={board?.shop_date ?? null}
        balance={cash?.balance ?? null}
        openCount={board?.open ?? 0}
        resolvedCount={board?.resolved ?? 0}
      />

      <div className="desk-body">
        {/* ---------------------------------------------------- left -- */}
        <div className="col">
          {error && (
            <div className="banner bad">
              <span>{error}</span>
            </div>
          )}

          <TicketList
            tickets={board?.tickets ?? []}
            selectedId={selectedId}
            runningId={running ? run!.ticket_id : null}
            onSelect={(id) => setSelectedId(id)}
          />

          <section className="card">
            <div className="card-body">
              <div className="toolbar">
                <button
                  className="btn btn-primary"
                  disabled={!selected || running || starting || !online}
                  onClick={() => selected && start(selected.id)}
                >
                  {running
                    ? "Team is working…"
                    : starting
                      ? "Rounding them up…"
                      : alreadyWorked
                        ? "Run it again"
                        : "Send in the team"}
                </button>
              </div>
              <p style={{ fontSize: 12, color: "var(--ink-faint)", margin: "9px 0 0" }}>
                {selected
                  ? `Johnny takes ticket #${selected.id} and decides who to call.`
                  : "Pick a ticket from the board."}
              </p>
            </div>
          </section>

          <section className="card">
            <div className="card-body">
              <div className="toolbar">
                <button className="btn btn-ghost" onClick={() => void refresh()}>
                  Refresh
                </button>
                <button className="btn btn-ghost" onClick={() => void doReset()} disabled={running}>
                  Reset the shop
                </button>
              </div>
            </div>
          </section>
        </div>

        {/* -------------------------------------------------- centre -- */}
        <div className="col">
          <section className="card">
            <div className="card-head">
              <h2>The Cast</h2>
              <span className="hint">
                {running ? "live" : selected ? `ticket #${selected.id}` : "standing by"}
              </span>
            </div>
            <div className="card-body">
              <CastRow activity={activity} activeAgent={activeAgent} running={running} />
            </div>
          </section>

          <section className="card">
            <div className="card-head">
              <h2>On the floor</h2>
              <span className="hint">
                {running ? (
                  <span className="pill live">running</span>
                ) : (
                  `${shownEvents.length} beats`
                )}
              </span>
            </div>
            <div className="card-body flush">
              <Feed events={shownEvents} running={running} />
            </div>
          </section>

          <Summary ticket={selected} run={run} events={shownEvents} />
        </div>

        {/* --------------------------------------------------- right -- */}
        <div className="col col-right">
          <Ledger cash={cash} />
          <Approvals
            approvals={selectedId ? pendingForSelected : approvals}
            onDecide={decide}
          />
        </div>
      </div>

      <div className="footnote">
        Campus Customs · agents prepare, Moira approves, and only then does the money move.
      </div>
    </div>
  );
}
