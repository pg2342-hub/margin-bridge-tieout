"""Yes/no checks on each analysis. Three are critical: one failure blocks go-live."""

from golive_gate import NA, CheckSet

checks = CheckSet()


def _matches(f, want):
    if want.get("kind") and f["kind"] != want["kind"]:
        return False
    if f["driver"] != want["driver"]:
        return False
    for k in ("dimension", "member"):
        if want.get(k) and f.get(k) != want[k]:
            return False
    if "sign" in want and f["amount"] * want["sign"] <= 0:
        return False
    return True


@checks.check("stops_on_bad_data", text="A data problem stops the bridge; clean data publishes one.", critical=True)
def stops_on_bad_data(case, out):
    return out["published"] == ("issue" not in case.expected)


@checks.check("names_the_problem", text="The analysis names the planted data problem.", critical=True)
def names_the_problem(case, out):
    if "issue" not in case.expected:
        return NA
    return case.expected["issue"] in {i["code"] for i in out["issues"]}


@checks.check(
    "ties_to_ledger",
    text="A published bridge ties to the ledger, and its effects add up to the ledger's change in gross profit.",
    critical=True,
)
def ties_to_ledger(case, out):
    if not out["published"]:
        return NA
    if not out.get("tie_out") or not out["tie_out"]["ok"]:
        return False
    p = out["tie_out"]["periods"]
    gl_delta = p["CY"]["gl_gp"] - p["PY"]["gl_gp"]
    return abs(sum(out["totals"].values()) - out["delta_gp"]) <= 1.0 and abs(out["delta_gp"] - gl_delta) <= 1.0


@checks.check("finds_the_driver", text="The planted driver is in the findings, with the right sign; a hidden one is in the top 3.")
def finds_the_driver(case, out):
    want = case.expected.get("finding")
    if not want:
        return NA
    pool = out["findings"][:3] if case.group == "hidden" else out["findings"]
    return any(_matches(f, want) for f in pool)


@checks.check("sizes_it_right", text="The bridge's effect for the planted driver is within 2% of the planted dollars.")
def sizes_it_right(case, out):
    key = case.expected.get("truth")
    if not key or not out.get("totals"):
        return NA
    truth = out["truth"][key]
    return abs(out["totals"][key] - truth) <= 0.02 * abs(truth)


@checks.check("no_false_alarm", text="With nothing planted, there are no data issues and no masked or reattributed findings.")
def no_false_alarm(case, out):
    if not case.expected.get("clean"):
        return NA
    return not out["issues"] and not any(f["kind"] in ("masked", "reattributed") for f in out["findings"])
