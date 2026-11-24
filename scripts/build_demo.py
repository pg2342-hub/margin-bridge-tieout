"""Build the GitHub Pages demo in docs/: the showcase bridge, the findings and both gate reports.

The page reads like a finance workpaper: the verdict first, the gross-profit bridge as a waterfall
drawn to scale, the tie-out as a ledger, then the driver finder, the data checks and the gate.
"""

from __future__ import annotations

import html
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from golive_gate.cli import main as golive  # noqa: E402

from bridge.core import DRIVERS, LABELS, analyze, data_checks, load_definitions  # noqa: E402
from bridge.data import build  # noqa: E402
from bridge.showcase import SHOWCASE  # noqa: E402

DOCS = ROOT / "docs"
REPO = "https://github.com/pg2342-hub/margin-bridge-tieout"
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


def level(x: float) -> str:
    """A balance, not a change: no sign."""
    return money(x)[1:]


def exact(x: float) -> str:
    """A tie-out difference, to the dollar."""
    return ("-" if x < -0.5 else "") + f"${abs(x):,.0f}"


def tone(x: float) -> str:
    return "up" if x > 0 else "down"


# ---------------------------------------------------------------- the bridge chart

ODD, DIFF, BRK = ' class="odd"', ' class="diff"', '<span class="chip brk">Break</span>'
ROW = 52  # px per bridge row; the SVG keeps this height and stretches only across
BAR = 20


def waterfall(key: str, label: str, start: tuple, steps: list, end: tuple, lo: float, hi: float, ticks: list) -> str:
    """One gross-profit bridge as a horizontal waterfall. Labels and values are HTML cells on fixed-height
    rows; the bars are one inline SVG on a shared scale (viewBox 0..1000 across, px down)."""
    span = hi - lo

    def x(v: float) -> float:
        return (v - lo) / span * 1000

    rows = [("total", *start)] + [("step", *s) for s in steps] + [("total", *end)]
    n = len(rows)
    h = n * ROW
    shapes = []
    for t in ticks:
        shapes.append(f'<line class="grid" x1="{x(t):.2f}" x2="{x(t):.2f}" y1="0" y2="{h}"/>')
    run = start[3]
    cells = []
    for i, (kind, name, sub, flag, amt) in enumerate(rows):
        y = i * ROW + (ROW - BAR) / 2
        if kind == "total":
            w = x(amt)
            shapes.append(f'<rect class="tot" x="0" y="{y}" width="{w:.2f}" height="{BAR}"/>')
            shapes.append(f'<rect class="brk" x="14" y="{y - 2}" width="6" height="{BAR + 4}"/>')
            right = amt
            val = level(amt)
        else:
            a, b = sorted((run, run + amt))
            w = max(x(b) - x(a), 0.5)
            cls = "inc" if amt > 0 else "dec"
            shapes.append(f'<rect class="{cls}" x="{x(a):.2f}" y="{y}" width="{w:.2f}" height="{BAR}"/>')
            if w < 8:  # too thin to see once the chart is narrow: mark its place with a hairline
                shapes.append(f'<line class="tick {cls}" x1="{x(b):.2f}" x2="{x(b):.2f}" y1="{y - 3}" y2="{y + BAR + 3}"/>')
            run += amt
            right = run
            val = money(amt)
        if i < n - 1:
            shapes.append(
                f'<line class="link" x1="{x(right):.2f}" x2="{x(right):.2f}" y1="{y + BAR}" y2="{(i + 1) * ROW + (ROW - BAR) / 2}"/>'
            )
        r = i + 2  # grid row: 1 is the axis
        mark = " key" if flag else ""
        cells.append(f'<div class="band{mark}" style="grid-row:{r}"></div>')
        cells.append(
            f'<div class="lbl{" t" if kind == "total" else ""}" style="grid-row:{r}"><b>{html.escape(name)}</b>'
            + (f"<span>{html.escape(sub)}</span>" if sub else "")
            + "</div>"
        )
        cls = "tot" if kind == "total" else tone(amt)
        cells.append(f'<div class="val {cls}" style="grid-row:{r}">{val}</div>')
    assert abs(run - end[3]) < 1, "bridge does not reach the current quarter"
    axis = "".join(
        f'<span{ODD if k % 2 else ""} style="left:{x(t) / 10:.2f}%">${t / 1e6:.1f}M</span>' for k, t in enumerate(ticks)
    )
    svg = (
        f'<svg class="bars" style="grid-row:2/span {n};height:{h}px" viewBox="0 0 1000 {h}" preserveAspectRatio="none" '
        f'role="img" aria-label="{html.escape(label)}">' + "".join(shapes) + "</svg>"
    )
    return (
        f'<div class="wf" id="wf-{key}" style="grid-template-rows:28px repeat({n},{ROW}px)">'
        f'<div class="axis" aria-hidden="true">{axis}</div>{"".join(cells)}{svg}</div>'
    )


