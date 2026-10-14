/**
 * Typed client for the Campus Customs backend.
 *
 * The backend runs at http://localhost:8000 (started from backend/ with
 * `uvicorn main:app --reload --port 8000`). This desk runs on 5173, which is
 * the origin that backend's CORS middleware allows.
 *
 * Every call goes through `request`, so a backend that is simply not running
 * produces one clear message — "can't reach the back office" — rather than five
 * different fetch errors scattered across the UI.
 */

import type {
  Approval,
  ApprovalResult,
  Board,
  Cash,
  EventsPage,
  RunRecord,
  RunStarted,
} from "./types";

export const API_BASE = "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public offline = false,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...init,
    });
  } catch {
    throw new ApiError(
      "Can't reach the back office. Is the backend running on port 8000?",
      0,
      true,
    );
  }

  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      /* non-JSON error body; the status line will do */
    }
    throw new ApiError(detail, res.status);
  }
  return (await res.json()) as T;
}

export const api = {
  health: () => request<{ ok: boolean; balance: number }>("/health"),

  board: () => request<Board>("/tickets"),

  cash: () => request<Cash>("/cash"),

  approvals: (status?: string) =>
    request<{ count: number; approvals: Approval[] }>(
      `/approvals${status ? `?status=${status}` : ""}`,
    ),

  /** Start the team on a ticket. Returns immediately; poll events to watch. */
  startRun: (ticketId: number) =>
    request<RunStarted>(`/tickets/${ticketId}/run`, { method: "POST" }),

  run: (runId: string) => request<RunRecord>(`/runs/${runId}`),

  /**
   * Poll for new activity. `sinceSeq` is the highest seq already drawn, so the
   * board only ever fetches what it has not seen.
   */
  events: (opts: { ticketId?: number; sinceSeq?: number; limit?: number }) => {
    const q = new URLSearchParams();
    if (opts.ticketId != null) q.set("ticket_id", String(opts.ticketId));
    if (opts.sinceSeq != null) q.set("since_seq", String(opts.sinceSeq));
    q.set("limit", String(opts.limit ?? 120));
    return request<EventsPage>(`/events?${q}`);
  },

  decide: (approvalId: number, decision: "approved" | "rejected", note?: string) =>
    request<ApprovalResult>(`/approvals/${approvalId}/approve`, {
      method: "POST",
      body: JSON.stringify({ decision, decided_by: "Kyle Yeh", note }),
    }),

  reset: () =>
    request<{ reset: boolean; balance: number; open_tickets: number }>("/reset", {
      method: "POST",
    }),
};
