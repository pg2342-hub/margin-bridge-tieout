"""A made-up aftermarket parts maker, as an ERP extract for two quarters.

Everything here is synthetic. The shape follows what a finance team actually exports:

- invoice lines (one row per invoice, SKU, customer and order type), with the
  order type as a code, the unit of measure as sold, and extended cost split into
  material, tariff and other cost;
- rebate memos posted as separate customer-level credits, not on the invoice line;
- the general ledger totals the bridge has to tie to.

A scenario is a list of planted changes on top of a clean baseline, so an eval case
knows exactly what moved and by how much.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

LINES = {
    # product line: (price range, prior-year gross margin before tariff, share of units)
    "Ignition": ((18, 60), 0.42, 0.20),
    "Sensors": ((35, 140), 0.46, 0.18),
    "Brake hydraulics": ((25, 90), 0.36, 0.16),
    "Climate": ((90, 380), 0.33, 0.10),
    "Wipers": ((9, 28), 0.30, 0.22),
    "Filters": ((6, 24), 0.27, 0.14),
}
ORIGIN_WEIGHTS = {"China": 0.45, "Mexico": 0.35, "USA": 0.20}
PY_TARIFF = {"China": 0.10, "Mexico": 0.0, "USA": 0.0}

CUSTOMERS = {
    # customer: (channel split, invoice discount, rebate rate, product lines carried)
    "Retailer A": ({"DIY": 0.65, "DIFM": 0.35}, 0.04, 0.05, list(LINES)),
    "Retailer B": ({"DIY": 0.55, "DIFM": 0.45}, 0.05, 0.06, list(LINES)),
    "Retailer C": ({"DIY": 0.80, "DIFM": 0.20}, 0.03, 0.04, ["Ignition", "Sensors", "Wipers", "Filters", "Brake hydraulics"]),
    "Distributor D": ({"DIFM": 1.0}, 0.08, 0.03, ["Ignition", "Sensors", "Brake hydraulics", "Climate"]),
    "Distributor E": ({"DIFM": 1.0}, 0.07, 0.03, ["Sensors", "Brake hydraulics", "Climate", "Filters"]),
    "Online F": ({"DIY": 1.0}, 0.02, 0.02, ["Ignition", "Sensors", "Wipers", "Filters"]),
}
CUSTOMER_WEIGHT = {
    "Retailer A": 0.26,
    "Retailer B": 0.24,
    "Retailer C": 0.14,
    "Distributor D": 0.14,
    "Distributor E": 0.12,
    "Online F": 0.10,
}
DIFM_PRICE_FACTOR = 0.88  # program pricing for installer (do-it-for-me) business
ORDER_CODES = {"DIY": ["RTL", "WEB"], "DIFM": ["PGM", "COM"]}
SKUS_PER_LINE = 20
MONTHS = {"PY": ["2025-07", "2025-08", "2025-09"], "CY": ["2026-07", "2026-08", "2026-09"]}


@dataclass
class Sku:
    sku: str
    line: str
    origin: str
    list_price: float
    material: float  # per each, before tariff
    other: float  # conversion, freight, overhead per each
    base_units: float  # quarterly units across all customers


@dataclass
class Extract:
    lines: list[dict]
    rebates: list[dict]
    gl: dict  # period -> {"revenue": x, "cogs": y}
    skus: dict[str, Sku]
    truth: dict = field(default_factory=dict)


def _catalog(rng: random.Random) -> dict[str, Sku]:
    skus = {}
    for li, (line, ((lo, hi), gm, share)) in enumerate(LINES.items()):
        for n in range(SKUS_PER_LINE):
            price = round(rng.uniform(lo, hi), 2)
            origin = rng.choices(list(ORIGIN_WEIGHTS), weights=list(ORIGIN_WEIGHTS.values()))[0]
            cost = price * (1 - gm + rng.uniform(-0.04, 0.04))
            material = cost * 0.62
            skus[f"{line[:3].upper()}-{li}{n:02d}"] = Sku(
                sku=f"{line[:3].upper()}-{li}{n:02d}",
                line=line,
                origin=origin,
                list_price=price,
                material=round(material, 4),
                other=round(cost - material, 4),
                base_units=600_000 * share / SKUS_PER_LINE * rng.uniform(0.5, 1.5),
            )
    return skus


def _matches(where: dict | None, sku: Sku, customer: str, channel: str) -> bool:
    if not where:
        return True
    want = {"line": sku.line, "origin": sku.origin, "customer": customer, "channel": channel, "sku": sku.sku}
    return all(want[k] == v for k, v in where.items())


def build(scenario: dict | None = None) -> Extract:
    """Build the two-quarter extract for a scenario: {"seed", "changes", "traps"}."""
    scenario = scenario or {}
    rng = random.Random(scenario.get("seed", 7))
    skus = _catalog(rng)
    changes = scenario.get("changes", [])
    tariff_cy = dict(PY_TARIFF)
    for c in changes:
        if c["type"] == "tariff_rate":
            tariff_cy[c["origin"]] = c["rate"]

    # quarterly units by (sku, customer, channel) for each period
    units = {"PY": {}, "CY": {}}
    for s in skus.values():
        carriers = [c for c, spec in CUSTOMERS.items() if s.line in spec[3]]
        wsum = sum(CUSTOMER_WEIGHT[c] for c in carriers)
        for cust in carriers:
            for ch, chs in CUSTOMERS[cust][0].items():
                base = s.base_units * CUSTOMER_WEIGHT[cust] / wsum * chs
                units["PY"][(s.sku, cust, ch)] = base * rng.uniform(0.98, 1.02)
                units["CY"][(s.sku, cust, ch)] = base * rng.uniform(0.98, 1.02)

    # planted volume and mix changes act on CY units
    for c in changes:
        t = c["type"]
        if t == "volume":
            for k in units["CY"]:
                if _matches(c.get("where"), skus[k[0]], k[1], k[2]):
                    units["CY"][k] *= 1 + c["pct"]
        elif t == "channel_shift":  # move a share of a customer's DIY units to DIFM, same SKU
            for (sku, cust, ch), q in list(units["CY"].items()):
                if cust == c["customer"] and ch == "DIY" and (sku, cust, "DIFM") in units["CY"]:
                    if c.get("where") and not _matches(c["where"], skus[sku], cust, ch):
                        continue
                    moved = q * c["share"]
                    units["CY"][(sku, cust, "DIY")] -= moved
                    units["CY"][(sku, cust, "DIFM")] += moved
        elif t == "line_shift":  # move units from one product line to another, same customers
            src = [k for k in units["CY"] if skus[k[0]].line == c["from"]]
            dst = [k for k in units["CY"] if skus[k[0]].line == c["to"]]
            moved = sum(units["CY"][k] for k in src) * c["share"]
            for k in src:
                units["CY"][k] *= 1 - c["share"]
            dst_total = sum(units["CY"][k] for k in dst)
            for k in dst:
                units["CY"][k] += moved * units["CY"][k] / dst_total
        elif t == "customer_shift":  # move units from one customer to another on shared SKUs
            pairs = [
                (k, (k[0], c["to"], ch2))
                for k in units["CY"]
                if k[1] == c["from"]
                for ch2 in CUSTOMERS[c["to"]][0]
                if (k[0], c["to"], ch2) in units["CY"]
            ]
            for src, dst in pairs:
                n_dst = len([p for p in pairs if p[0] == src])
                moved = units["CY"][src] * c["share"] / n_dst
                units["CY"][dst] += moved
            for src in {p[0] for p in pairs}:
                units["CY"][src] *= 1 - c["share"]
        elif t == "discontinue":
            gone = [s for s in skus.values() if s.line == c["line"]][: c["n"]]
            for k in list(units["CY"]):
                if skus[k[0]] in gone:
                    del units["CY"][k]
        elif t == "new_skus":
            for i in range(c["n"]):
                tmpl = [s for s in skus.values() if s.line == c["line"]][i]
                new = Sku(f"{tmpl.sku}N", tmpl.line, tmpl.origin, tmpl.list_price * 1.1, tmpl.material, tmpl.other, tmpl.base_units)
                skus[new.sku] = new
                for k in [k for k in units["CY"] if k[0] == tmpl.sku]:
                    units["CY"][(new.sku, k[1], k[2])] = units["CY"][k] * 0.5

    truth = {"price": 0.0, "cost_tariff": 0.0, "cost_other": 0.0}

    def unit_economics(period: str, s: Sku, cust: str, ch: str):
        disc, reb = CUSTOMERS[cust][1], CUSTOMERS[cust][2]
        price = s.list_price * (1 - disc) * (DIFM_PRICE_FACTOR if ch == "DIFM" else 1.0)
        surcharge = 0.0
        material, other = s.material, s.other
        rate = PY_TARIFF[s.origin] if period == "PY" else tariff_cy[s.origin]
        if period == "CY":
            for c in changes:
                if c["type"] == "price" and _matches(c.get("where"), s, cust, ch):
                    price *= 1 + c["pct"]
                elif c["type"] == "surcharge" and _matches(c.get("where"), s, cust, ch):
                    surcharge += price * c["pct"]
                elif c["type"] == "material_cost" and _matches(c.get("where"), s, cust, ch):
                    material *= 1 + c["pct"]
        return price, surcharge, material, material * rate, other, reb

    lines, rebates = [], []
    gl = {}
    inv = 0
    for period in ("PY", "CY"):
        rev = cogs = 0.0
        cust_gross = {}
        for (sku, cust, ch), q in sorted(units[period].items()):
            s = skus[sku]
            price, surcharge, material, tariff, other, reb = unit_economics(period, s, cust, ch)
            if period == "CY" and (sku, cust, ch) in units["PY"]:
                p0, s0, m0, t0, o0, _ = unit_economics("PY", s, cust, ch)
                truth["price"] += q * ((price + surcharge) - (p0 + s0)) * (1 - reb)
                truth["cost_tariff"] -= q * (tariff - t0)
                truth["cost_other"] -= q * ((material + other) - (m0 + o0))
            monthly = _split(q, rng)
            for month, mq in zip(MONTHS[period], monthly):
                mq = round(mq)
                if mq <= 0:
                    continue
                inv += 1
                gross = round(mq * (price + surcharge), 2)
                row = {
                    "period": period,
                    "month": month,
                    "invoice": f"INV{inv:06d}",
                    "sku": sku,
                    "customer": cust,
                    "order_type": rng.choice(ORDER_CODES[ch]),
                    "uom": "EA",
                    "qty": mq,
                    "gross": gross,
                    "surcharge": round(mq * surcharge, 2),
                    "cost_material": round(mq * material, 2),
                    "cost_tariff": round(mq * tariff, 2),
                    "cost_other": round(mq * other, 2),
                }
                lines.append(row)
                cust_gross[(cust, month)] = cust_gross.get((cust, month), 0.0) + gross
                rev += gross
                cogs += row["cost_material"] + row["cost_tariff"] + row["cost_other"]
        for (cust, month), g in sorted(cust_gross.items()):
            amt = round(g * CUSTOMERS[cust][2], 2)
            rebates.append({"period": period, "month": month, "memo": f"CM-{cust[:3].upper()}-{month}", "customer": cust, "amount": amt})
            rev -= amt
        gl[period] = {"revenue": round(rev, 2), "cogs": round(cogs, 2)}

    ext = Extract(lines=lines, rebates=rebates, gl=gl, skus=skus, truth={k: round(v, 2) for k, v in truth.items()})
    for trap in scenario.get("traps", []):
        _apply_trap(ext, trap, rng)
    return ext


def _split(q: float, rng: random.Random) -> list[float]:
    w = [rng.uniform(0.9, 1.1) for _ in range(3)]
    return [q * x / sum(w) for x in w]


def _apply_trap(ext: Extract, trap: dict, rng: random.Random) -> None:
    """Data problems a real extract has. The ledger stays the truth; only the extract changes."""
    t = trap["type"]
    cy = [r for r in ext.lines if r["period"] == "CY"]
    if t == "unmapped_order_code":  # a new order type nobody added to the channel map
        for r in rng.sample(cy, 40):
            r["order_type"] = "XFR"
    elif t == "case_pack":  # a customer buys some SKUs in cases of N; qty and price are per case
        n = trap.get("pack", 6)
        uom = trap.get("uom", f"CS{n}")
        hit = [r for r in ext.lines if r["customer"] == trap["customer"] and r["sku"].startswith(trap.get("prefix", "WIP"))]
        for r in hit:
            cases = max(1, round(r["qty"] / n))
            scale = cases * n / r["qty"]
            for k in ("gross", "surcharge", "cost_material", "cost_tariff", "cost_other"):
                r[k] = round(r[k] * scale, 2)
            r["qty"], r["uom"] = cases, uom
        _restate_gl(ext)
    elif t == "unmatched_rebate":  # a memo keyed to a customer name the master does not know
        memo = next(m for m in ext.rebates if m["period"] == "CY" and m["customer"] == "Retailer B")
        memo["customer"] = "RETAILER B INC"
    elif t == "missing_lines":  # the extract was cut off; the ledger still has the full month
        drop = [r for r in cy if r["month"] == "2026-09"][: trap.get("n", 60)]
        ids = {id(r) for r in drop}
        ext.lines = [r for r in ext.lines if id(r) not in ids]
    elif t == "duplicate_lines":  # an export that repeated a page of invoices
        dup = [dict(r) for r in cy[100:130]]
        ext.lines.extend(dup)
    else:
        raise ValueError(f"unknown trap {t}")


def _restate_gl(ext: Extract) -> None:
    """Rebuild GL totals from the extract after a trap that changes amounts but not truth."""
    for period in ("PY", "CY"):
        rows = [r for r in ext.lines if r["period"] == period]
        reb = sum(m["amount"] for m in ext.rebates if m["period"] == period)
        ext.gl[period] = {
            "revenue": round(sum(r["gross"] for r in rows) - reb, 2),
            "cogs": round(sum(r["cost_material"] + r["cost_tariff"] + r["cost_other"] for r in rows), 2),
        }