def scale(*paths: list) -> tuple:
    vals = [v for p in paths for v in p]
    lo = math.floor((min(vals) - 100_000) / 250_000) * 250_000
    hi = math.ceil((max(vals) + 100_000) / 250_000) * 250_000
    ticks = [t for t in range(math.ceil(lo / 500_000) * 500_000, int(hi) + 1, 500_000) if lo < t < hi]
    return lo, hi, ticks


def running(start: float, steps: list) -> list:
    out, run = [start], start
    for s in steps:
        run += s[3]
        out.append(run)
    return out


# ---------------------------------------------------------------- page


def main() -> None:
    defs = load_definitions()
    ext = build(SHOWCASE)
    out = analyze(ext, defs)
    levels = {x["level"]: x for x in out["mix_levels"]}
    tie = out["tie_out"]["periods"]
    py, cy = tie["PY"], tie["CY"]

    trap_rows, cutoff = [], None
    for trap, text in TRAPS:
        t = build({"seed": 11, "traps": [trap]})
        issues = data_checks(t, defs)
        res = analyze(t, defs)
        detail = (issues or res["issues"])[0]["detail"]
        if trap["type"] == "missing_lines":
            cutoff = res["tie_out"]["periods"]["CY"]["diff_gp"]
        trap_rows.append(
            f'<tr class="break"><td>{html.escape(text)}</td><td class="say">{html.escape(detail)}</td>'
            f'<td class="st"><span class="chip brk">Stopped</span></td></tr>'
        )

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
    delta = money(out["delta_gp"])
    chan, line = levels["channel"]["amount"], levels["line"]["amount"]
    recovered = f"{dp['price'] / -dp['cost_tariff']:.0%}"
    tariff = money(dp["cost_tariff"])

    # -- tie-out ledger
    ties = py["ok"] and cy["ok"]
    ok_chip = '<span class="chip ok">Ties</span>'
    led = []
    for label, per in (("Prior quarter", py), ("Current quarter", cy)):
        d_rev = per["revenue"] - per["gl_revenue"]
        led.append(f'<tr class="grp"><th colspan="5" scope="rowgroup">{label}</th></tr>')
        led.append(
            f'<tr class="tieline"><td>Revenue</td><td class="num">{level(per["revenue"])}</td><td class="num">{level(per["gl_revenue"])}</td>'
            f'<td class="num">{exact(d_rev)}</td><td class="st">{ok_chip if abs(d_rev) <= defs["tie_out_tolerance"] else BRK}</td></tr>'
        )
        led.append(f'<tr><td>Gross profit from invoice lines</td><td class="num">{level(per["gp"])}</td><td></td><td></td><td></td></tr>')
        for it in per["ledger_items"]:
            led.append(
                f'<tr class="less"><td>less {html.escape(it["name"])}</td><td class="num">({level(-it["amount"])})</td><td></td><td></td><td></td></tr>'
            )
        led.append(
            f'<tr class="tieline"><td>Gross profit after named items</td><td class="num">{level(per["gl_gp"] + per["diff_gp"])}</td>'
            f'<td class="num">{level(per["gl_gp"])}</td><td class="num">{exact(per["diff_gp"])}</td>'
            f'<td class="st">{ok_chip if per["ok"] else BRK}</td></tr>'
        )
    led.append('<tr class="grp"><th colspan="5" scope="rowgroup">The same check on a planted cut-off extract (separate test data)</th></tr>')
    led.append(
        f'<tr class="tieline break"><td>Current quarter gross profit after named items</td><td></td><td></td>'
        f'<td class="num">{exact(cutoff)}</td><td class="st"><span class="chip brk">Break</span></td></tr>'
    )

    # -- the two bridges
    item_steps = [
        ("Price", "Net of rebates, incl. tariff surcharges", False, dp["price"]),
        ("Tariff cost", "", False, dp["cost_tariff"]),
        ("Material and other cost", "", False, dp["cost_other"]),
        ("Volume", "", False, dp["volume"]),
        ("Product mix", "", False, line),
        ("Channel mix", "Within product lines", True, chan),
        ("Customer mix", "Within product line and channel", False, levels["customer"]["amount"]),
        ("SKU mix", "Within the rest", False, levels["sku"]["amount"]),
        ("Ledger-only items", "Variances, reserves, freight", False, dp["ledger_items"]),
    ]
    item_steps = [s for s in item_steps if abs(s[3]) >= 500]
    mgmt_steps = [
        ("Price", "Net of rebates, incl. tariff surcharges", True, m["price"]),
        ("Tariff cost", "", False, m["cost_tariff"]),
        ("Material and other cost", "", False, m["cost_other"]),
        ("Volume", "", False, m["volume"]),
        ("Mix", "", True, m["mix"]),
        ("Ledger-only items", "Variances, reserves, freight", False, m["ledger_items"]),
    ]
    mgmt_steps = [s for s in mgmt_steps if abs(s[3]) >= 500]
    start = ("Prior quarter", "Gross profit", False, py["gl_gp"])
    end = ("Current quarter", "Gross profit", False, cy["gl_gp"])
    lo, hi, ticks = scale(running(py["gl_gp"], item_steps), running(py["gl_gp"], mgmt_steps))
    wf_item = waterfall("item", f"Item-level bridge: gross profit {level(py['gl_gp'])} to {level(cy['gl_gp'])}", start, item_steps, end, lo, hi, ticks)
    wf_mgmt = waterfall("mgmt", f"Product-line bridge: gross profit {level(py['gl_gp'])} to {level(cy['gl_gp'])}", start, mgmt_steps, end, lo, hi, ticks)

    grain_rows = []
    for d in (*DRIVERS, "ledger_items"):
        a, b = m[d], dp[d]
        if abs(a) < 1000 and abs(b) < 1000:
            continue
        differs = abs(a - b) >= 100_000
        grain_rows.append(
            f'<tr{DIFF if differs else ""}><td>{LABELS[d]}</td><td class="num">{money(a)}</td><td class="num">{money(b)}</td></tr>'
        )
    mix_rows = "\n".join(
        f'<tr{DIFF if x["level"] == "channel" else ""}><td>{html.escape(x["label"][0].upper() + x["label"][1:])}</td><td class="num">{money(x["amount"])}</td></tr>'
        for x in out["mix_levels"]
    )

    gate_rows = f"""<div class="grow">
  <div class="gwho"><b>Tie-out, item-level bridge and driver finder</b><span>What this page shows</span></div>
  <div class="gscore"><b>{p1[0]}</b><span>of {p1[1]} cases</span></div>
  <span class="badge {g1["decision"]}">{g1["decision"].upper()}</span>
  <a href="gate/">Every case and check</a>
</div>
<div class="grow">
  <div class="gwho"><b>Product-line workbook</b><span>Ties to the ledger and stops if it does not; product line only, so it cannot see customer, channel, or origin; no data checks</span></div>
  <div class="gscore"><b>{p2[0]}</b><span>of {p2[1]} cases</span></div>
  <span class="badge {g2["decision"]}">{g2["decision"].upper()}</span>
  <a href="gate-workbook/">Every case and check</a>
</div>"""

    status = "Ties to the ledger" if ties else "Does not tie"
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Margin bridge tie-out</title>
<meta name="description" content="A quarter's gross-profit bridge rebuilt from invoice lines and tied to the ledger: gross profit moved {delta}, and a {money(chan)} installer channel drag hid under a favorable product mix.">
<style>{CSS}</style></head><body><main>
<div class="head">
<h1>Margin bridge tie-out</h1>
<p class="lead">Rebuild a quarter's gross-profit bridge from ERP invoice lines, tie it to the ledger, and find the driver a favorable total hides.</p>
</div>

