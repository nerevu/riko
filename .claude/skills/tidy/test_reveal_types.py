"""
Smoke-tests reveal_types.py against a real riko symbol.

Run after editing the tidy scripts:

    uv run --active pytest .claude/skills/tidy/test_reveal_types.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import reveal_types


@pytest.mark.parametrize(
    ("spec", "reveal"),
    [
        pytest.param("m:foo", "reveal_type(_s0)", id="name"),
        pytest.param("m:foo(foobar.foo)", "reveal_type(_s0(foobar.foo))", id="call"),
        pytest.param("m:foo.bar", "reveal_type(_s0.bar)", id="attribute"),
        pytest.param("m: foo[int]", "reveal_type(_s0[int])", id="subscript"),
    ],
)
def test_get_probe_lines(spec: str, reveal: str) -> None:
    assert reveal_types.get_probe_lines(0, spec) == ("from m import foo as _s0", reveal)


def test_reveals_a_symbol_and_a_call(capsys: pytest.CaptureFixture[str]) -> None:
    reveals = {
        "riko.definitions._normalize:require_raw_edge": (
            "TypeRequire[Mapping[str, object], RawEdge]"
        ),
        "riko.base._require_guards:require_from_keys({'x'}, {'y'})": (
            "TypeRequire[Mapping[str, object], dict[str, object]]"
        ),
    }

    assert reveal_types.main(list(reveals)) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines == [f"{spec} -> {reveal}" for spec, reveal in reveals.items()]


@pytest.mark.parametrize(
    ("bad", "result", "error"),
    [
        pytest.param(
            "riko.definitions._normalize:missing_name",
            "Unknown",
            "riko.definitions._normalize:missing_name: ",
            id="unknown-name",
        ),
        pytest.param(
            "riko.definitions._normalize:require_raw_edge(",
            "(syntax error)",
            "",
            id="unclosed-paren",
        ),
        pytest.param("require_edge", "(syntax error)", "", id="no-module"),
    ],
)
def test_keeps_labels_after_a_bad_spec(
    capsys: pytest.CaptureFixture[str], bad: str, result: str, error: str
) -> None:
    good = "riko.definitions._normalize:require_raw_edge"
    expected = "TypeRequire[Mapping[str, object], RawEdge]"

    assert reveal_types.main([good, bad, good]) == 1
    captured = capsys.readouterr()
    assert captured.out.splitlines() == [
        f"{good} -> {expected}",
        f"{bad} -> {result}",
        f"{good} -> {expected}",
    ]
    assert captured.err.startswith(error)
    assert bool(captured.err) is bool(error)
