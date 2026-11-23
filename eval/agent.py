"""The two analyses the gate compares, called with each case's scenario."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bridge.core import analyze, management_view  # noqa: E402
from bridge.data import build  # noqa: E402


def tieout_agent(scenario: dict) -> dict:
    """Data checks, tie-out to the ledger, item-grain bridge, driver finder."""
    ext = build(scenario)
    return analyze(ext) | {"truth": ext.truth}


def workbook_agent(scenario: dict) -> dict:
    """A month-end workbook: product-line bridge, no data checks, no tie-out."""
    ext = build(scenario)
    return management_view(ext) | {"truth": ext.truth}
