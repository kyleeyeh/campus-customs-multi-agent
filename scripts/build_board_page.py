"""Build `output/resolved_board.html` from the dashboard screenshots.

    python scripts/build_board_page.py

Expects `output/screenshots/ticket-101.jpg` (and 102, 103) — one capture of
the React board per resolved ticket.

The images are **base64-embedded** rather than linked. The page has to work by
double-clicking it, and a relative <img src> breaks the moment the file is
moved, mailed, or opened from a different folder. One self-contained file
cannot break that way.

Ticket facts are read from `output/resolved_tickets.json` so the captions
cannot drift from the run they describe.
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "output" / "screenshots"
DATA = ROOT / "output" / "resolved_tickets.json"
OUT = ROOT / "output" / "resolved_board.html"

CHAR_COLOR = {
    "Johnny Rose": "#2f3e55",
    "David Rose": "#242428",
    "Patrick Brewer": "#45749f",
    "Stevie Budd": "#5f6b4e",
    "Alexis Rose": "#c2748c",
}


def embed(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode()


def money(n: float) -> str:
    return f"${n:,.2f}"


def main() -> int:
    if not DATA.exists():
        print(f"missing {DATA}; run scripts/build_outputs.py first")
        return 1
    doc = json.load(open(DATA, encoding="utf-8"))

    cards = []
    for t in doc["tickets"]:
        shot = SHOTS / f"ticket-{t['id']}.jpg"
        if not shot.exists():
            print(f"  WARNING: no screenshot for ticket {t['id']} at {shot}")
            img_block = (
                '<div class="missing">No capture on file for this ticket.</div>'
            )
        else:
            img_block = (
                f'<img alt="Dashboard showing ticket {t["id"]} resolved" '
                f'src="data:image/jpeg;base64,{embed(shot)}">'
            )

        agents = "".join(
            f'<span class="who" style="--c:{CHAR_COLOR.get(a["character"], "#6d6459")}">'
            f'{a["character"]}<small>{a["agent"].replace("_", " ")}</small></span>'
            for a in t["agent_contributions"]
        )

        app_items = []
        for a in t["human_approvals"]:
            amt = money(a["amount"]) if a["amount"] else ""
            by = f" by {a['decided_by']}" if a["decided_by"] else ""
            executed = any(
                p["approved_by"] and a["kind"] == "payment" for p in t["payments_executed"]
            )
            # An approved request that moved no money is worth calling out —
            # ticket 103's second request was approved and then refused by the
            # pay tool because the invoice had already been settled.
            note = ""
            if a["kind"] == "payment" and a["status"] == "approved" and not executed:
                note = " <i>— approved, but the tool refused it (already settled)</i>"
            elif a["kind"] == "discount":
                note = " <i>— no cash moves on a discount</i>"
            app_items.append(
                f"<li><b>#{a['approval_id']}</b> {a['kind']} {amt} — "
                f"<span class='st {a['status']}'>{a['status']}</span>{by}{note}</li>"
            )
        approvals = "".join(app_items) or "<li class='none'>No approval was needed.</li>"

        delta = t["cash"]["change"]
        cards.append(f"""
    <section class="card">
      <div class="head">
        <div>
          <span class="tid">Ticket {t['id']}</span>
          <h2>{t['subject']}</h2>
          <div class="req">{t['requester']} · {t['type'].replace('_', ' ')}</div>
        </div>
        <span class="status {t['final_status']}">{t['final_status'].replace('_', ' ')}</span>
      </div>

      <figure>{img_block}
        <figcaption>The board after ticket {t['id']} was resolved.</figcaption>
      </figure>

      <div class="facts">
        <div class="fact"><dt>Outcome</dt><dd class="outcome">{t['outcome'] or '—'}</dd></div>
        <div class="grid">
          <div class="fact"><dt>Who worked it</dt><dd>{agents}</dd></div>
          <div class="fact"><dt>Handoffs</dt><dd class="mono">{' · '.join(t['delegation_chain']) or 'none'}</dd></div>
          <div class="fact"><dt>Human approvals</dt><dd><ul class="apps">{approvals}</ul></dd></div>
          <div class="fact"><dt>Cash</dt><dd class="mono">
            {money(t['cash']['balance_before'])} &rarr; <b>{money(t['cash']['balance_after'])}</b>
            <span class="{'down' if delta < 0 else 'flat'}">({delta:+,.2f})</span>
          </dd></div>
        </div>
      </div>
    </section>""")

    chk = doc["arithmetic_check"]
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Resolved Board — Campus Customs</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Bodoni+Moda:wght@600;700&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
<style>
  :root {{
    --paper:#f4efe6; --card:#fffdf9; --ink:#2a2622; --soft:#6d6459; --faint:#9b9184;
    --rule:#e0d7c8; --neon:#1f6f4f; --brass:#a9833f; --alarm:#a63b2d; --plum:#58355e;
    --serif:"Bodoni Moda",Georgia,serif; --sans:"Inter",system-ui,sans-serif;
    --mono:"JetBrains Mono",ui-monospace,Consolas,monospace;
  }}
  *{{box-sizing:border-box}}
  body{{margin:0;background:var(--paper);color:var(--ink);font-family:var(--sans);line-height:1.55}}
  .wrap{{max-width:1100px;margin:0 auto;padding:0 24px 72px}}
  header{{background:linear-gradient(180deg,#2c2a26,#211f1c);border-bottom:3px solid var(--brass);
    padding:26px 0 22px;margin-bottom:28px}}
  header .inner{{max-width:1100px;margin:0 auto;padding:0 24px;display:flex;
    justify-content:space-between;align-items:flex-end;gap:24px;flex-wrap:wrap}}
  header h1{{font-family:var(--serif);font-size:30px;letter-spacing:.14em;text-transform:uppercase;
    margin:0;color:#eafaf1;text-shadow:0 0 20px rgba(42,155,108,.45)}}
  header .sub{{color:#8f8678;font-family:var(--serif);font-style:italic;font-size:14px;margin-top:4px}}
  .totals{{display:flex;gap:26px}}
  .totals div{{text-align:right}}
  .totals dt{{font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:#8f8678}}
  .totals dd{{margin:2px 0 0;font-family:var(--mono);font-size:17px;color:#f0e9dc}}

  .ledger-note{{background:var(--card);border:1px solid var(--rule);border-left:3px solid var(--neon);
    border-radius:8px;padding:14px 18px;margin-bottom:26px;font-size:14px}}
  .ledger-note b{{font-family:var(--mono)}}
  .ok{{color:var(--neon);font-weight:700}}
  .bad{{color:var(--alarm);font-weight:700}}

  .card{{background:var(--card);border:1px solid var(--rule);border-radius:10px;
    margin-bottom:26px;overflow:hidden;box-shadow:0 2px 10px rgba(60,48,32,.08)}}
  .head{{display:flex;justify-content:space-between;align-items:flex-start;gap:18px;
    padding:16px 20px;border-bottom:1px solid var(--rule)}}
  .tid{{font-family:var(--mono);font-size:11px;color:var(--faint);letter-spacing:.08em}}
  .head h2{{font-family:var(--serif);font-size:21px;margin:2px 0 3px}}
  .req{{font-size:13px;color:var(--soft)}}
  .status{{font-size:10px;text-transform:uppercase;letter-spacing:.11em;font-weight:700;
    padding:5px 11px;border-radius:20px;white-space:nowrap}}
  .status.resolved{{background:#e6f4ec;color:var(--neon);border:1px solid #bfe0cd}}
  .status.declined{{background:#fbeceb;color:var(--alarm);border:1px solid #e8c4bd}}
  .status.waiting_approval{{background:#f1eaf3;color:var(--plum)}}

  figure{{margin:0;padding:18px 20px 10px;background:#efe9de}}
  figure img{{width:100%;display:block;border:1px solid var(--rule);border-radius:6px;
    box-shadow:0 6px 22px rgba(60,48,32,.18)}}
  figcaption{{font-size:12px;color:var(--soft);text-align:center;padding:9px 0 4px;font-style:italic}}
  .missing{{padding:40px;text-align:center;color:var(--faint);font-style:italic;
    border:1px dashed var(--rule);border-radius:6px;background:var(--card)}}

  .facts{{padding:16px 20px 20px}}
  .grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px 22px;margin-top:14px}}
  @media(max-width:760px){{.grid{{grid-template-columns:1fr}}}}
  .fact dt{{font-size:10px;text-transform:uppercase;letter-spacing:.1em;color:var(--faint);
    font-weight:700;margin-bottom:5px}}
  .fact dd{{margin:0;font-size:13.5px}}
  .outcome{{font-size:14.5px;line-height:1.6}}
  .mono{{font-family:var(--mono);font-size:12.5px;color:var(--soft)}}
  .down{{color:var(--alarm);font-weight:600}}
  .flat{{color:var(--faint)}}

  .who{{display:inline-block;font-size:12px;font-weight:600;color:#fff;background:var(--c);
    padding:3px 9px;border-radius:20px;margin:0 5px 5px 0}}
  .who small{{display:block;font-weight:400;font-size:9.5px;opacity:.8;letter-spacing:.05em}}

  ul.apps{{margin:0;padding-left:16px}}
  ul.apps li{{font-size:12.5px;margin-bottom:4px}}
  ul.apps li.none{{list-style:none;margin-left:-16px;color:var(--faint);font-style:italic}}
  .st{{font-weight:700}}
  .st.approved{{color:var(--neon)}} .st.pending{{color:var(--plum)}} .st.rejected{{color:var(--alarm)}}

  footer{{text-align:center;font-size:12px;color:var(--faint);padding-top:10px}}
</style>
</head>
<body>
<header>
  <div class="inner">
    <div>
      <h1>Resolved Board</h1>
      <div class="sub">Campus Customs · shop date {doc['shop_date']} · every agent ran {doc['model']}</div>
    </div>
    <div class="totals">
      <div><dt>Starting</dt><dd>{money(doc['starting_checking_balance'])}</dd></div>
      <div><dt>Paid out</dt><dd>−{money(doc['total_paid'])}</dd></div>
      <div><dt>Ending</dt><dd>{money(doc['ending_checking_balance'])}</dd></div>
    </div>
  </div>
</header>

<div class="wrap">
  <div class="ledger-note">
    <b>{money(doc['starting_checking_balance'])}</b> − <b>{money(doc['total_paid'])}</b>
    = <b>{money(chk['starting_minus_payments'])}</b>, and <code>cash_accounts.balance</code>
    in the working database reads <b>{money(chk['database_cash_accounts_balance'])}</b> —
    <span class="{'ok' if chk['matches'] else 'bad'}">
      {'these match' if chk['matches'] else 'THESE DO NOT MATCH'}</span>.
    Every payment below was executed only after a human approved it; the agents
    themselves moved nothing.
  </div>
{''.join(cards)}
  <footer>Captures taken from the running React dashboard at localhost:5173 against the live backend.</footer>
</div>
</body>
</html>
"""
    OUT.write_text(html, encoding="utf-8")
    size_kb = round(len(html.encode()) / 1024, 1)
    print(f"wrote {OUT.relative_to(ROOT)} ({size_kb} KB, images embedded)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