<section class="verdict" aria-label="Result">
  <div class="vtop">
    <span class="chip {"ok" if ties else "brk"} big">{status}</span>
    <p>Both quarters, revenue and gross profit, within $1 of the general ledger</p>
    <span class="vgate">Go-live gate <span class="badge {g1["decision"]}">{g1["decision"].upper()}</span> {p1[0]} of {p1[1]}</span>
  </div>
  <div class="vbody">
    <div class="vnum"><b>{delta}</b><span>Gross profit, {level(py["gl_gp"])} to {level(cy["gl_gp"])}, while revenue rose from {level(py["revenue"])} to {level(cy["revenue"])}</span></div>
    <div class="vsay">
      <p class="vline">The real driver is a {money(chan)} drag from lower-margin installer (DIFM) business at the two largest retailers, hidden under a {money(line)} gain from richer product mix.</p>
      <p>Surcharges recovered {recovered} of the {tariff} tariff hit ({money(dp["price"])} price). The lever is the installer program's margin, not list price.</p>
    </div>
  </div>
  <div class="vfoot"><b>The product-line bridge says the opposite:</b> surcharges barely stuck (price {money(m["price"])} against a {tariff} tariff hit) and mix helped ({money(m["mix"])}). It booked the installer shift as a price cut.</div>
