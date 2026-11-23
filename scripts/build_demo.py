"""Build the GitHub Pages demo in docs/: the showcase bridge, the findings and both gate reports."""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from golive_gate.cli import main as golive  # noqa: E402

from bridge.core import DRIVERS, LABELS, analyze, data_checks, load_definitions  # noqa: E402
from bridge.data import build  # noqa: E402
from bridge.showcase import SHOWCASE  # noqa: E402

DOCS = ROOT / "docs"
SWEEP = "172 of 175"  # scripts/seed_sweep.py; CI fails if it drops below 95%
TRAPS = [
    ({"type": "unmapped_order_code"}, "A new order type, XFR, that nobody added to the channel map"),
    (
        {"type": "case_pack", "customer": "Retailer A", "prefix": "WIP", "pack": 12},
        "Wipers sold in cases of twelve, a unit with no conversion",
    ),
    ({"type": "unmatched_rebate"}, "A rebate memo keyed to RETAILER B INC instead of Retailer B"),
    ({"type": "missing_lines", "n": 60}, "An extract cut off in September while the ledger has the full month"),
    ({"type": "duplicate_lines"}, "An export that repeated a page of invoices"),
]


def money(x: float) -> str:
    sign = "-" if x < 0 else "+"
    x = abs(x)
    if x < 500:
        return "$0"
    return f"{sign}${x / 1e6:.2f}M" if x >= 1e6 else f"{sign}${x / 1e3:,.0f}K"


def bridge_rows(mgmt: dict, deep: dict) -> str:
    rows = []
    for d in (*DRIVERS, "ledger_items"):
        a, b = mgmt[d], deep[d]
        if abs(a) < 1000 and abs(b) < 1000:
            continue
        flag = ' class="diff"' if abs(a - b) >= 100_000 else ""
        rows.append(f"<tr{flag}><td>{LABELS[d]}</td><td>{money(a)}</td><td>{money(b)}</td></tr>")
    return "\n".join(rows)


