"""Run all 25 cases on data seeds the cases were not written with, to check the eval is not tuned to its seeds."""

import copy
import json
import sys
import tempfile
from pathlib import Path

import yaml
from golive_gate.cli import main

EVAL = Path(__file__).resolve().parents[1] / "eval"
SEEDS = (101, 202, 303, 404, 505, 606, 707)


def sweep() -> int:
    cases = yaml.safe_load((EVAL / "cases.yml").read_text())["cases"]
    total = 0
    for seed in SEEDS:
        cs = copy.deepcopy(cases)
        for c in cs:
            c["input"]["seed"] = seed
        with tempfile.TemporaryDirectory() as d:
            (EVAL / "_sweep_cases.yml").write_text(yaml.safe_dump({"cases": cs}))
            (EVAL / "_sweep.yml").write_text(
                "cases: _sweep_cases.yml\nchecks: checks:checks\nagent: agent:tieout_agent\ngate: gate.yml\nruns: 1\n"
            )
            try:
                main(["run", str(EVAL / "_sweep.yml"), "--out", d])
                passed = json.loads(Path(d, "results.json").read_text())["summary"]["by_run"][0]["passed"]
            finally:
                (EVAL / "_sweep_cases.yml").unlink()
                (EVAL / "_sweep.yml").unlink()
        print(f"seed {seed}: {passed} of {len(cs)}")
        total += passed
    print(f"total: {total} of {len(cases) * len(SEEDS)}")
    return total


if __name__ == "__main__":
    sys.exit(0 if sweep() >= 0.95 * 25 * len(SEEDS) else 1)
