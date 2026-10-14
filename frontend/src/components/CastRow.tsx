/**
 * The cast, standing by.
 *
 * All five are always on screen, but dimmed until they are actually in the
 * scene. That is the single most useful thing this row does: at a glance you
 * can see that ticket 102 only ever involved Stevie, while 101 pulled in four
 * people. A roster that only showed active agents would hide exactly that.
 *
 * The character currently working gets a glowing ring and three bouncing dots.
 */

import { CAST_LIST, narrate, type AgentKey } from "../cast";

export interface AgentActivity {
  spoke: boolean;
  toolCalls: number;
  lastTool: string | null;
  lastSaid: string | null;
}

interface Props {
  activity: Record<string, AgentActivity>;
  activeAgent: string | null;
  running: boolean;
}

export function CastRow({ activity, activeAgent, running }: Props) {
  return (
    <div className="cast-row">
      {CAST_LIST.map((c) => {
        const act = activity[c.agent as AgentKey];
        const isActive = running && activeAgent === c.agent;
        const line = isActive
          ? act?.lastTool
            ? `${narrate(act.lastTool)}…`
            : c.working
          : act?.lastSaid
            ? act.lastSaid
            : c.idle;

        return (
          <div
            key={c.agent}
            className={`cast${isActive ? " active" : ""}${act?.spoke ? " spoke" : ""}`}
            style={{ ["--c" as string]: c.color }}
          >
            <div className="cast-face">
              <div className="avatar">{c.initials}</div>
              <div style={{ minWidth: 0 }}>
                <div className="cast-name">{c.character}</div>
                <div className="cast-job">{c.agent.replace("_", " ")}</div>
              </div>
            </div>

            <div className="cast-line">
              {line.length > 72 ? line.slice(0, 72) + "…" : line}
            </div>

            <div className="cast-foot">
              <span>{isActive ? "on it" : act?.spoke ? "done" : "standing by"}</span>
              {isActive ? (
                <span className="dots">
                  <i />
                  <i />
                  <i />
                </span>
              ) : (
                <span className="cast-count">{act?.toolCalls ?? 0} tools</span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
