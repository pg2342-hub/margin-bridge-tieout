"""The eval itself: the tie-out agent must pass the gate and the workbook must not."""

from pathlib import Path

from golive_gate.cli import main

CONFIG = str(Path(__file__).resolve().parents[1] / "eval" / "golive.yml")


def test_tieout_agent_is_go(tmp_path):
    assert main(["run", CONFIG, "--out", str(tmp_path)]) == 0


def test_workbook_is_no_go(tmp_path):
    assert main(["run", CONFIG, "--agent", "agent:workbook_agent", "--out", str(tmp_path)]) != 0
