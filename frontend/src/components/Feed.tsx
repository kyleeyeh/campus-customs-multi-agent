/**
 * The live feed — what each agent is saying and doing, as it happens.
 *
 * Two editorial decisions make this readable rather than a log dump:
 *
 * 1. Framework noise is filtered out. pydantic-ai's `final_result` is how an
 *    agent returns its answer, and `delegate` duplicates the delegation event
 *    we already draw more legibly. Neither is a thing a person did, so neither
 *    appears. Tool *results* are also hidden — the call says what happened, the
 *    result is a wall of JSON — except when one is a refusal, which is the most
 *    interesting thing that can occur.
 *
 * 2. Delegation depth becomes indentation. A reply from someone a specialist
 *    pulled in sits further right than the boss's own line, so the shape of the
 *    conversation is visible without reading it.
 */

import { useEffect, useRef } from "react";
import type { AgentEvent } from "../types";
import { castFor, narrate } from "../cast";

const HIDE_TOOLS = new Set(["final_result", "delegate"]);

function isRefusal(e: AgentEvent): boolean {
  if (e.event !== "tool_result") return false;
  const r = e.tool_result;
  if (r && typeof r === "object") {
    const o = r as Record<string, unknown>;
    return o.refused === true || typeof o.error === "string";
  }
  return typeof r === "string" && r.includes("REFUSED");
}

function refusalText(e: AgentEvent): string {
  const r = e.tool_result as Record<string, unknown> | null;
  if (r && typeof r === "object") {
    return String(r.error ?? r.refused ?? "refused");
  }
  return String(e.tool_result ?? "refused");
}

export function visibleBeats(events: AgentEvent[]): AgentEvent[] {
  return events.filter((e) => {
    if (e.event === "model_request") return false;
    if (e.tool_name && HIDE_TOOLS.has(e.tool_name)) return false;
    if (e.event === "tool_result") return isRefusal(e);
    return true;
  });
}

interface Props {
  events: AgentEvent[];
  running: boolean;
}

export function Feed({ events, running }: Props) {
  const endRef = useRef<HTMLDivElement>(null);
  const beats = visibleBeats(events);

  useEffect(() => {
    if (running) endRef.current?.scrollIntoView({ block: "nearest" });
  }, [beats.length, running]);

  if (beats.length === 0) {
    return (
      <div className="empty">
        {running
          ? "The team is gathering…"
          : "Pick a ticket and send the team in."}
      </div>
    );
  }

  return (
    <div className="feed">
      {beats.map((e) => {
        const who = castFor(e.agent);
        const target = castFor(e.to_agent);
        const cls = [
          "beat",
          `depth-${Math.min(e.depth, 2)}`,
          who ? "by-agent" : "",
          e.event === "error" ? "is-error" : "",
          e.event === "budget_refused" || isRefusal(e) ? "is-refusal" : "",
          e.event === "delegation" || e.event === "delegation_result" ? "is-handoff" : "",
        ]
          .filter(Boolean)
          .join(" ");

        return (
          <div
            key={`${e.run_id}-${e.seq}`}
            className={cls}
            style={{ ["--c" as string]: who?.color ?? "var(--ink-faint)" }}
          >
            <div className="beat-dot">{who?.initials ?? "··"}</div>
            <div className="beat-main">
              <div className="beat-who">
                {who?.character ?? e.agent ?? "The desk"}
                {target && e.event === "delegation" && (
                  <>
                    <span className="arrow">→</span>
                    <span style={{ color: target.color }}>{target.character}</span>
                  </>
                )}
                <small>{new Date(e.ts).toLocaleTimeString()}</small>
              </div>
              <div className="beat-text">{body(e)}</div>
            </div>
          </div>
        );
      })}
      <div ref={endRef} />
    </div>
  );

  function body(e: AgentEvent) {
    switch (e.event) {
      case "run_start":
        return <em>takes the ticket and reads it over.</em>;
      case "tool_call":
        return (
          <>
            {narrate(e.tool_name)} <span className="tool-chip">{e.tool_name}</span>
          </>
        );
      case "tool_result":
        return <>refused — {refusalText(e)}</>;
      case "delegation":
        return <>“{e.said ?? "a hand, please"}”</>;
      case "delegation_result":
        return <>“{e.said ?? "done"}”</>;
      case "budget_refused":
        return <>held back — {e.said}</>;
      case "error":
        return <>{e.error}</>;
      case "run_end":
        return <em>{e.said ?? "wraps up."}</em>;
      default:
        return e.said ?? e.tool_name ?? e.event;
    }
  }
}
