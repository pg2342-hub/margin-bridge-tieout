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
}


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
    """Extract totals against the ledger, each period. Gross profit is revenue less COGS."""
    tol = defs["tie_out_tolerance"]
    out = {"ok": True, "periods": {}}
    for period in ("PY", "CY"):
        rows = [r for r in ext.lines if r["period"] == period]
        rev = sum(r["gross"] for r in rows) - sum(m["amount"] for m in ext.rebates if m["period"] == period)
        cogs = sum(r["cost_material"] + r["cost_tariff"] + r["cost_other"] for r in rows)
        gl = ext.gl[period]
        d_rev, d_gp = rev - gl["revenue"], (rev - cogs) - (gl["revenue"] - gl["cogs"])
        ok = abs(d_rev) <= tol and abs(d_gp) <= tol
        out["periods"][period] = {
            "revenue": round(rev, 2),
            "gl_revenue": gl["revenue"],
            "gp": round(rev - cogs, 2),
            "gl_gp": round(gl["revenue"] - gl["cogs"], 2),
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
    mix_by = {dim: mix_between(items, ext, dim) for dim in DIMENSIONS}
    for dim, r in mix_by.items():
        tot = sum(r.values())
        if abs(tot) >= mat:
            # the member whose share moved the most dollars
            top = max(r, key=lambda m: abs(r[m]))
            f.append({"kind": "top", "driver": "mix", "dimension": dim, "member": top, "amount": round(tot, 0)})
    signs = {dim: sum(r.values()) for dim, r in mix_by.items()}
    for dim, v in signs.items():
        for other, w in signs.items():
            if dim != other and abs(v) >= mat and abs(w) >= mat and v * w < 0:
                f.append(
                    {
                        "kind": "masked",
                        "driver": "mix",
                        "dimension": dim,
                        "member": max(mix_by[dim], key=lambda m: abs(mix_by[dim][m])),
                        "amount": round(v, 0),
                        "under": round(w, 0),
                        "under_dimension": other,
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
    return {
        "published": True,
        "issues": issues,
        "tie_out": tie,
        "delta_gp": round(deep["delta"], 2),
        "totals": {d: round(v, 2) for d, v in deep["totals"].items()},
        "management_totals": {d: round(v, 2) for d, v in mgmt["totals"].items()},
        "findings": find_drivers(items, ext, defs, deep, mgmt),
    }


def management_view(ext, defs: dict | None = None) -> dict:
    """What a careful month-end workbook does: ties totals to the ledger and bridges by product
    line. It has no data checks, so unknown codes fall into DIY and units stay as sold, and it
    publishes whatever the tie-out says."""
    defs = defs or load_definitions()
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
    return {
        "published": True,
        "issues": [],
        "tie_out": tie_out(ext, defs),
        "delta_gp": round(mgmt["delta"], 2),
        "totals": {d: round(v, 2) for d, v in mgmt["totals"].items()},
        "findings": f,
    }