</section>

<div class="layout">
<div class="content">

<h2 id="bridge">The bridge</h2>
<p class="note">Prior quarter gross profit to current quarter, one step per effect. Both grains end at the same {delta}; they disagree on why.</p>
<div class="chart">
  <div class="ctop">
    <div class="seg" role="radiogroup" aria-label="Bridge grain"><button type="button" role="radio" aria-checked="true" data-v="item">Item-level <span>SKU x customer x channel</span></button><button type="button" role="radio" aria-checked="false" data-v="mgmt">Product-line</button></div>
    <div class="legend" aria-hidden="true"><span><i class="inc"></i>Raises gross profit</span><span><i class="dec"></i>Lowers it</span><span><i class="tot"></i>Quarter total</span></div>
  </div>
  {wf_item}
  {wf_mgmt.replace('class="wf"', 'class="wf" hidden', 1)}
  <p class="cnote" data-for="item">Item-level mix is split into four nested levels, each the mix it adds on top of the coarser one. Channel mix is the driver.</p>
  <p class="cnote" data-for="mgmt" hidden>The product-line bridge has one mix line and books the installer shift inside its lines as a lower price.</p>
  <p class="scale">Scale starts at ${lo / 1e6:.2f}M, not zero; the break in each total bar marks it. Every step is drawn to the same scale.</p>
</div>

<div class="pair">
<div>
<h3>Both grains, line by line</h3>
<div class="scroll"><table><thead><tr><th>Effect on gross profit</th><th class="num">Product line</th><th class="num">Item level</th></tr></thead><tbody>
{chr(10).join(grain_rows)}
<tr class="sum"><td>Change in gross profit</td><td class="num">{delta}</td><td class="num">{delta}</td></tr></tbody></table></div>
<p class="note">Marked rows read differently at the two grains: when installer business grows inside a product line, the product-line bridge books the lower program price as a price cut.</p>
</div>
<div>
<h3>Mix, split so the parts add up</h3>
<div class="scroll"><table><thead><tr><th>Mix level</th><th class="num">Effect</th></tr></thead><tbody>
{mix_rows}
<tr class="sum"><td>Item-level mix</td><td class="num">{money(dp["mix"])}</td></tr></tbody></table></div>
<p class="note">Each level is the mix it adds on top of the coarser one, so the four rows sum to the item-level mix.</p>
</div>
</div>

