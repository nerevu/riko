"""
Smoke-tests covdiff.py on a hand-built coverage data file.

Run after editing the tidy scripts:

    uv run --active pytest .claude/skills/tidy/test_covdiff.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import coverage
import pytest

sys.path.insert(0, str(Path(__file__).parent))

import covdiff

_CUT = "tests/test_a.py::TestA::test_cut"
_COVER = "tests/test_a.py::TestA::test_cover"
CONTEXTS = {
    "": {1, 2},
    f"{_CUT}[row]|run": {2, 3, 4, 5},
    f"{_CUT}|setup": {6},
    f"{_COVER}|run": {4},
    "tests/test_a.py::TestAB::test_other|run": {5},
}
MATCHES = [
    pytest.param("tests/test_a.py", True, id="file"),
    pytest.param("tests/test_a.py::TestA", True, id="class"),
    pytest.param(_CUT, True, id="exact"),
    pytest.param("tests/test_a.py::TestAB", False, id="sibling-prefix"),
    pytest.param("tests/test_a.py::TestA::test_cu", False, id="partial-name"),
]
RUNS = [
    pytest.param([_CUT, "--", _COVER], 1, ["riko/x.py [3, 5, 6]"], id="uncovered"),
    pytest.param([_CUT, "--", "tests/test_a.py"], 0, [], id="covered-by-file"),
    pytest.param(
        [_CUT, "--", _COVER, "tests/test_a.py::TestAB"],
        1,
        ["riko/x.py [3, 6]"],
        id="two-covers",
    ),
]
USAGE_ERRORS = [
    pytest.param([_CUT, _COVER], id="no-separator"),
    pytest.param(["--data", "missing", _CUT, "--", _COVER], id="no-data"),
]


@pytest.fixture
def data_path(tmp_path: Path) -> Path:
    path = tmp_path / ".coverage"
    data = coverage.CoverageData(basename=str(path))

    for context, lines in CONTEXTS.items():
        data.set_context(context)
        data.add_lines({str(tmp_path / "riko" / "x.py"): lines})

    return path


@pytest.mark.parametrize(("prefix", "expected"), MATCHES)
def test_is_match(prefix: str, expected: bool) -> None:
    assert covdiff.is_match(f"{_CUT}[row]|run", [prefix]) is expected


@pytest.mark.parametrize(("argv", "code", "expected"), RUNS)
def test_main(
    data_path: Path,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
    code: int,
    expected: list[str],
) -> None:
    args = ["--data", str(data_path), *argv]
    assert covdiff.main(args, root=data_path.parent) == code
    assert capsys.readouterr().out.splitlines() == expected


@pytest.mark.parametrize("argv", USAGE_ERRORS)
def test_usage_error(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        covdiff.main(argv)

    assert caught.value.code == 2
