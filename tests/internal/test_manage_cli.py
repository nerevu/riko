"""Tests for the ``manage`` command-line interface."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from click.testing import CliRunner

from riko.cli import _codegen, _import_commands, _lint
from riko.cli._docstyle import summary_leads_with_output
from riko.cli.manage import manager

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def test_docstring_summary_output_lead_detection() -> None:
    assert summary_leads_with_output("Returns the parsed response body.")
    assert not summary_leads_with_output("Parses the response body.")


def _record(calls: list[str], name: str, code: int = 0) -> Callable[[], int]:
    def runner() -> int:
        calls.append(name)
        return code

    return runner


def _record_path(calls: list[str], name: str, code: int = 0) -> Callable[[Path], int]:
    def runner(_: Path) -> int:
        calls.append(name)
        return code

    return runner


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ([], ["config"]),
        (["--names", "--api"], ["names", "api"]),
        (["--all"], ["config", "names", "pipes", "api"]),
    ],
)
def test_codegen_selectors(
    monkeypatch: pytest.MonkeyPatch, args: list[str], expected: list[str]
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        _codegen,
        "_CODEGEN",
        {
            name: (_record(calls, name), lambda name=name: name, f"{name} failed")
            for name in ("config", "names", "pipes", "api")
        },
    )

    result = CliRunner().invoke(_codegen.CODEGEN_COMMAND, args)
    assert result.exit_code == 0
    assert calls == expected


def test_codegen_mode_is_removed() -> None:
    result = CliRunner().invoke(_codegen.CODEGEN_COMMAND, ["--mode", "config"])
    assert result.exit_code == 2


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ([], ["canonical"]),
        (["--relative", "--architecture"], ["relative", "architecture"]),
        (["--all"], ["canonical", "relative", "architecture"]),
    ],
)
def test_import_selectors(
    monkeypatch: pytest.MonkeyPatch, args: list[str], expected: list[str]
) -> None:
    calls: list[str] = []
    names = ("canonical", "relative", "architecture")
    monkeypatch.setattr(
        _import_commands,
        "_IMPORT_CHECKS",
        {name: _record_path(calls, name) for name in names},
    )

    result = CliRunner().invoke(_import_commands.IMPORTS_COMMAND, args)
    assert result.exit_code == 0
    assert calls == expected


def test_import_all_runs_every_check(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        _import_commands,
        "_IMPORT_CHECKS",
        {
            "canonical": _record_path(calls, "canonical", 1),
            "relative": _record_path(calls, "relative"),
            "architecture": _record_path(calls, "architecture"),
        },
    )

    result = CliRunner().invoke(_import_commands.IMPORTS_COMMAND, ["--all"])
    assert result.exit_code == 1
    assert calls == ["canonical", "relative", "architecture"]


def _patch_lints(monkeypatch: pytest.MonkeyPatch, calls: list[str]) -> None:
    monkeypatch.setattr(
        _lint, "_ruff_check", lambda *_, **_kw: calls.append("ruff") or 0
    )
    monkeypatch.setattr(_lint, "_check_rst", lambda *_: calls.append("rst") or 0)
    monkeypatch.setattr(_lint, "_check_docs", lambda: calls.append("docs") or 0)
    monkeypatch.setattr(
        _lint, "_docstring_check", lambda *_: calls.append("docstrings") or 0
    )
    monkeypatch.setattr(
        _lint, "_check_actions", lambda *_: calls.append("actions") or 0
    )
    monkeypatch.setattr(_lint, "_check_yaml", lambda *_: calls.append("yaml") or 0)
    monkeypatch.setattr(
        _lint, "run_import_checks", lambda *_: calls.append("imports") or 0
    )
    monkeypatch.setattr(_lint, "_check_types", lambda *_: calls.append("types") or 0)
    monkeypatch.setattr(
        _lint, "_verify_types", lambda *_: calls.append("verify-types") or 0
    )
    monkeypatch.setattr(_lint, "_twine_check", lambda: calls.append("dist") or 0)
    monkeypatch.setattr(_lint, "_pylint_check", lambda *_: calls.append("strict") or 0)


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ([], ["ruff"]),
        (["--rst", "--yaml"], ["rst", "yaml"]),
        (
            ["--all"],
            ["ruff", "rst", "docs", "docstrings", "actions", "yaml", "imports"],
        ),
        (["--check-types", "--strict"], ["types", "strict"]),
    ],
)
def test_lint_selectors(
    monkeypatch: pytest.MonkeyPatch, args: list[str], expected: list[str]
) -> None:
    calls: list[str] = []
    _patch_lints(monkeypatch, calls)

    result = CliRunner().invoke(_lint.LINT_COMMAND, args)

    assert result.exit_code == 0
    assert calls == expected


def test_imports_is_nested_under_lint() -> None:
    runner = CliRunner()
    nested = runner.invoke(manager, ["lint", "imports", "--help"])
    top_level = runner.invoke(manager, ["imports", "--help"])

    assert nested.exit_code == 0
    assert "--architecture" in nested.output
    assert top_level.exit_code == 2
