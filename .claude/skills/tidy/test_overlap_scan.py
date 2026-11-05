"""
Smoke-tests overlap_scan.py's sections on a throwaway repository.

Run after editing the tidy scripts:

    uv run --active pytest .claude/skills/tidy/test_overlap_scan.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import overlap_scan

CONFIG = '''\
def load_settings(env):
    """
    Loads settings.

    >>> load_settings({"RIKO_NODE_THREADS": "many"}).node_threads
    40
    >>> load_settings({"RIKO_NODE_THREADS": None})
    Traceback (most recent call last):
    ValueError: RIKO_NODE_THREADS must be a string
    """


def ticks(n):
    """
    Counts ticks.

    >>> ticks(1)
    1
    >>> ticks(2)
    2
    >>> ticks(3)
    3
    >>> ticks(4)
    4
    >>> ticks(5)
    5
    >>> ticks(6)
    6
    """


class Gizmo:
    pass
'''
SURFACE = 'STABLE = ("load_settings",)\n'
HELPERS = """\
def build_pair(value):
    first = [value]
    first.append(value)
"""
VALUES = """\
import pytest

from riko.base import load_settings

ENV_OVERRIDES = [
    pytest.param("RIKO_NODE_THREADS", "many", "node_threads", 40, id="many"),
    pytest.param("RIKO_NODE_THREADS", "-1", "node_threads", 40, id="int-below-min"),
    pytest.param(
        "RIKO_FETCH_TIMEOUT_SECONDS", "2.5", "fetch_timeout", 2.5, id="near-miss"
    ),
    pytest.param(
        "RIKO_FETCH",  # a comment keeps it open
        "3",
        "fetch",
        3,
        id="commented",
    ),
]
NAMES = ["alpha", "beta", "gamma"]


class TestLoadSettings:
    @pytest.mark.parametrize(("key", "raw", "name", "expected"), ENV_OVERRIDES)
    def test_env_override_or_default(self, key, raw, name, expected):
        assert getattr(load_settings({key: raw}), name) == expected

    def test_a_non_string_is_refused(self):
        with pytest.raises(ValueError, match="must be a string"):
            load_settings({"RIKO_NODE_THREADS": None})
"""
ALPHA = """\
import pytest

from riko._config import _hidden, ticks

LABELS = ["alpha", "beta", "gamma"]


def wrap():
    return _hidden()


class TestTicks:
    def test_ticks_refuses_a_negative(self):
        with pytest.raises(ValueError):
            ticks(-1)

    def test_ticks_counts(self, monkeypatch):
        monkeypatch.setattr("riko._config.LIMIT", 3)
        assert wrap() == ticks(LABELS) == shared()

    @pytest.mark.parametrize("raw", [pytest.param(1, id="one")])
    def test_ticks_table(self, raw):
        assert ticks(raw) == raw

    def test_ticks_two(self):
        assert ticks(2) == 2

    def test_ticks_three(self):
        assert ticks(3) == 3

    def test_ticks_inline(self):
        first = ["x"]
        first.append("x")


def shared():
    return 1


class TestGizmo:
    def test_shared(self):
        assert shared()


class TestReiteration:
    def test_twice(self):
        assert shared() == shared()
"""
SCRIPT = """\
from tests import run_module


class TestRunPipe:
    def test_spawns(self):
        assert run_module("runpipe", "demo")

    def test_entry_point(self):
        assert run_module("runpipe", "demo", entry_point=True)

    def test_module_form(self):
        \"\"\"The ``python -m`` form runs.\"\"\"
        assert run_module("runpipe", "demo")
"""
LEADS = [
    pytest.param("helpers", "build_pair body inlined in", id="inlined-helper"),
    pytest.param("helpers", "under different names: LABELS", id="value"),
    pytest.param("shapes", "test_ticks_two matches table test", id="row-candidate"),
    pytest.param(
        "rows",
        "'near-miss' would be 92 columns on one line (4 over)",
        id="near-miss-row",
    ),
    pytest.param("shapes", "(small) tests/public/test_alpha.py", id="small-shapes"),
    pytest.param("unsupported", "_hidden via wrap x1", id="via-helper"),
    pytest.param("unsupported", "monkeypatch riko._config.LIMIT", id="monkeypatch"),
    pytest.param("unsupported", "TestLoadSettings: uses only supported", id="reverse"),
    pytest.param("placement", "TestTicks: behavior after", id="class-order"),
    pytest.param("placement", "below its first user TestTicks;", id="several-users"),
    pytest.param("placement", "TestGizmo: never names Gizmo", id="unnamed-subject"),
    pytest.param("doctest-balance", "ticks: 6 examples; tables:", id="balance"),
    pytest.param("processes", "TestRunPipe::test_spawns: starts", id="process"),
]


@pytest.fixture
def report(tmp_path):
    tier = tmp_path / "tests" / "internal"
    public = tmp_path / "tests" / "public"
    (tmp_path / "riko" / "base").mkdir(parents=True)
    tier.mkdir(parents=True)
    public.mkdir()
    (tmp_path / "tests" / "functional").mkdir()
    (tmp_path / "riko" / "_config.py").write_text(CONFIG)
    (tmp_path / "riko" / "base" / "_api_surface.py").write_text(SURFACE)
    (tmp_path / "tests" / "_helpers.py").write_text(HELPERS)
    (tier / "test_values.py").write_text(VALUES)
    (public / "test_alpha.py").write_text(ALPHA)
    (tmp_path / "tests" / "functional" / "test_script.py").write_text(SCRIPT)
    sections = overlap_scan.build_sections(tmp_path, 2)
    return {section: [text for text, _ in found] for section, found in sections.items()}


def test_doctest_sections_pair_a_doctest_with_its_pytest_twin(report):
    args, errors = report["doctest-args"], report["doctest-raises"]

    assert len(args) == len(errors) == 1
    assert "doctest load_settings" in args[0]
    assert "tests/internal/test_values.py:6 TestLoadSettings" in args[0]
    assert "doctest load_settings" in errors[0]
    assert "test_a_non_string_is_refused" in errors[0]
    assert errors[0].endswith("(same callee)")


@pytest.mark.parametrize(("section", "fragment"), LEADS)
def test_section_lists_the_lead(report, section, fragment):
    assert any(fragment in text for text in report[section]), report[section]


def test_a_commented_row_is_never_joined(report):
    assert not [text for text in report["rows"] if "commented" in text]


def test_a_process_with_a_stated_reason_is_not_a_lead(report):
    assert len(report["processes"]) == 1, report["processes"]


def test_a_concept_named_class_is_not_an_unnamed_subject(report):
    assert not [text for text in report["placement"] if "Reiteration" in text]
