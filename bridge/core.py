"""Margin bridge: check the extract, tie it to the ledger, decompose the change, find the drivers.

Order matters. Nothing is decomposed until the data checks pass and the extract ties to
the general ledger, because a bridge that does not tie is a story, not an analysis.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import yaml

DEFS_PATH = Path(__file__).with_name("definitions.yml")
DIMENSIONS = ("line", "customer", "channel", "origin")
DRIVERS = ("price", "cost_tariff", "cost_other", "volume", "mix", "new", "lost")
LABELS = {
    "price": "Price (net of rebates, incl. tariff surcharges)",
    "cost_tariff": "Tariff cost",
    "cost_other": "Material and other cost",
    "volume": "Volume",
    "mix": "Mix",
    "new": "New items",
    "lost": "Lost items",
    "ledger_items": "Ledger-only items (variances, reserves, freight)",
}
MIX_LEVELS = (  # nested mix: each level is the mix it adds on top of the coarser one
    ("line", "product mix", lambda a: (a["line"],)),
    ("channel", "channel mix within product lines", lambda a: (a["line"], a["channel"])),
    ("customer", "customer mix within product line and channel", lambda a: (a["line"], a["channel"], a["customer"])),
    ("sku", "SKU mix within the rest", lambda a: (a["line"], a["channel"], a["customer"], a["sku"])),
)


def load_definitions(path: Path | str = DEFS_PATH) -> dict:
    return yaml.safe_load(Path(path).read_text())


# ---------------------------------------------------------------- checks


def data_checks(ext, defs: dict) -> list[dict]:
    """Problems that make any bridge built on this extract wrong. Every one blocks publishing."""
    issues = []
    bad_codes = defaultdict(lambda: [0, 0.0])
    for r in ext.lines:
        if r["order_type"] not in defs["channel_map"]:
            bad_codes[r["order_type"]][0] += 1
            bad_codes[r["order_type"]][1] += r["gross"]
    for code, (n, amt) in bad_codes.items():
        issues.append(
            {"code": "unmapped_order_code", "detail": f"order type {code} on {n} lines (${amt:,.0f}) has no channel", "blocking": True}
        )

    bad_uom = defaultdict(lambda: [0, 0.0])
    for r in ext.lines:
        if r["uom"] not in defs["uom_to_each"]:
            bad_uom[r["uom"]][0] += 1
            bad_uom[r["uom"]][1] += r["gross"]
    for uom, (n, amt) in bad_uom.items():
        issues.append(
            {
                "code": "unknown_uom",
                "detail": f"unit of measure {uom} on {n} lines (${amt:,.0f}) has no conversion to eaches",
                "blocking": True,
            }
        )

    known = set(defs["customers"])
    for m in ext.rebates:
        if m["customer"] not in known:
            issues.append(
                {
                    "code": "unmatched_rebate",
                    "detail": f"rebate memo {m['memo']} (${m['amount']:,.0f}) names {m['customer']}, not in the customer master",
                    "blocking": True,
                }
            )

    seen = defaultdict(int)
    for r in ext.lines:
        seen[(r["invoice"], r["sku"], r["customer"])] += 1
    dups = [k for k, n in seen.items() if n > 1]
    if dups:
        issues.append({"code": "duplicate_lines", "detail": f"{len(dups)} invoice lines appear more than once", "blocking": True})
    return issues


def tie_out(ext, defs: dict) -> dict:
    """Extract against the ledger, each period. Revenue must tie within tolerance. Gross profit must
    tie within tolerance after the named ledger-only items (COGS entries that never touch an invoice
    line, such as variances, reserves and freight); anything left over is unexplained and blocks."""
    tol = defs["tie_out_tolerance"]
    out = {"ok": True, "periods": {}}
    for period in ("PY", "CY"):
        rows = [r for r in ext.lines if r["period"] == period]
        rev = sum(r["gross"] for r in rows) - sum(m["amount"] for m in ext.rebates if m["period"] == period)
        cogs = sum(r["cost_material"] + r["cost_tariff"] + r["cost_other"] for r in rows)
        named = [i for i in ext.ledger_items if i["period"] == period]
        led = sum(i["amount"] for i in named)
        gl = ext.gl[period]
        gl_gp = gl["revenue"] - gl["cogs"]
        d_rev = rev - gl["revenue"]
        d_gp = (rev - cogs - led) - gl_gp
        ok = abs(d_rev) <= tol and abs(d_gp) <= tol
        out["periods"][period] = {
            "revenue": round(rev, 2),
            "gl_revenue": gl["revenue"],
            "gp": round(rev - cogs, 2),
            "ledger_items": [{"name": i["name"], "amount": round(-i["amount"], 2)} for i in named],
            "gl_gp": round(gl_gp, 2),
            "diff_gp": round(d_gp, 2),
            "ok": ok,
        }
        out["ok"] &= ok
    return out


# ---------------------------------------------------------------- normalise


def normalise(ext, defs: dict) -> dict:
    """Quarterly items keyed by (sku, customer, channel) with eaches, net revenue after
    allocated rebates, and cost split into tariff and other."""
    items = {"PY": {}, "CY": {}}
    gross_cm = defaultdict(float)
    for r in ext.lines:
        gross_cm[(r["period"], r["customer"], r["month"])] += r["gross"]
    reb_cm = defaultdict(float)
    for m in ext.rebates:
        reb_cm[(m["period"], m["customer"], m["month"])] += m["amount"]
    for r in ext.lines:
        ch = defs["channel_map"][r["order_type"]]
        key = (r["sku"], r["customer"], ch)
        it = items[r["period"]].setdefault(key, {"qty": 0.0, "rev": 0.0, "tariff": 0.0, "other": 0.0})
        g = gross_cm[(r["period"], r["customer"], r["month"])]
        alloc = reb_cm[(r["period"], r["customer"], r["month"])] * r["gross"] / g if g else 0.0
        it["qty"] += r["qty"] * defs["uom_to_each"][r["uom"]]
        it["rev"] += r["gross"] - alloc
        it["tariff"] += r["cost_tariff"]
        it["other"] += r["cost_material"] + r["cost_other"]
    return items


def attributes(ext, key) -> dict:
    s = ext.skus[key[0]]
    return {"sku": s.sku, "line": s.line, "origin": s.origin, "customer": key[1], "channel": key[2]}


# ---------------------------------------------------------------- bridge


def bridge(items: dict, grain) -> dict:
    """Price / cost / volume / mix bridge at a grain (a function from item key to a group key).

    For groups sold in both periods, with GPU = gross profit per each:
      price       = Q1 x (P1 - P0)
      cost        = -Q1 x (C1 - C0), split into tariff and other
      volume      = Q0 x (growth of all continuing units) x GPU0        (each group grows at the total rate)
      mix         = (Q1 - Q0 x total growth) x GPU0                     (share gained or lost, at its own margin)
    New groups bring their whole CY gross profit, lost groups lose their whole PY gross profit.
    The effects add up to the change in gross profit exactly, by construction.
    """
    g = {p: defaultdict(lambda: {"qty": 0.0, "rev": 0.0, "tariff": 0.0, "other": 0.0}) for p in items}
    for p in items:
        for k, it in items[p].items():
            acc = g[p][grain(k)]
            for f in acc:
                acc[f] += it[f]
    common = [k for k in g["CY"] if k in g["PY"] and g["PY"][k]["qty"] > 0 and g["CY"][k]["qty"] > 0]
    q0 = sum(g["PY"][k]["qty"] for k in common)
    q1 = sum(g["CY"][k]["qty"] for k in common)
    growth = q1 / q0 if q0 else 0.0
    per_group = {}
    for k in common:
        a, b = g["PY"][k], g["CY"][k]
        p0, p1 = a["rev"] / a["qty"], b["rev"] / b["qty"]
        t0, t1 = a["tariff"] / a["qty"], b["tariff"] / b["qty"]
        o0, o1 = a["other"] / a["qty"], b["other"] / b["qty"]
        gpu0 = p0 - t0 - o0
        per_group[k] = {
            "price": b["qty"] * (p1 - p0),
            "cost_tariff": -b["qty"] * (t1 - t0),
            "cost_other": -b["qty"] * (o1 - o0),
            "volume": a["qty"] * (growth - 1) * gpu0,
            "mix": (b["qty"] - a["qty"] * growth) * gpu0,
            "new": 0.0,
            "lost": 0.0,
        }
    for k in g["CY"]:
        if k not in per_group:
            b = g["CY"][k]
            per_group[k] = dict.fromkeys(DRIVERS, 0.0) | {"new": b["rev"] - b["tariff"] - b["other"]}
    for k in g["PY"]:
        if k not in per_group:
            a = g["PY"][k]
            per_group[k] = dict.fromkeys(DRIVERS, 0.0) | {"lost": -(a["rev"] - a["tariff"] - a["other"])}
    totals = {d: sum(v[d] for v in per_group.values()) for d in DRIVERS}
    gp = {p: sum(x["rev"] - x["tariff"] - x["other"] for x in g[p].values()) for p in g}
    return {"groups": per_group, "totals": totals, "gp": gp, "delta": gp["CY"] - gp["PY"]}


def mix_between(items: dict, ext, dim: str) -> dict:
    """Mix effect between the members of one dimension (e.g. DIY vs DIFM), on continuing items:
    (Q1_m - Q1 x share0_m) x (GPU0_m - GPU0_all). Members sum to the mix at that grain."""
    b = bridge(items, lambda k: attributes(ext, k)[dim])
    agg = {p: defaultdict(lambda: [0.0, 0.0]) for p in items}
    for p in items:
        for k, it in items[p].items():
            m = attributes(ext, k)[dim]
            agg[p][m][0] += it["qty"]
            agg[p][m][1] += it["rev"] - it["tariff"] - it["other"]
    common = [m for m in agg["CY"] if m in agg["PY"]]
    q0 = sum(agg["PY"][m][0] for m in common)
    q1 = sum(agg["CY"][m][0] for m in common)
    gpu_all = sum(agg["PY"][m][1] for m in common) / q0
    out = {m: (agg["CY"][m][0] - q1 * agg["PY"][m][0] / q0) * (agg["PY"][m][1] / agg["PY"][m][0] - gpu_all) for m in common}
    assert abs(sum(out.values()) - b["totals"]["mix"]) < 1.0 + 1e-6 * abs(b["totals"]["mix"])
    return out


def nested_mix(items: dict, ext) -> list[tuple[str, str, float]]:
    """Mix split into levels that add up: product mix, then channel within product line, then customer,
    then SKU. Each level is the bridge's mix at that grain minus the mix at the coarser grain, so the
    levels sum to the item-level mix exactly. Price moves the other way: whatever a coarser grain books
    as price, because of mix inside a group, shows up here as mix."""
    out, prev = [], 0.0
    for name, label, key in MIX_LEVELS:
        m = bridge(items, lambda k, key=key: key(attributes(ext, k)))["totals"]["mix"]
        out.append((name, label, m - prev))
        prev = m
    return out


# ---------------------------------------------------------------- findings


def rollup(deep: dict, ext, dim: str, driver: str) -> dict:
    out = defaultdict(float)
    for k, v in deep["groups"].items():
        out[attributes(ext, k)[dim]] += v[driver]
    return dict(out)


def find_drivers(items: dict, ext, defs: dict, deep: dict, mgmt: dict) -> list[dict]:
    """Three kinds of finding, each at least `materiality` dollars of gross profit:
    - top:         the largest member behind each driver
    - masked:      a member moving against its driver's total (a drag hidden under a gain, or the reverse)
    - reattributed: a driver that reads differently at the management grain than at the item grain
    """
    mat = defs["materiality"]
    f = []
    for d in ("price", "cost_tariff", "cost_other", "volume"):
        tot = deep["totals"][d]
        for dim in DIMENSIONS:
            r = rollup(deep, ext, dim, d)
            if not r:
                continue
            top = max(r, key=lambda m: abs(r[m]))
            if abs(r[top]) >= mat:
                f.append({"kind": "top", "driver": d, "dimension": dim, "member": top, "amount": round(r[top], 0)})
            for m, v in r.items():
                if abs(v) >= mat and v * tot < 0 and abs(v) >= 0.25 * abs(tot):
                    f.append({"kind": "masked", "driver": d, "dimension": dim, "member": m, "amount": round(v, 0), "under": round(tot, 0)})
    levels = nested_mix(items, ext)
    for name, _label, v in levels:
        if abs(v) >= mat:
            f.append({"kind": "top", "driver": "mix", "dimension": name, "member": None, "amount": round(v, 0)})
    product = levels[0][2]
    for name, _label, v in levels[1:]:
        if abs(v) >= mat and abs(product) >= mat and v * product < 0:
            f.append(
                {
                    "kind": "masked",
                    "driver": "mix",
                    "dimension": name,
                    "member": None,
                    "amount": round(v, 0),
                    "under": round(product, 0),
                    "under_dimension": "line",
                }
            )
    for d in ("price", "volume", "mix"):
        gap = mgmt["totals"][d] - deep["totals"][d]
        if abs(gap) >= mat:
            f.append(
                {
                    "kind": "reattributed",
                    "driver": d,
                    "dimension": "line",
                    "member": None,
                    "amount": round(deep["totals"][d], 0),
                    "management": round(mgmt["totals"][d], 0),
                }
            )
    for d in ("new", "lost"):
        if abs(deep["totals"][d]) >= mat:
            r = rollup(deep, ext, "line", d)
            top = max(r, key=lambda m: abs(r[m]))
            f.append({"kind": "top", "driver": d, "dimension": "line", "member": top, "amount": round(deep["totals"][d], 0)})
    f.sort(key=lambda x: (-{"masked": 2, "reattributed": 1, "top": 0}[x["kind"]], -abs(x["amount"])))
    return f


# ---------------------------------------------------------------- entry point


def _money(x: float) -> str:
    return f"{'-' if x < 0 else ''}${abs(x):,.0f}"


def analyze(ext, defs: dict | None = None) -> dict:
    """Check, tie out, bridge at the management grain and at the item grain, find drivers."""
    defs = defs or load_definitions()
    issues = data_checks(ext, defs)
    if any(i["blocking"] for i in issues):
        return {"published": False, "issues": issues, "tie_out": None, "findings": [], "totals": None}
    tie = tie_out(ext, defs)
    if not tie["ok"]:
        names = {"PY": "prior quarter", "CY": "current quarter"}
        gap = "; ".join(f"{names[p]} gross profit off by {_money(v['diff_gp'])}" for p, v in tie["periods"].items() if not v["ok"])
        issues.append({"code": "tie_out_gap", "detail": f"extract does not tie to the ledger: {gap}", "blocking": True})
        return {"published": False, "issues": issues, "tie_out": tie, "findings": [], "totals": None}
    items = normalise(ext, defs)
    deep = bridge(items, lambda k: k)
    mgmt = bridge(items, lambda k: attributes(ext, k)["line"])
    for b in (deep, mgmt):
        assert abs(sum(b["totals"].values()) - b["delta"]) < 0.01, "bridge does not add up"
    led = _ledger_delta(ext)
    return {
        "published": True,
        "issues": issues,
        "tie_out": tie,
        "delta_gp": round(deep["delta"] + led, 2),
        "totals": {d: round(v, 2) for d, v in deep["totals"].items()} | {"ledger_items": round(led, 2)},
        "management_totals": {d: round(v, 2) for d, v in mgmt["totals"].items()} | {"ledger_items": round(led, 2)},
        "mix_levels": [{"level": n, "label": lab, "amount": round(v, 2)} for n, lab, v in nested_mix(items, ext)],
        "findings": find_drivers(items, ext, defs, deep, mgmt),
    }


def _ledger_delta(ext) -> float:
    """Change in gross profit from ledger-only COGS items (a cost increase lowers gross profit)."""
    return -(
        sum(i["amount"] for i in ext.ledger_items if i["period"] == "CY")
        - sum(i["amount"] for i in ext.ledger_items if i["period"] == "PY")
    )


def management_view(ext, defs: dict | None = None) -> dict:
    """A month-end workbook: allocates rebates the same way, ties to the ledger (and stops if it does
    not tie), and bridges by product line only. It has no data checks, so an unknown order type falls
    into DIY and units stay as sold, and it cannot see customer, channel, or origin."""
    defs = defs or load_definitions()
    tie = tie_out(ext, defs)
    if not tie["ok"]:
        issue = {"code": "tie_out_gap", "detail": "workbook does not tie to the ledger", "blocking": True}
        return {"published": False, "issues": [issue], "tie_out": tie, "findings": [], "totals": None}
    cmap = defaultdict(lambda: "DIY") | defs["channel_map"]
    loose = defs | {"channel_map": cmap, "uom_to_each": defaultdict(lambda: 1)}
    items = normalise(ext, loose)
    mgmt = bridge(items, lambda k: attributes(ext, k)["line"])
    f = []
    for d in DRIVERS:
        r = {k: v[d] for k, v in mgmt["groups"].items()} if d != "mix" else {}
        if r:
            top = max(r, key=lambda m: abs(r[m]))
            if abs(r[top]) >= defs["materiality"]:
                f.append({"kind": "top", "driver": d, "dimension": "line", "member": top, "amount": round(r[top], 0)})
    if abs(mgmt["totals"]["mix"]) >= defs["materiality"]:
        f.append({"kind": "top", "driver": "mix", "dimension": "line", "member": None, "amount": round(mgmt["totals"]["mix"], 0)})
    led = _ledger_delta(ext)
    return {
        "published": True,
        "issues": [],
        "tie_out": tie,
        "delta_gp": round(mgmt["delta"] + led, 2),
        "totals": {d: round(v, 2) for d, v in mgmt["totals"].items()} | {"ledger_items": round(led, 2)},
        "findings": f,
    }
