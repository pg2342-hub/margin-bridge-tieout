import random

import pytest

from bridge.core import analyze, bridge, load_definitions, management_view, normalise
from bridge.data import build
from bridge.showcase import SHOWCASE

DEFS = load_definitions()


def test_clean_extract_ties_and_finds_nothing():
    out = analyze(build({"seed": 7}))
    assert out["published"] and out["tie_out"]["ok"]
    assert not out["issues"]
    assert not [f for f in out["findings"] if f["kind"] != "top"]


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_effects_add_up_at_every_grain(seed):
    rng = random.Random(seed)
    scenario = {
        "seed": seed,
        "changes": [
            {"type": "price", "where": {"line": rng.choice(["Sensors", "Wipers", "Climate"])}, "pct": rng.uniform(-0.1, 0.1)},
            {"type": "channel_shift", "customer": "Retailer A", "share": rng.uniform(0, 0.5)},
            {"type": "tariff_rate", "origin": "Mexico", "rate": rng.uniform(0, 0.2)},
            {"type": "new_skus", "line": "Ignition", "n": 2},
            {"type": "discontinue", "line": "Filters", "n": 3},
        ],
    }
    ext = build(scenario)
    items = normalise(ext, DEFS)
    for grain in (lambda k: k, lambda k: k[1], lambda k: (k[1], k[2])):
        b = bridge(items, grain)
        assert sum(b["totals"].values()) == pytest.approx(b["delta"], abs=0.01)
    out = analyze(ext)
    gl = ext.gl
    assert out["delta_gp"] == pytest.approx((gl["CY"]["revenue"] - gl["CY"]["cogs"]) - (gl["PY"]["revenue"] - gl["PY"]["cogs"]), abs=1.0)


def test_price_effect_matches_planted_dollars():
    ext = build({"seed": 7, "changes": [{"type": "price", "where": {"customer": "Distributor D"}, "pct": -0.06}]})
    out = analyze(ext)
    assert out["totals"]["price"] == pytest.approx(ext.truth["price"], rel=0.005)


def test_case_pack_is_converted_to_eaches():
    plain = analyze(build({"seed": 23}))
    packed = analyze(build({"seed": 23, "traps": [{"type": "case_pack", "customer": "Retailer C", "prefix": "WIP", "pack": 6}]}))
    assert packed["published"]
    assert packed["totals"]["price"] == pytest.approx(plain["totals"]["price"], abs=20_000)


@pytest.mark.parametrize(
    "trap,code",
    [
        ({"type": "unmapped_order_code"}, "unmapped_order_code"),
        ({"type": "case_pack", "customer": "Retailer A", "prefix": "WIP", "pack": 12}, "unknown_uom"),
        ({"type": "unmatched_rebate"}, "unmatched_rebate"),
        ({"type": "missing_lines", "n": 60}, "tie_out_gap"),
        ({"type": "duplicate_lines"}, "duplicate_lines"),
    ],
)
def test_bad_extracts_stop_the_bridge(trap, code):
    out = analyze(build({"seed": 11, "traps": [trap]}))
    assert not out["published"]
    assert code in {i["code"] for i in out["issues"]}
    assert out["findings"] == []


def test_workbook_stops_on_a_gap_but_not_on_bad_codes():
    gap = management_view(build({"seed": 11, "traps": [{"type": "missing_lines", "n": 60}]}))
    assert not gap["published"]
    codes = management_view(build({"seed": 11, "traps": [{"type": "unmapped_order_code"}]}))
    assert codes["published"]  # the unknown code falls into DIY, and the totals still tie


def test_tie_out_needs_named_ledger_items():
    ext = build({"seed": 7})
    assert analyze(ext)["tie_out"]["ok"]
    ext.ledger_items = ext.ledger_items[1:]  # drop one named item: the gap is now unexplained
    out = analyze(ext)
    assert not out["published"] and "tie_out_gap" in {i["code"] for i in out["issues"]}


def test_showcase_story():
    out = analyze(build(SHOWCASE))
    kinds = {(f["kind"], f["driver"], f["dimension"]) for f in out["findings"]}
    assert ("masked", "mix", "channel") in kinds
    assert ("reattributed", "price", "line") in kinds
    assert out["totals"]["price"] > out["management_totals"]["price"]
    assert out["totals"]["mix"] < 0 < out["management_totals"]["mix"]
    levels = {x["level"]: x["amount"] for x in out["mix_levels"]}
    assert sum(levels.values()) == pytest.approx(out["totals"]["mix"], abs=0.01)
    assert levels["line"] > 0 > levels["channel"]
    # what the product-line bridge books as price is the channel mix inside its lines
    ext = build(SHOWCASE)
    items = normalise(ext, DEFS)
    by_line = bridge(items, lambda k: ext.skus[k[0]].line)["totals"]["price"]
    by_line_channel = bridge(items, lambda k: (ext.skus[k[0]].line, k[2]))["totals"]["price"]
    assert by_line_channel - by_line == pytest.approx(-levels["channel"], rel=0.001)
