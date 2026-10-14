/**
 * What each agent actually did, once the run is over.
 *
 * Built from the same event stream the live feed draws, collapsed per agent:
 * the line they signed off with, and the tools they reached for. The live feed
 * answers "what is happening"; this answers "what did they do" — and the second
 * question is the one you ask after the fact, so it gets its own panel rather
 * than making you re-read a transcript.
 *
 * The boss's resolution sits on top because that is the sentence a shop owner
 * would actually act on.
 */

import type { AgentEvent, RunRecord, Ticket } from "../types";
import { CAST, castFor, type AgentKey } from "../cast";

const HIDE_TOOLS = new Set(["final_result", "delegate"]);

interface Props {
  ticket: Ticket | null;
  run: RunRecord | null;
  events: AgentEvent[];
}

export function Summary({ ticket, run, events }: Props) {
  if (!ticket) return null;

  const outcome = run?.result?.outcome ?? null;
  const resolution = outcome?.resolution ?? ticket.resolution;
  if (!resolution && events.length === 0) return null;

  // Collapse the event stream to one entry per agent that appeared.
  const perAgent = new Map<string, { tools: string[]; said: string | null }>();
  for (const e of events) {
    if (!e.agent || !(e.agent in CAST)) continue;
    const entry = perAgent.get(e.agent) ?? { tools: [], said: null };
    if (e.event === "tool_call" && e.tool_name && !HIDE_TOOLS.has(e.tool_name)) {
      if (!entry.tools.includes(e.tool_name)) entry.tools.push(e.tool_name);
    }
    if (e.event === "delegation_result" && e.said) entry.said = e.said;
    if (e.event === "run_end" && e.said) entry.said = e.said;
    perAgent.set(e.agent, entry);
  }

  const stats = run?.result;

  return (
    <section className="card summary-card">
      <div className="card-head">
        <h2>How it went</h2>
        {outcome && <span className="hint">{outcome.status.replace("_", " ")}</span>}
      </div>

      {resolution && (
        <div className="resolution">
          <strong>The call</strong>
          {resolution}
        </div>
      )}

      {[...perAgent.entries()].map(([agent, entry]) => {
        const c = castFor(agent);
        if (!c) return null;
        return (
          <div className="did" key={agent}>
            <div className="avatar" style={{ background: c.color }}>
              {c.initials}
            </div>
            <div className="did-body">
              <div className="did-who">
                {c.character}{" "}
                <span style={{ color: "var(--ink-faint)", fontWeight: 400, fontSize: 11 }}>
                  {agent.replace("_", " ")}
                </span>
              </div>
              {entry.said && (
                <div className="did-what">
                  {entry.said.length > 190 ? entry.said.slice(0, 190) + "…" : entry.said}
                </div>
              )}
              {entry.tools.length > 0 && (
                <div className="did-tools">
                  {entry.tools.map((t) => (
                    <span className="tool-chip" key={t}>
                      {t}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>
        );
      })}

      {outcome && outcome.facts_used.length > 0 && (
        <div className="facts">
          <h4>What the decision rested on</h4>
          <ul>
            {outcome.facts_used.slice(0, 7).map((f, i) => (
              <li key={i}>{f}</li>
            ))}
          </ul>
        </div>
      )}

      {outcome?.next_step && (
        <div className="facts">
          <h4>What you need to do</h4>
          <div style={{ fontSize: 13 }}>{outcome.next_step}</div>
        </div>
      )}

      {stats && (
        <div className="run-stats">
          <span>
            <b>{stats.duration_s}s</b> on the clock
          </span>
          <span>
            <b>{stats.delegations}</b> handoffs
          </span>
          <span>
            <b>{stats.tool_calls}</b> tool calls
          </span>
          <span>
            <b>{(stats.input_tokens + stats.output_tokens).toLocaleString()}</b> tokens
          </span>
          <span>
            <b>${stats.cost_usd.toFixed(4)}</b>
          </span>
          <span>
            moved <b>${(outcome?.money_moved ?? 0).toFixed(2)}</b>
          </span>
        </div>
      )}
    </section>
  );
}

export type { AgentKey };
