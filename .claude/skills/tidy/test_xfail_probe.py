"""
Smoke-tests xfail_probe.py on a throwaway test module.

Run after editing the tidy scripts:

    uv run --active pytest .claude/skills/tidy/test_xfail_probe.py --no-cov
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

TRIPWIRES = """\
import pytest


@pytest.fixture
def broken():
    raise RuntimeError("boom")


@pytest.mark.xfail(strict=True, raises=NotImplementedError)
def test_pending():
    raise NotImplementedError("pending")


@pytest.mark.xfail(strict=True, raises=NotImplementedError)
def test_wrong_error():
    raise KeyError("missing")


@pytest.mark.xfail(strict=True, raises=RuntimeError)
def test_broken_fixture(broken):
    pass


@pytest.mark.xfail(strict=True)
def test_any_error():
    raise ValueError("bad")


@pytest.mark.xfail(strict=True, raises=ValueError)
def test_landed():
    pass
"""
VERDICTS = [
    pytest.param("MISMATCH *::test_wrong_error *actual=KeyError*", id="mismatch"),
    pytest.param("SETUP *::test_broken_fixture *actual=RuntimeError: boom", id="setup"),
    pytest.param("UNPINNED *::test_any_error *raises=- actual=ValueError*", id="any"),
    pytest.param("PASSES *::test_landed *actual=-*", id="passes"),
]


@pytest.fixture
def output(pytester):
    pytester.makepyfile(test_tripwires=TRIPWIRES)
    return pytester.runpytest("-p", "xfail_probe").stdout


@pytest.mark.parametrize("pattern", VERDICTS)
def test_probe_lists_the_suspect(output, pattern):
    output.fnmatch_lines([pattern])


def test_a_documented_failure_is_only_counted(output):
    output.fnmatch_lines(["SETUP=1 MISMATCH=1 UNPINNED=1 PASSES=1 ok=1"])
    output.no_fnmatch_line("* *::test_pending *")