def main() -> None:
    defs = load_definitions()
    ext = build(SHOWCASE)
    out = analyze(ext, defs)
    levels = {x["level"]: x for x in out["mix_levels"]}
    tie = out["tie_out"]["periods"]
    py, cy = tie["PY"], tie["CY"]

    trap_rows = []
    for trap, text in TRAPS:
        t = build({"seed": 11, "traps": [trap]})
        issues = data_checks(t, defs)
        res = analyze(t, defs)
        detail = (issues or res["issues"])[0]["detail"]
        trap_rows.append(f"<tr><td>{html.escape(text)}</td><td>Stopped</td><td>{html.escape(detail)}</td></tr>")

    # both gate reports
    for agent, folder in (("agent:tieout_agent", "gate"), ("agent:workbook_agent", "gate-workbook")):
        golive(["run", str(ROOT / "eval" / "golive.yml"), "--agent", agent, "--out", str(DOCS / folder)])
    g1 = json.loads((DOCS / "gate" / "results.json").read_text())
    g2 = json.loads((DOCS / "gate-workbook" / "results.json").read_text())

    def passed(g):
        r = g["summary"]["by_run"][0]
        return r["passed"], r["total"]

    p1, p2 = passed(g1), passed(g2)
    m, dp = out["management_totals"], out["totals"]
    recon = []
    for label, per in (("Prior quarter", py), ("Current quarter", cy)):
        recon.append(f"<tr><td>{label}: gross profit from invoice lines</td><td>{money(per['gp'])[1:]}</td><td></td></tr>")
        for it in per["ledger_items"]:
            recon.append(f"<tr><td>&nbsp;&nbsp;less {html.escape(it['name'])}</td><td>{money(-it['amount'])[1:]}</td><td></td></tr>")
        recon.append(
            f"<tr><td><strong>{label}: gross profit after named items</strong></td><td><strong>{money(per['gl_gp'] + per['diff_gp'])[1:]}</strong></td><td><strong>{money(per['gl_gp'])[1:]}</strong></td></tr>"
        )
    mix_rows = "\n".join(
        f"<tr><td>{html.escape(x['label'][0].upper() + x['label'][1:])}</td><td>{money(x['amount'])}</td></tr>" for x in out["mix_levels"]
    )
    page = TEMPLATE.format(
        rev_py=money(py["revenue"])[1:],
        rev_cy=money(cy["revenue"])[1:],
        gp_py=money(py["gl_gp"])[1:],
        gp_cy=money(cy["gl_gp"])[1:],
        recon="\n".join(recon),
        mix_rows=mix_rows,
        delta=money(out["delta_gp"]),
        lines=f"{len(ext.lines):,}",
        memos=len(ext.rebates),
        rows=bridge_rows(m, dp),
        m_price=money(m["price"]),
        m_mix=money(m["mix"]),
        d_price=money(dp["price"]),
        d_mix=money(dp["mix"]),
        tariff=money(dp["cost_tariff"]),
        line_mix=money(levels["line"]["amount"]),
        chan_mix=money(levels["channel"]["amount"]),
        recovered=f"{dp['price'] / -dp['cost_tariff']:.0%}",
        traps="\n".join(trap_rows),
        g1=f"{p1[0]} of {p1[1]}",
        d1=g1["decision"].upper(),
        d1c=g1["decision"],
        g2=f"{p2[0]} of {p2[1]}",
        sweep=SWEEP,
        d2=g2["decision"].upper(),
        d2c=g2["decision"],
    )
    (DOCS / "index.html").write_text(page)
    import subprocess
    pages = [str(DOCS / "index.html"), str(DOCS / "gate" / "index.html"), str(DOCS / "gate-workbook" / "index.html")]
    subprocess.run([sys.executable, str(ROOT / "scripts" / "demo_chrome.py"), *pages, "--repo", "margin-bridge-tieout"], check=True)
    print("wrote", DOCS / "index.html")


TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Margin bridge tie-out</title>
<style>
main{{padding-bottom:24px}}
p.lead{{color:var(--ink-2);font-size:18px;max-width:42em}}
table{{margin:16px 0}}
td:nth-child(n+2){{white-space:nowrap}}
tr.diff td{{font-weight:500;background:var(--tint-1)}}
.box{{border-left:2px solid var(--green);padding:4px 0 4px 18px;margin:32px 0;max-width:46em;font-size:17px}}
.muted{{color:var(--ink-2);font-size:15px;max-width:46em}}
code{{background:rgb(27 26 23/.05);padding:1px 5px;border-radius:4px}}
.wrap td:nth-child(3){{white-space:normal}}
.tbl{{overflow-x:auto}}
</style></head><body><main>
<h1>Margin bridge tie-out</h1>
<p class="lead">Rebuild a quarter's gross-profit bridge from ERP invoice lines, tie it to the ledger, and find the driver a favorable total hides. All data is made up: a parts maker with 6 product lines, 6 customers, {lines} invoice lines and {memos} rebate memos across two quarters.</p>

<div class="box"><strong>The quarter in one line.</strong> Revenue rose from {rev_py} to {rev_cy}, yet gross profit moved {delta} ({gp_py} to {gp_cy}). The product-line bridge says surcharges barely stuck (price {m_price} against a {tariff} tariff hit) and mix helped ({m_mix}). The item-level bridge says the opposite: surcharges recovered {recovered} of the {tariff} tariff hit ({d_price} price), and a {line_mix} gain from richer product mix hid a {chan_mix} drag from lower-margin installer (DIFM) business at the two largest retailers, which the product-line bridge booked as a price cut. The lever is the installer program's margin, not list price.</div>