<h2 id="tie-out">Tie-out</h2>
<p class="note">Nothing is decomposed until the extract ties to the general ledger, each quarter: revenue within $1, and gross profit within $1 after named, sized items that post only at the ledger. Anything left unexplained stops the bridge.</p>
<div class="scroll"><table class="ledger"><thead><tr><th></th><th class="num">Extract</th><th class="num">Ledger</th><th class="num">Difference</th><th class="st">Status</th></tr></thead><tbody>
{chr(10).join(led)}
</tbody></table></div>
<p class="note">Rebates post as separate customer-level memos, so they are allocated to invoice lines by gross sales within each customer and month before any price is calculated. Order types map to channels, and units convert to eaches, from one definitions file finance owns.</p>

<h2 id="drivers">What the driver finder flags</h2>
<div class="finds">
  <div class="find key"><b class="{tone(chan)}">{money(chan)}</b><h3>Channel mix masked</h3><p>Installer (DIFM) share grew inside product lines at Retailers A and B, hidden under a favorable product mix of {money(line)}.</p></div>
  <div class="find"><b class="{tone(dp["price"])}">{money(dp["price"])}</b><h3>Price reattributed</h3><p>Like-for-like price held up better than the product-line bridge shows ({money(m["price"])}): it books the installer shift inside its lines as a price cut. Surcharges held.</p></div>
  <div class="find"><b class="{tone(dp["cost_tariff"])}">{tariff}</b><h3>Tariff cost</h3><p>All of it on China-origin parts; surcharges recovered {recovered}.</p></div>
</div>

<h2 id="checks">Bad extracts stop the bridge</h2>
<p class="note">Five planted problems, each on its own test extract. Every one stops the bridge before a number is published.</p>
<div class="scroll"><table class="ledger traps"><thead><tr><th>Planted problem</th><th>What the check says</th><th class="st">Result</th></tr></thead><tbody>
{chr(10).join(trap_rows)}
</tbody></table></div>

<h2 id="gate">Go-live gate</h2>
<p class="note">25 planted scenarios (8 routine drivers, 8 hidden drivers, 6 bad extracts, 3 clean controls), scored with <a href="https://github.com/pg2342-hub/golive-gate">golive-gate</a>. The gate: 24 of 25 overall, every hidden driver, every bad extract stopped, no false alarms, and zero critical failures (publishing on bad data, missing a planted data problem, or a bridge that does not tie).</p>
<div class="gates">
{gate_rows}
</div>
<p class="note">The workbook's misses are mostly structural: a product-line view cannot name a customer or a channel, and without data checks it cannot name a bad extract. The cases were written on fixed data seeds; on seven seeds they were not written with, the tie-out passes {SWEEP} cases. CI runs the tests, this gate, and that sweep on every push.</p>
</div>

<aside class="side" aria-label="About this build">
  <nav aria-label="On this page"><a href="#bridge">The bridge</a><a href="#tie-out">Tie-out</a><a href="#drivers">Driver finder</a><a href="#checks">Bad extracts</a><a href="#gate">Go-live gate</a></nav>
  <div><h3>Data</h3><p>All data is made up: a parts maker with 6 product lines, 6 customers, {len(ext.lines):,} invoice lines and {len(ext.rebates)} rebate memos across two quarters. Customers, SKUs, prices, tariffs and the ledger are synthetic.</p></div>
  <div><h3>Run it yourself</h3><p>Python 3.9+.</p><pre>pip install -e .
golive run eval/golive.yml
golive run eval/golive.yml \\
  --agent agent:workbook_agent
python scripts/seed_sweep.py</pre></div>
  <div><a class="pill" href="{REPO}">Code on GitHub</a></div>
