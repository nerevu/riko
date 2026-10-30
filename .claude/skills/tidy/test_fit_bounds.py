"""
Smoke-tests fit_bounds.py on a durations excerpt and a throwaway test module.

Run after editing the tidy scripts:

    uv run --active pytest .claude/skills/tidy/test_fit_bounds.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import fit_bounds

_SLOW = "tests/internal/test_x.py::TestY::test_slow"
DURATIONS = f"""\
============================= slowest durations ==============================
0.53s call     {_SLOW}[row-one]
1.20s call     {_SLOW}[row two]
9.00s setup    {_SLOW}[row-one]
4.00s teardown tests/internal/test_x.py::TestY::test_fast
0.01s call     tests/internal/test_x.py::TestY::test_fast
(12 durations < 0.005s hidden.  Use -vv to show these durations.)
"""
MORE_DURATIONS = f"0.90s call     {_SLOW}[row-one]\n"
FLAGS = [
    pytest.param(1, 0.01, "ok", "1", id="floor"),
    pytest.param(2, 0.01, "LOOSE", "1", id="loose"),
    pytest.param(2, 0.3, "ok", "2", id="fits"),
    pytest.param(3, 0.3, "LOOSE", "2", id="loose-above-fit"),
    pytest.param(5, 1.2, "TIGHT", "8", id="tight"),
    pytest.param(30, 7.0, "TIGHT", ">30", id="beyond-ladder"),
    pytest.param(0.05, 0.01, "subject?", "1", id="subject"),
    pytest.param(5, None, "unmeasured", "-", id="unmeasured"),
]
MODULE = """\
import pytest


@pytest.mark.timeout(30)
class TestY:
    @pytest.mark.timeout(2)
    def test_slow(self):
        pass

    def test_fast(self):
        pass
"""


def test_parse_durations() -> None:
    worst = fit_bounds.parse_durations(DURATIONS, MORE_DURATIONS)
    assert worst == {_SLOW: 1.2, "tests/internal/test_x.py::TestY::test_fast": 0.01}


@pytest.mark.parametrize(("seconds", "worst", "flag", "fit"), FLAGS)
def test_get_flag(seconds: float, worst: float | None, flag: str, fit: str) -> None:
    assert fit_bounds.get_flag(seconds, worst) == flag
    assert fit_bounds.get_fit_text(worst) == fit


def test_end_to_end(tmp_path: Path) -> None:
    path = tmp_path / "test_x.py"
    path.write_text(MODULE)
    durations = {
        "test_x.py::TestY::test_slow": 1.2,
        "test_x.py::TestY::test_fast": 0.01,
    }
    lines = list(fit_bounds.gen_report([path], durations, root=tmp_path))
    assert [line.split()[0] for line in lines] == ["LOOSE", "TIGHT"]