<h2>1. Tie-out first</h2>
<p>Nothing is decomposed until the extract ties to the general ledger, each quarter: revenue within $1, and gross profit within $1 after named, sized items that post only at the ledger. Anything left unexplained stops the bridge.</p>
<div class="tbl"><table><tr><th></th><th>Extract</th><th>Ledger</th></tr>
{recon}</table></div>
<p class="muted">Rebates post as separate customer-level memos, so they are allocated to invoice lines by gross sales within each customer and month before any price is calculated. Order types map to channels, and units convert to eaches, from one definitions file finance owns.</p>

<h2>2. The bridge at two grains</h2>
<div class="tbl"><table><tr><th>Effect on gross profit</th><th>Product-line bridge</th><th>Item-level bridge (SKU x customer x channel)</th></tr>
{rows}
<tr><td><strong>Change in gross profit</strong></td><td><strong>{delta}</strong></td><td><strong>{delta}</strong></td></tr></table></div>
<p><strong>Mix, split so the parts add up.</strong> Each level is the mix it adds on top of the coarser one, so the four rows sum to the item-level mix.</p>
<div class="tbl"><table><tr><th>Mix level</th><th>Effect</th></tr>
{mix_rows}</table></div>
<p class="muted">Both bridges add up to the same total. Shaded rows read differently at the two grains: when installer business grows inside a product line, the product-line bridge books the lower program price as a price cut.</p>

<h2>3. What the driver finder flags</h2>
<div class="tbl"><table class="wrap"><tr><th>Finding</th><th>Amount</th><th>What it means</th></tr>
<tr><td>Channel mix masked</td><td>{chan_mix}</td><td>Installer (DIFM) share grew inside product lines at Retailers A and B, hidden under a favorable product mix of {line_mix}.</td></tr>
<tr><td>Price reattributed</td><td>{d_price}</td><td>Like-for-like price held up better than the product-line bridge shows ({m_price}): it books the installer shift inside its lines as a price cut. Surcharges held.</td></tr>
<tr><td>Tariff cost</td><td>{tariff}</td><td>All of it on China-origin parts; surcharges recovered {recovered}.</td></tr></table></div>

<h2>4. Bad extracts stop the bridge</h2>
<div class="tbl"><table class="wrap"><tr><th>Planted problem</th><th>Result</th><th>What the check says</th></tr>
{traps}</table></div>

<h2>5. Go-live gate</h2>
<p>25 planted scenarios (8 routine drivers, 8 hidden drivers, 6 bad extracts, 3 clean controls), scored with <a href="https://github.com/pg2342-hub/golive-gate">golive-gate</a>. The gate: 24 of 25 overall, every hidden driver, every bad extract stopped, no false alarms, and zero critical failures (publishing on bad data, missing a planted data problem, or a bridge that does not tie).</p>
<div class="tbl"><table><tr><th>Analysis</th><th>Cases passed</th><th>Gate</th><th>Report</th></tr>
<tr><td>Tie-out + item-level bridge + driver finder</td><td>{g1}</td><td><span class="badge {d1c}">{d1}</span></td><td><a href="gate/">every case and check</a></td></tr>
<tr><td>Product-line workbook (ties to the ledger and stops if it does not; product line only, so it cannot see customer, channel, or origin; no data checks)</td><td>{g2}</td><td><span class="badge {d2c}">{d2}</span></td><td><a href="gate-workbook/">every case and check</a></td></tr></table></div>
<p class="muted">The workbook's misses are mostly structural: a product-line view cannot name a customer or a channel, and without data checks it cannot name a bad extract. The cases were written on fixed data seeds; on seven seeds they were not written with, the tie-out passes {sweep} cases. CI runs the tests, this gate, and that sweep on every push. Code: <a href="https://github.com/pg2342-hub/margin-bridge-tieout">github.com/pg2342-hub/margin-bridge-tieout</a>. Run it yourself: <code>pip install -e . &amp;&amp; golive run eval/golive.yml</code></p>
</main></body></html>
"""

if __name__ == "__main__":
    main()
