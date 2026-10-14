/**
 * The cast.
 *
 * Each agent is played by the Schitt's Creek character who already does that
 * job on the show. This is not decoration — it is the fastest legend the
 * dashboard has. Once you know David runs a shop and panics about empty
 * shelves, you know what the inventory agent does without reading a label.
 *
 *   boss              Johnny Rose    — ran a business, makes the final call
 *   inventory         David Rose     — Rose Apothecary; curates and counts stock
 *   accounting        Patrick Brewer — literally does the books at the shop
 *   facilities        Stevie Budd    — runs the motel; the property is hers
 *   customer_service  Alexis Rose    — PR background; writes the charming note
 *
 * Moira is deliberately NOT an agent. She presides over approvals instead,
 * which is the one thing no agent on this team is permitted to do. Nothing
 * moves until she assents, and she is magnificent about it.
 */

export type AgentKey =
  | "boss"
  | "inventory"
  | "accounting"
  | "facilities"
  | "customer_service";

export interface CastMember {
  agent: AgentKey;
  character: string;
  initials: string;
  role: string;
  /** What this character would mutter while working. Flavour, clearly marked. */
  idle: string;
  working: string;
  /** Signature colour, drawn from how the character actually dresses. */
  color: string;
  ink: string;
  tint: string;
}

export const CAST: Record<AgentKey, CastMember> = {
  boss: {
    agent: "boss",
    character: "Johnny Rose",
    initials: "JR",
    role: "Runs the desk · routes every ticket",
    idle: "Let's take a look at what we've got.",
    working: "Alright — who do I need on this?",
    color: "#2f3e55",
    ink: "#ffffff",
    tint: "#eaeef5",
  },
  inventory: {
    agent: "inventory",
    character: "David Rose",
    initials: "DR",
    role: "Stock & restock · counts every size",
    idle: "The shelves are curated, thank you.",
    working: "Um. We have none of those. In that size.",
    color: "#242428",
    ink: "#ffffff",
    tint: "#ebebed",
  },
  accounting: {
    agent: "accounting",
    character: "Patrick Brewer",
    initials: "PB",
    role: "Cash, margins & invoices",
    idle: "Books are balanced. For now.",
    working: "So here's the number, and you're not going to love it.",
    color: "#45749f",
    ink: "#ffffff",
    tint: "#e9f0f7",
  },
  facilities: {
    agent: "facilities",
    character: "Stevie Budd",
    initials: "SB",
    role: "The premises · lease & landlord",
    idle: "Rent's a thing that happens. Monthly.",
    working: "Yeah, so the landlord wants money again.",
    color: "#5f6b4e",
    ink: "#ffffff",
    tint: "#edefe8",
  },
  customer_service: {
    agent: "customer_service",
    character: "Alexis Rose",
    initials: "AR",
    role: "Drafts what the shop says",
    idle: "I'll handle the people part.",
    working: "Okay, but like — how do we say this nicely?",
    color: "#c2748c",
    ink: "#ffffff",
    tint: "#f8edf1",
  },
};

/** Moira presides over approvals. She is not an agent and never will be. */
export const MOIRA = {
  character: "Moira Rose",
  initials: "MR",
  role: "Approvals · nothing moves without her",
  color: "#58355e",
  ink: "#ffffff",
  tint: "#f1eaf3",
  /** Shown when there is nothing to decide. */
  quiet: "I have no pending business. Bask in it.",
  /** Shown when money is waiting on a human. */
  waiting: "Something requires my assent.",
};

export const CAST_LIST = Object.values(CAST);

export function castFor(agent: string | null | undefined): CastMember | null {
  if (!agent) return null;
  return CAST[agent as AgentKey] ?? null;
}

/** Narration for a tool call, in the voice of whoever called it. */
export const TOOL_NARRATION: Record<string, string> = {
  check_stock: "counting what's actually on the shelf",
  find_restock_vendor: "working out who can make more",
  get_cash_position: "opening the books",
  get_ticket: "reading the ticket properly",
  list_open_tickets: "looking over the board",
  get_lease: "digging out the lease",
  evaluate_discount: "doing the margin maths",
  request_approval: "putting it in front of Moira",
  list_approvals: "checking what's already been decided",
  pay_invoice: "settling the invoice",
  pay_rent: "paying the landlord",
  create_purchase_order: "drafting a restock order",
  save_draft_message: "writing the note",
  update_ticket: "closing the ticket out",
  get_shop_policy: "checking the house rules",
  delegate: "pulling someone else in",
  final_result: "wrapping up",
};

export function narrate(tool: string | null | undefined): string {
  if (!tool) return "";
  return TOOL_NARRATION[tool] ?? `calling ${tool}`;
}
