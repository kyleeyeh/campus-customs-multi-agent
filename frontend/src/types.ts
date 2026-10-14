/** Shapes returned by the FastAPI backend in backend/main.py. */

export type TicketStatus = "open" | "waiting_approval" | "resolved" | "declined";

export interface Ticket {
  id: number;
  type: string;
  requester: string;
  subject: string;
  sku: string | null;
  size: string | null;
  qty: number | null;
  lease_id: number | null;
  invoice_id: number | null;
  status: TicketStatus;
  notes: string | null;
  assignee: string | null;
  resolution: string | null;
  resolved_at: string | null;
  is_open: boolean;
  is_resolved: boolean;
  pending_approvals: number[];
}

export interface Board {
  shop_date: string;
  count: number;
  open: number;
  resolved: number;
  tickets: Ticket[];
}

export type AuditEvent =
  | "run_start"
  | "delegation"
  | "delegation_result"
  | "tool_call"
  | "tool_result"
  | "budget_refused"
  | "error"
  | "run_end"
  | "model_request";

export interface AgentEvent {
  run_id: string;
  seq: number;
  ts: string;
  ticket_id: number | null;
  event: AuditEvent;
  agent: string | null;
  to_agent: string | null;
  depth: number;
  tool_name: string | null;
  tool_args: Record<string, unknown> | null;
  tool_result: unknown;
  said: string | null;
  model: string | null;
  error: string | null;
}

export interface EventsPage {
  count: number;
  total_matching: number;
  latest_seq: number;
  events: AgentEvent[];
}

export interface Obligation {
  kind: string;
  ref_id: number;
  description: string;
  owed_to: string;
  amount: number;
  due_date: string;
  days_until_due: number;
  is_overdue: boolean;
}

export interface Payment {
  id: number;
  kind: string;
  ref_id: number;
  amount: number;
  paid_at: string;
  approved_by: string;
}

export interface Cash {
  account: string;
  balance: number;
  shop_date: string;
  total_owed: number;
  remaining_if_all_paid: number;
  overdue_count: number;
  obligations: Obligation[];
  payments_made: Payment[];
}

export interface Approval {
  id: number;
  ticket_id: number;
  kind: "payment" | "purchase_order" | "discount";
  summary: string;
  payload: string;
  rationale: string | null;
  amount: number | null;
  requested_by: string;
  status: "pending" | "approved" | "rejected";
  decided_by: string | null;
  decided_at: string | null;
  decision_note: string | null;
  created_at: string;
}

export interface RunStarted {
  run_id: string;
  ticket_id: number;
  status: string;
  message: string;
}

export interface RunRecord {
  run_id: string;
  ticket_id: number;
  status: "running" | "done" | "failed";
  started_at: string;
  finished_at?: string;
  model: string;
  error?: string | null;
  result?: {
    delegations: number;
    tool_calls: number;
    input_tokens: number;
    output_tokens: number;
    cost_usd: number;
    duration_s: number;
    outcome: {
      ticket_id: number;
      status: TicketStatus;
      assignee: string;
      resolution: string;
      delegated_to: string[];
      facts_used: string[];
      policy_cited: string[];
      approval_ids: number[];
      draft_ids: number[];
      money_moved: number;
      next_step: string | null;
    } | null;
  };
}

export interface ApprovalResult {
  approval_id: number;
  decision: "approved" | "rejected";
  decided_by: string;
  kind?: string;
  executed: boolean;
  execution?: Record<string, unknown>;
  balance_after?: number;
  note: string;
}
