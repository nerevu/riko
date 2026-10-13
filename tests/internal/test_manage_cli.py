"""Tests for the ``manage`` command-line interface."""

from __future__ import annotations

import tomllib
from datetime import date, timedelta
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from click.testing import CliRunner

from riko.cli import _codegen, _import_commands, _lint, _upgrade
from riko.cli._docstyle import summary_leads_with_output
from riko.cli.manage import manager

if TYPE_CHECKING:
    from collections.abc import Callable

PYPROJECT = Path(__file__).parents[2] / "pyproject.toml"
SCRIPTS: dict[str, str] = tomllib.loads(PYPROJECT.read_text())["project"]["scripts"]


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
        (["--all"], ["config", "names", "api"]),
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
            for name in _codegen._CODEGEN
        },
    )

    result = CliRunner().invoke(_codegen.CODEGEN_COMMAND, args)
    assert result.exit_code == 0
    assert calls == expected


def test_codegen_mode_is_removed() -> None:
    result = CliRunner().invoke(_codegen.CODEGEN_COMMAND, ["--mode", "config"])
    assert result.exit_code == 2


def _record_upgrade(
    monkeypatch: pytest.MonkeyPatch, stamp: Path, lock_code: int = 0
) -> list[list[str]]:
    calls: list[list[str]] = []
    monkeypatch.setattr(_upgrade, "_UPGRADE_STAMP", stamp)

    def call(args: list[str]) -> int:
        calls.append(args)
        return lock_code if args[1] == "lock" else 0

    monkeypatch.setattr(_upgrade, "_uv", "uv")
    monkeypatch.setattr(_upgrade, "call", call)
    return calls


SYNC = ["uv", "sync", "--active", "--locked", "--group", "dev", "--all-extras"]


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ([], [["uv", "lock", "--upgrade"], SYNC]),
        (
            ["-p", "ruff", "--package", "pyright"],
            [
                ["uv", "lock", "--upgrade-package=ruff", "--upgrade-package=pyright"],
                SYNC,
            ],
        ),
        (["--no-sync"], [["uv", "lock", "--upgrade"]]),
    ],
)
def test_upgrade_locks_then_syncs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    args: list[str],
    expected: list[list[str]],
) -> None:
    calls = _record_upgrade(monkeypatch, tmp_path / "stamp")
    result = CliRunner().invoke(manager, ["upgrade", *args])
    assert result.exit_code == 0
    assert calls == expected


def test_upgrade_skips_sync_when_lock_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    stamp = tmp_path / "stamp"
    calls = _record_upgrade(monkeypatch, stamp, lock_code=1)
    result = CliRunner().invoke(manager, ["upgrade"])
    assert result.exit_code == 1
    assert calls == [["uv", "lock", "--upgrade"]]
    assert not stamp.exists()


def test_upgrade_daily_runs_once_per_day(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    stamp = tmp_path / "cache" / "stamp"
    stamp.parent.mkdir()
    stamp.write_text((date.today() - timedelta(days=1)).isoformat())
    calls = _record_upgrade(monkeypatch, stamp)

    first = CliRunner().invoke(manager, ["upgrade", "--daily"])
    second = CliRunner().invoke(manager, ["upgrade", "--daily"])

    assert (first.exit_code, second.exit_code) == (0, 0)
    assert calls == [["uv", "lock", "--upgrade"], SYNC]
    assert "already upgraded today" in second.output


@pytest.mark.parametrize("args", [["-p", "ruff"], ["--no-sync"]])
def test_partial_upgrade_does_not_count_as_daily(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, args: list[str]
) -> None:
    stamp = tmp_path / "stamp"
    _record_upgrade(monkeypatch, stamp)
    result = CliRunner().invoke(manager, ["upgrade", *args])
    assert result.exit_code == 0
    assert not stamp.exists()


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
        _lint, "_lint_python", lambda *_, **_kw: calls.append("ruff") or 0
    )
    monkeypatch.setattr(_lint, "_lint_rst", lambda *_: calls.append("rst") or 0)
    monkeypatch.setattr(_lint, "_lint_docs", lambda: calls.append("docs") or 0)
    monkeypatch.setattr(
        _lint, "_lint_docstrings", lambda *_: calls.append("docstrings") or 0
    )
    monkeypatch.setattr(_lint, "_lint_terms", lambda *_: calls.append("terms") or 0)
    monkeypatch.setattr(
        _lint, "_lint_literals", lambda *_: calls.append("literals") or 0
    )
    monkeypatch.setattr(_lint, "_lint_deps", lambda: calls.append("deps") or 0)
    monkeypatch.setattr(_lint, "_lint_actions", lambda *_: calls.append("actions") or 0)
    monkeypatch.setattr(_lint, "_lint_yaml", lambda *_: calls.append("yaml") or 0)
    monkeypatch.setattr(
        _lint, "run_import_checks", lambda *_: calls.append("imports") or 0
    )
    monkeypatch.setattr(_lint, "_lint_types", lambda *_: calls.append("types") or 0)
    monkeypatch.setattr(
        _lint, "_verify_types", lambda *_: calls.append("verify-types") or 0
    )
    monkeypatch.setattr(_lint, "_twine_check", lambda: calls.append("dist") or 0)
    monkeypatch.setattr(
        _lint, "_lint_python_strict", lambda *_: calls.append("strict") or 0
    )


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ([], ["ruff"]),
        (["--rst", "--yaml"], ["rst", "yaml"]),
        (
            ["--all"],
            [
                "ruff",
                "rst",
                "docs",
                "docstrings",
                "terms",
                "literals",
                "deps",
                "actions",
                "yaml",
                "imports",
            ],
        ),
        (["--terms", "--literals", "--deps"], ["terms", "literals", "deps"]),
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


@pytest.mark.parametrize(("script", "target"), sorted(SCRIPTS.items()))
def test_console_script_target_resolves(script: str, target: str) -> None:
    """
    Checks every console script names an importable callable.

    A script pointing at a renamed module installs fine but fails with
    ``ModuleNotFoundError`` when run.

    """
    module_name, attr = target.split(":")

    assert callable(getattr(import_module(module_name), attr)), script