</aside>
</div>
</main>
<script>{JS}</script></body></html>
"""
    (DOCS / "index.html").write_text(page)
    import subprocess

    pages = [str(DOCS / "index.html"), str(DOCS / "gate" / "index.html"), str(DOCS / "gate-workbook" / "index.html")]
    subprocess.run([sys.executable, str(ROOT / "scripts" / "demo_chrome.py"), *pages, "--repo", "margin-bridge-tieout"], check=True)
    print("wrote", DOCS / "index.html")


CSS = """
.head h1{margin:40px 0 14px}
.head .lead{max-width:38em}
.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.note{color:var(--ink-2);font-size:15px;max-width:44em;margin-top:14px}
h2+.note{margin-top:0}
.up{color:var(--green)}.down{color:var(--ink)}
/* status chips: a tie is the evergreen moment, a break is ink */
.chip{display:inline-flex;align-items:center;gap:6px;min-height:24px;padding:0 10px;border-radius:999px;font:500 12px/1 var(--mono);letter-spacing:.04em;white-space:nowrap;border:1px solid transparent}
.chip.ok{background:var(--green-wash);color:var(--green)}
.chip.ok::before{content:"";width:8px;height:4px;border-left:1.5px solid currentColor;border-bottom:1.5px solid currentColor;transform:translateY(-2px) rotate(-45deg)}
.chip.brk{background:var(--ink);color:var(--paper)}
.chip.brk::before{content:"";width:7px;height:7px;border-radius:2px;background:var(--paper);transform:rotate(45deg)}
.chip.big{min-height:32px;padding:0 14px;font-size:13px}
/* verdict */
.verdict{margin:36px 0 0;border:1px solid var(--rule);border-radius:16px;background:#fbfaf6;overflow:hidden}
.vtop{display:flex;flex-wrap:wrap;align-items:center;gap:10px 16px;padding:16px 24px;border-bottom:1px solid var(--rule)}
.vtop p{margin:0;color:var(--ink-2);font-size:15px;flex:1 1 18em}
.vgate{display:inline-flex;align-items:center;gap:10px;font-size:14px;color:var(--ink-2);font-variant-numeric:tabular-nums}
.vbody{display:grid;grid-template-columns:minmax(0,17em) minmax(0,1fr);gap:28px 40px;padding:28px 24px;align-items:start}
.vnum b{display:block;font:400 64px/1 var(--serif);letter-spacing:-.01em;font-variant-numeric:tabular-nums}
.vnum span{display:block;margin-top:10px;color:var(--ink-2);font-size:14px;line-height:1.45;max-width:17em}
.vline{font:400 25px/1.3 var(--serif);margin:0 0 12px;text-wrap:pretty}
.vsay p:last-child{color:var(--ink-2);margin:0;max-width:40em}
.vfoot{padding:14px 24px;border-top:1px solid var(--rule);font-size:15px;color:var(--ink-2)}
.vfoot b{color:var(--ink)}
/* page body: content and a side column */
.layout{display:grid;grid-template-columns:minmax(0,1fr) 270px;gap:56px;align-items:start;margin-top:8px}
.side{position:sticky;top:24px;margin-top:64px;display:grid;gap:22px;font-size:14px;color:var(--ink-2)}
.side h3{margin:0 0 6px;font:500 13px/1.3 var(--sans);color:var(--ink)}
.side p{margin:0}
.side nav a{display:block;padding:5px 0;color:var(--ink-2);text-decoration:none;border-bottom:1px solid var(--rule-soft)}
.side nav a:hover{color:var(--ink)}
.side pre{font-size:12px;margin:6px 0 0}
section[id],h2[id]{scroll-margin-top:24px}
/* the bridge: a horizontal waterfall */
.chart{border:1px solid var(--rule);border-radius:16px;background:#fbfaf6;padding:18px 24px 16px}
.ctop{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:12px 20px;margin-bottom:10px}
.seg{display:flex;width:fit-content;max-width:100%;flex-wrap:wrap;gap:2px;padding:3px;border:1px solid var(--rule);border-radius:999px;background:var(--paper)}
.seg button{min-height:34px;padding:0 14px;border:0;border-radius:999px;background:transparent;color:var(--ink-2);font:500 14px/1 var(--sans);cursor:pointer}
.seg button span{font-weight:400;opacity:.75;margin-left:4px}
.seg button[aria-checked=true]{background:var(--ink);color:var(--paper)}
.legend{display:flex;flex-wrap:wrap;gap:4px 16px;color:var(--ink-2);font-size:13px}
.legend span{display:inline-flex;align-items:center;gap:7px}
.legend i{width:14px;height:10px;border-radius:2px}
.legend .inc{background:var(--green)}.legend .dec{background:var(--paper);box-shadow:inset 0 0 0 1.5px var(--ink)}.legend .tot{background:#a8a496}
.wf{display:grid;grid-template-columns:minmax(0,13em) minmax(0,1fr) 5.5em;column-gap:16px;position:relative}
.wf[hidden]{display:none}
.axis{grid-column:2;grid-row:1;position:relative;font:400 12px/28px var(--mono);color:var(--ink-2);font-variant-numeric:tabular-nums}
.axis span{position:absolute;top:0;transform:translateX(-50%);white-space:nowrap}
.band{grid-column:1/-1;margin:0 -12px;border-radius:8px;border-top:1px solid var(--rule-soft)}
.band.key{background:var(--green-wash);border-top-color:transparent}
.band.key+.lbl b{color:var(--green)}
.lbl,.val{position:relative;align-self:center;line-height:1.25}
.lbl{grid-column:1;font-size:14px}
.lbl b{display:block;font-weight:500}
.lbl span{display:block;color:var(--ink-2);font-size:12.5px}
.lbl.t b{font-weight:600}
.val{grid-column:3;text-align:right;font:500 14px/1.2 var(--sans);font-variant-numeric:tabular-nums;white-space:nowrap}
.val.tot{font-weight:600}
.bars{grid-column:2;width:100%;display:block;position:relative;overflow:visible}
.bars .grid{stroke:var(--rule);stroke-width:1;vector-effect:non-scaling-stroke}
.bars .tot{fill:#a8a496}
.bars .brk{fill:#fbfaf6}
.band.key~.bars .brk{fill:#fbfaf6}
.bars .inc{fill:var(--green)}
.bars rect.dec{fill:var(--paper);stroke:var(--ink);stroke-width:1.5;vector-effect:non-scaling-stroke}
.bars .tick{stroke-width:2;vector-effect:non-scaling-stroke}
.bars .tick.inc{stroke:var(--green)}.bars .tick.dec{stroke:var(--ink)}
.bars .link{stroke:var(--ink-2);stroke-width:1;stroke-dasharray:2 3;vector-effect:non-scaling-stroke}
.cnote{margin:12px 0 0;font-size:15px}
.scale{margin:6px 0 0;font-size:13px;color:var(--ink-2)}
.pair{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(0,1fr);gap:32px;margin-top:8px}
.pair h3{margin:32px 0 6px}
tr.diff td{background:var(--tint-1)}
tr.diff td:first-child{box-shadow:inset 3px 0 0 var(--green);padding-left:10px}
tr.sum td{font-weight:600;border-top:1px solid var(--ink);border-bottom:0}
/* ledgers */
.ledger td,.ledger th{padding-left:0}
.ledger td+td,.ledger th+th{padding-left:16px}
.ledger tr.grp th{font:400 18px/1.3 var(--serif);color:var(--ink);letter-spacing:0;border-bottom:1px solid var(--rule);padding-top:22px;white-space:normal}
.ledger tr.less td:first-child{padding-left:18px;color:var(--ink-2)}
.ledger tr.less td{color:var(--ink-2)}
.ledger tr.tieline td{font-weight:500}
.ledger tr.tieline td.num:nth-child(2),.ledger tr.tieline td.num:nth-child(3){border-top:1px solid var(--ink)}
.ledger .st{text-align:right;width:1%;white-space:nowrap}
.ledger tr.break td{background:rgb(27 26 23/.045)}
.ledger tr.break td:first-child{box-shadow:inset 3px 0 0 var(--ink);padding-left:12px}
.traps .say{font-family:var(--mono);font-size:13px;color:var(--ink-2)}
/* driver finder */
.finds{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}
.find{border:1px solid var(--rule);border-radius:16px;background:#fbfaf6;padding:20px 22px}
.find.key{border-color:var(--green);box-shadow:inset 0 0 0 1px var(--green)}
.find b{display:block;font:400 36px/1 var(--serif);font-variant-numeric:tabular-nums}
.find h3{margin:12px 0 6px;font:500 16px/1.3 var(--sans)}
.find p{margin:0;font-size:15px;color:var(--ink-2)}
/* gate */
.gates{border:1px solid var(--rule);border-radius:16px;background:#fbfaf6;overflow:hidden}
.grow{display:grid;grid-template-columns:minmax(0,1fr) 7em 5.5em 10em;align-items:center;gap:16px 24px;padding:20px 24px}
.grow+.grow{border-top:1px solid var(--rule-soft)}
.gwho b{display:block;font:400 20px/1.25 var(--serif)}
.gwho span{display:block;color:var(--ink-2);font-size:14px;line-height:1.4;margin-top:4px}
.gscore b{font:400 40px/1 var(--serif)}
.gscore span{display:block;color:var(--ink-2);font-size:13px;margin-top:4px}
.grow .badge{justify-self:start}
.grow a{font-size:14px;justify-self:end}
@media (max-width:1000px){
 .layout{grid-template-columns:minmax(0,1fr);gap:0}
 .side{position:static;margin-top:48px}
 .pair{grid-template-columns:minmax(0,1fr);gap:0}
 .finds{grid-template-columns:minmax(0,1fr)}
}
@media (max-width:760px){
 .vbody{grid-template-columns:minmax(0,1fr);gap:18px}
 .vnum b{font-size:52px}
 .vline{font-size:21px}
 .grow{grid-template-columns:minmax(0,1fr) auto;gap:12px 16px}
 .gwho{grid-column:1/-1}
 .grow a{grid-column:1/-1;justify-self:start}
}
@media (max-width:640px){
 .vtop,.vbody,.vfoot{padding-left:18px;padding-right:18px}
 .chart{padding:16px 14px 14px}
 .wf{grid-template-columns:minmax(0,8.5em) minmax(0,1fr) 4.4em;column-gap:10px}
 .band{margin:0 -8px}
 .lbl{font-size:13px}.lbl span{font-size:11.5px}
 .val{font-size:13px}
 .axis span.odd{display:none}
 .seg button span{display:none}
 .grow{padding:18px}
 /* ledgers stack: the line on top, its figures in a row beneath */
 .ledger,.ledger tbody,.ledger thead{display:block}
 .ledger tr{display:grid;grid-template-columns:repeat(3,minmax(0,1fr)) 30px;column-gap:10px;align-items:center;border-bottom:1px solid var(--rule)}
 .ledger td,.ledger th,.ledger td+td,.ledger th+th{border:0;padding:0}
 .ledger thead tr{border-bottom:1px solid var(--ink);padding:8px 0}
 .ledger thead th:first-child{display:none}
 .ledger td:first-child{grid-column:1/-1;padding:10px 0 2px}
 .ledger tr>td:not(:first-child){padding-bottom:10px}
 .ledger tr.grp th{grid-column:1/-1;padding:18px 0 8px}
 .ledger tr.less td:first-child{padding-left:14px}
 .ledger tr.break{background:rgb(27 26 23/.045);box-shadow:inset 3px 0 0 var(--ink);padding:0 10px 0 14px}
 .ledger tr.break td,.ledger tr.break td:first-child{background:none;box-shadow:none;padding-left:0}
 .ledger:not(.traps) .chip{font-size:0;gap:0;min-height:22px;padding:0 7px}
 .ledger:not(.traps) th.st{font-size:0}
 .ledger .st{width:auto}
 .ledger tr.tieline td.num:nth-child(2),.ledger tr.tieline td.num:nth-child(3){border-top:0}
 .traps tr{grid-template-columns:minmax(0,1fr) auto}
 .traps thead th:first-child{display:block}
 .traps thead th:nth-child(2){display:none}
 .traps td.say{padding-bottom:10px}
 .pair th{white-space:normal}
 .pair td,.pair th{padding-right:8px}
 .pair td:last-child,.pair th:last-child{padding-right:0}
}
"""

JS = """
const seg=[...document.querySelectorAll('.seg button')];
seg.forEach(b=>b.addEventListener('click',()=>{
 seg.forEach(x=>x.setAttribute('aria-checked',String(x===b)));
 const v=b.dataset.v;
 document.querySelectorAll('.wf').forEach(w=>w.hidden=w.id!=='wf-'+v);
 document.querySelectorAll('.cnote').forEach(p=>p.hidden=p.dataset.for!==v);
}));
"""

if __name__ == "__main__":
    main()
