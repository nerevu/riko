# vim: sw=4:ts=4:expandtab
"""Provides internal tests for the manage commands, lint checks, and workflow input."""

from __future__ import annotations

import io
import json
import tomllib
from datetime import date, timedelta
from importlib import import_module
from logging import DEBUG, ERROR, INFO, WARNING, getLogger
from pathlib import Path
from textwrap import indent
from types import ModuleType
from typing import TYPE_CHECKING

import pytest
from click.testing import CliRunner

from riko.base._exceptions import InvalidArchitectureError, InvalidPipelineError
from riko.base._paths import ROOT_DIR
from riko.base._strutils import get_codegen_note
from riko.cli import (
    _codegen,
    _docs,
    _document,
    _import_commands,
    _lint,
    _test,
    _upgrade,
)
from riko.cli._docs import (
    gen_stale_path_citations,
    gen_stale_source_symbol_citations,
    gen_stale_test_citations,
    gen_stale_test_symbol_citations,
    gen_unruled_terms,
)
from riko.cli._docstyle import (
    gen_docstring_issues,
    gen_example_prose,
    summary_leads_with_output,
)
from riko.cli._document import read_document, require_workflow
from riko.cli._gen_api_surface import generate_api_surface
from riko.cli._gen_tier_index import GENERATED_HEADER, generate_tier_index
from riko.cli._gen_verbs import TableFormat, generate_verb_tables
from riko.cli._lint_basenames import BasenameIssue, gen_basename_issues
from riko.cli._lint_bindings import gen_binding_issues, gen_binding_lines
from riko.cli._lint_canonical_imports import _iter_issues as canonical_issues
from riko.cli._lint_deps import (
    gen_hook_pin_issues,
    gen_import_issues,
    gen_runtime_imports,
    get_locked_version,
)
from riko.cli._lint_escapes import get_escape_counts
from riko.cli._lint_import_architecture import (
    _validate_graph,
    load_architecture_report,
    render_architecture,
)
from riko.cli._lint_literals import gen_literal_issues
from riko.cli._lint_relative_imports import _iter_issues as relative_issues
from riko.cli._lint_terms import BannedTerm, gen_term_issues
from riko.cli._lint_tests import (
    MERGE_LINES,
    SPLIT_LINES,
    LayoutIssue,
    gen_global_bound_issues,
    gen_layout_issues,
    get_backstop,
)
from riko.cli._logging import exception_hook, resolve_log_level
from riko.cli._ratchet import build_ceiling_text, ratchet_ceiling
from riko.cli._upgrade import _pin_hooks
from riko.cli.manage import manager
from riko.cli.runpipe import run_target
from riko.definitions._workflow_definition import Workflow
from riko.runtime._compile import compile_workflow
from tests import run_python
from tests._workflows import DAG, DAG_PATH, PIPE_DEF

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator


def _if(test: str, body: str = "import a", orelse: str = "") -> str:
    tail = f"else:\n    {orelse}\n" if orelse else ""
    return f"if {test}:\n    {body}\n{tail}"


_TYPING = "[tool.riko.typing]\n"
_TODAY = date(2026, 10, 27)
_WINDOW = "\n[tool.riko.ratchet]\nstale-days = 7\n"
_FRESH = f"any = 9\nany-lowered = 2026-10-25\n{_WINDOW}"
_STALE = f"any = 9\nany-lowered = 2026-10-19\n{_WINDOW}"
_DATED = "any = 8\nany-lowered = 2026-10-27\n"
_LOWERED = f"{_DATED}{_WINDOW}"
_DATETIME = "any = 8\nany-lowered = 2026-10-01T10:00:00\n"
_UNWINDOWED = "any = 9\nany-lowered = 2026-01-01\n"
_HOLDS = "9 uses hold the ceiling of 9."
_HELD = "9 uses have held the ceiling of 9 since 2026-10-19, over 7 days; lower it."
_RECORDED = "8 uses; recorded the ceiling as 8 on 2026-10-27."

_DISCARDED = (
    " CI discards this change; run the ratchet locally and commit pyproject.toml."
)

_CI_DISCARDS = f"::warning::{_RECORDED}{_DISCARDED}"
_MODULE_EXAMPLE = '"""\nDoes.\n\n>>> 1\n1\n"""\n'
_PRIVATE_MODULE = ["private module without a public API carries a module example"]
_NO_MODULE_EXAMPLE = "private module with a public runtime API has no module example"
_TYPE_ONLY = "class Item(Protocol): ...\nclass Stream(Item): ...\n"

_ALPHA = """
class TestAlpha:
    def test_one(self): ...


class TestAsyncAlpha:
    def test_one(self): ...


class TestBeta:
    def test_two(self): ...
"""

_BACKSTOP = 30
_LADDER = "is not on the bound ladder: 1, 2, 3, 5, 8, 10, 15, 20, 30 s"
_MARK = "@pytest.mark.timeout(5)"

_ROW_MARK = (
    '@pytest.mark.parametrize("v", [pytest.param("x", marks=[pytest.mark.timeout(4)])])'
)

_DOC_READ = "tests never read tracked docs: {}; check it in manage lint --docs"
_BOUND_FRAGMENTS = ("bound ladder", "must stay below", "outlasts", "tracked docs")
_OPTIONS = "[tool.pytest.ini_options]\n"
_SHARED = "basename is shared; rename one or allowlist the pair"
_STALE_BASENAME = "allowlisted basename is no longer duplicated; remove it"
_ANY = "from typing import Any\n"
_ANY_CAST = "from typing import Any, cast\nx: Any = cast(Any, y)\n"
_UPWARD = "from riko.runtime.b import thing\n"
_GUARDED = "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    " + _UPWARD
_LOCAL = "def load():\n    " + _UPWARD + "\n    return thing\n"

_TIMEOUT_SUITE = """
import time

import pytest


@pytest.mark.timeout(0.5, method="signal")
@pytest.mark.xfail(strict=True, reason="never ends")
def test_hangs():
    time.sleep(5)


@pytest.mark.xfail(strict=True, reason="known defect")
def test_fails():
    assert False
"""

SYNC = ["uv", "sync", "--active", "--locked", "--group", "dev", "--all-extras"]
PYPROJECT = ROOT_DIR / "pyproject.toml"
SCRIPTS: dict[str, str] = tomllib.loads(PYPROJECT.read_text())["project"]["scripts"]

DISTRIBUTIONS = {
    "dateutil": ["python-dateutil"],
    "requests": ["requests"],
    "lxml": ["lxml"],
}

PYPROJECT_TOML = """
[project]
dependencies = ["python-dateutil>=2", "requests"]

[project.optional-dependencies]
xml = ["lxml>=5", "requests"]

[dependency-groups]
lint = ["types-requests"]
"""

STALE = "the index is stale; run `manage codegen --tests`"
ALPHA_ROW = "    test_alpha.py    Alpha, Beta\n"
LONG = "".join(f"class TestSubject{n:02}: ...\n" for n in range(12))

SUBJECTS = [
    ", ".join(f"Subject{n:02}" for n in range(start, start + 6)) for start in (0, 6)
]

LONG_ROWS = f"{ALPHA_ROW}    test_long.py     {SUBJECTS[0]},\n{' ' * 21}{SUBJECTS[1]}\n"
ABSOLUTE = "import a.b\nfrom c import d\nfrom . import e\n"
TRY = "try:\n    import a\nexcept ImportError:\n    pass\n"
REQUESTS = "import requests\n"

ONLY = (
    "'python-dateutil' is a [project] dependency that nothing imports at run time; "
    "import it outside TYPE_CHECKING or move it to a dependency group"
)

LXML = "import lxml\n"

LOCK = """
[[package]]
name = "ruff"
version = "0.16.10"
"""

HOOKS = """
repos:
  - repo: local
    hooks:
      - id: ruff-check
        additional_dependencies: [ruff==0.16.10]
      - id: ruff-format
        additional_dependencies: [ruff==0.16.9]
"""

WORKFLOW = json.loads(Workflow.parse(DAG).serialize())
TC, NOT_TC = "TYPE_CHECKING", "not TYPE_CHECKING"
LOCAL = "def f():\n" + indent(_if(TC) + "import b\n", "    ")
ELIF = _if(TC, "pass") + "elif flag:\n    import a\n"


def write(root: Path, path: str, text: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)


def _record(calls: list[str], name: str, code: int = 0) -> Callable[[], int]:
    def runner() -> int:
        calls.append(name)
        return code

    return runner


class TestCodegenCommand:
    """The ``manage codegen`` selectors."""

    @pytest.mark.parametrize(
        ("args", "expected"),
        [
            ([], ["config"]),
            (["--names", "--api"], ["names", "api"]),
            (["--tests", "--verbs"], ["tests", "verbs"]),
            (["--all"], ["config", "names", "api", "tests", "verbs"]),
        ],
    )
    def test_codegen_selectors(
        self, monkeypatch: pytest.MonkeyPatch, args: list[str], expected: list[str]
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

    def test_codegen_mode_is_removed(self) -> None:
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


class TestUpgradeCommand:
    """The ``manage upgrade`` lock, sync, and daily stamp."""

    @pytest.mark.parametrize(
        ("args", "expected"),
        [
            ([], [["uv", "lock", "--upgrade"], SYNC]),
            (
                ["-p", "ruff", "--package", "pyright"],
                [
                    [
                        "uv",
                        "lock",
                        "--upgrade-package=ruff",
                        "--upgrade-package=pyright",
                    ],
                    SYNC,
                ],
            ),
            (["--no-sync"], [["uv", "lock", "--upgrade"]]),
        ],
    )
    def test_upgrade_locks_then_syncs(
        self,
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
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        stamp = tmp_path / "stamp"
        calls = _record_upgrade(monkeypatch, stamp, lock_code=1)
        result = CliRunner().invoke(manager, ["upgrade"])
        assert result.exit_code == 1
        assert calls == [["uv", "lock", "--upgrade"]]
        assert not stamp.exists()

    def test_upgrade_daily_runs_once_per_day(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
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
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, args: list[str]
    ) -> None:
        stamp = tmp_path / "stamp"
        _record_upgrade(monkeypatch, stamp)
        result = CliRunner().invoke(manager, ["upgrade", *args])
        assert result.exit_code == 0
        assert not stamp.exists()


def _record_path(calls: list[str], name: str, code: int = 0) -> Callable[[Path], int]:
    def runner(_: Path) -> int:
        calls.append(name)
        return code

    return runner


class TestImportsCommand:
    """The ``manage lint imports`` selectors."""

    @pytest.mark.parametrize(
        ("args", "failing", "expected", "exit_code"),
        [
            pytest.param([], (), ["canonical"], 0, id="default"),
            pytest.param(
                ["--relative", "--architecture"],
                (),
                ["relative", "architecture"],
                0,
                id="additive",
            ),
            pytest.param(
                ["--all"],
                ("canonical",),
                ["canonical", "relative", "architecture"],
                1,
                id="all-continues-past-a-failure",
            ),
        ],
    )
    def test_import_selectors(
        self,
        monkeypatch: pytest.MonkeyPatch,
        args: list[str],
        failing: tuple[str, ...],
        expected: list[str],
        exit_code: int,
    ) -> None:
        calls: list[str] = []
        names = ("canonical", "relative", "architecture")
        checks = {
            name: _record_path(calls, name, int(name in failing)) for name in names
        }
        monkeypatch.setattr(_import_commands, "_IMPORT_CHECKS", checks)

        result = CliRunner().invoke(_import_commands.IMPORTS_COMMAND, args)
        assert result.exit_code == exit_code
        assert calls == expected

    def test_imports_is_nested_under_lint(self) -> None:
        runner = CliRunner()
        nested = runner.invoke(manager, ["lint", "imports", "--help"])
        top_level = runner.invoke(manager, ["imports", "--help"])

        assert nested.exit_code == 0
        assert "--architecture" in nested.output
        assert top_level.exit_code == 2


def _patch_lints(monkeypatch: pytest.MonkeyPatch, calls: list[str]) -> None:
    monkeypatch.setattr(
        _lint, "_lint_python", lambda *_, **_kw: calls.append("ruff") or 0
    )
    monkeypatch.setattr(_lint, "lint_rst", lambda *_: calls.append("rst") or 0)
    monkeypatch.setattr(_lint, "lint_docs", lambda: calls.append("docs") or 0)
    monkeypatch.setattr(
        _lint, "_lint_docstrings", lambda *_: calls.append("docstrings") or 0
    )
    monkeypatch.setattr(_lint, "_lint_terms", lambda *_: calls.append("terms") or 0)
    monkeypatch.setattr(
        _lint, "_lint_literals", lambda *_: calls.append("literals") or 0
    )
    monkeypatch.setattr(_lint, "_lint_deps", lambda: calls.append("deps") or 0)
    monkeypatch.setattr(
        _lint, "_lint_bindings", lambda *_: calls.append("bindings") or 0
    )
    monkeypatch.setattr(_lint, "_lint_tests", lambda: calls.append("tests") or 0)
    monkeypatch.setattr(_lint, "_lint_actions", lambda *_: calls.append("actions") or 0)
    monkeypatch.setattr(_lint, "_lint_yaml", lambda *_: calls.append("yaml") or 0)
    monkeypatch.setattr(
        _lint, "run_import_checks", lambda *_: calls.append("imports") or 0
    )
    monkeypatch.setattr(_lint, "_lint_types", lambda *_: calls.append("types") or 0)
    monkeypatch.setattr(
        _lint, "_verify_types", lambda *_: calls.append("verify-types") or 0
    )
    monkeypatch.setattr(_lint, "twine_check", lambda: calls.append("dist") or 0)
    monkeypatch.setattr(
        _lint, "_lint_python_strict", lambda *_: calls.append("strict") or 0
    )


class TestLintCommand:
    """The ``manage lint`` selectors."""

    @pytest.mark.parametrize(
        ("check", "text"),
        [
            pytest.param(_lint._lint_terms, "Run a sub-pipeline.\n", id="terms"),
            pytest.param(
                _lint._lint_literals, "Pass ``'list'`` here.\n", id="literals"
            ),
        ],
    )
    def test_text_checks_exit_by_whether_issues_were_found(
        self, tmp_path: Path, capsys, check, text: str
    ) -> None:
        clean, flagged = tmp_path / "CLEAN.rst", tmp_path / "GUIDE.rst"
        clean.write_text("Nothing to see.\n", encoding="utf-8")
        flagged.write_text(text, encoding="utf-8")

        assert check(str(clean)) == 0
        assert check(str(flagged)) == 1
        assert "GUIDE.rst" in capsys.readouterr().out

    def test_dependency_check_exits_by_whether_issues_were_found(
        self, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        codes = {"deptry": 0}
        monkeypatch.setattr(_lint, "_deptry", "deptry")
        monkeypatch.setattr(_lint, "call", lambda args, **_: codes[args[0]])
        monkeypatch.setattr(_lint, "gen_import_issues", lambda *_: [])
        monkeypatch.setattr(_lint, "gen_hook_pin_issues", lambda *_: [])
        assert _lint._lint_deps() == 0

        codes["deptry"] = 1
        assert _lint._lint_deps() == 1

        codes["deptry"] = 0
        monkeypatch.setattr(_lint, "gen_hook_pin_issues", lambda *_: ["stale pin"])
        assert _lint._lint_deps() == 1
        assert "stale pin" in capsys.readouterr().out

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
                    "bindings",
                    "tests",
                    "actions",
                    "yaml",
                    "imports",
                ],
            ),
            (
                ["--terms", "--literals", "--deps", "--bindings", "--tests"],
                ["terms", "literals", "deps", "bindings", "tests"],
            ),
            (["--check-types", "--strict"], ["types", "strict"]),
        ],
    )
    def test_lint_selectors(
        self, monkeypatch: pytest.MonkeyPatch, args: list[str], expected: list[str]
    ) -> None:
        calls: list[str] = []
        _patch_lints(monkeypatch, calls)

        result = CliRunner().invoke(_lint.LINT_COMMAND, args)

        assert result.exit_code == 0
        assert calls == expected


def _coverage_report(root: Path, uncovered: int) -> Path:
    report = root / "coverage.json"
    report.write_text(json.dumps({"totals": {"missing_lines": uncovered}}))
    return report


PARTIAL_RATCHET_CASES = [
    pytest.param(["tests/public"], id="paths"),
    pytest.param(["--tox"], id="tox"),
    pytest.param(["--failed"], id="failed"),
]


class TestCoverageRatchet:
    """The ``manage test --ratchet`` uncovered-line ceiling."""

    @pytest.mark.parametrize(
        ("recorded", "uncovered", "code", "ceiling"),
        [
            pytest.param(1249, 1240, 0, "uncovered = 1240", id="gain-lowers"),
            pytest.param(1249, 1249, 0, "uncovered = 1249", id="equal-holds"),
            pytest.param(1249, 1250, 1, "uncovered = 1249", id="loss-fails"),
            pytest.param(None, 1250, 0, "uncovered = 1250", id="first-run-records"),
        ],
    )
    def test_ratchet_holds_or_lowers_the_ceiling(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        recorded: int | None,
        uncovered: int,
        code: int,
        ceiling: str,
    ) -> None:
        pyproject = tmp_path / "pyproject.toml"
        table = (
            ""
            if recorded is None
            else f"[tool.riko.coverage]\nuncovered = {recorded}\n"
        )
        pyproject.write_text(f"[project]\nname = 'x'\n{table}")
        monkeypatch.setattr(_test, "ROOT_DIR", tmp_path)

        assert _test._ratchet_coverage(_coverage_report(tmp_path, uncovered)) == code
        assert ceiling in pyproject.read_text()

    @pytest.mark.parametrize(
        ("args", "present", "absent"),
        [
            pytest.param(["-q"], "--cov=riko", "--cov-report", id="default"),
            pytest.param(["-q", "--no-cov"], "--no-cov", "--cov-report", id="no-cov"),
            pytest.param(["-q", "--ratchet"], "--cov-report=json:", "", id="ratchet"),
        ],
    )
    def test_command_passes_coverage_options_to_pytest(
        self,
        monkeypatch: pytest.MonkeyPatch,
        args: list[str],
        present: str,
        absent: str,
    ) -> None:
        calls: list[tuple[list[str], dict[str, str] | None]] = []
        monkeypatch.setattr(_test, "_pytest", "pytest")
        monkeypatch.setattr(
            _test, "check_call", lambda cmd, env=None: calls.append((cmd, env))
        )
        monkeypatch.setattr(_test, "_ratchet_coverage", lambda _: 0)

        result = CliRunner().invoke(_test.TEST_COMMAND, args)
        cmd, env = calls[0]
        command = " ".join(cmd)
        report = command.partition("--cov-report=json:")[2].partition(" ")[0]
        data_file = None if env is None else env["COVERAGE_FILE"]
        expected = str(Path(report).with_name(".coverage")) if report else None
        assert result.exit_code == 0
        assert present in command
        assert not absent or absent not in command
        assert data_file == expected

    @pytest.mark.parametrize("args", PARTIAL_RATCHET_CASES)
    def test_ratchet_refuses_a_partial_run(
        self, monkeypatch: pytest.MonkeyPatch, args: list[str]
    ) -> None:
        folders: list[str] = []
        monkeypatch.setattr(_test, "mkdtemp", lambda: folders.append("made") or "")

        result = CliRunner().invoke(_test.TEST_COMMAND, ["--ratchet", *args])
        assert result.exit_code == 2
        assert "measures the whole suite" in result.output
        assert folders == []


CEILING_TEXT_CASES = [
    pytest.param("x = 1\n", "x = 1\n\n[tool.riko.typing]\nany = 4\n", id="no-table"),
    pytest.param(f"{_TYPING}cast = 1\n", f"{_TYPING}any = 4\ncast = 1\n", id="no-key"),
    pytest.param(f"{_TYPING}any = 9\n", f"{_TYPING}any = 4\n", id="rewrite"),
    pytest.param(
        f"{_TYPING}any = 9  # note\n",
        f"{_TYPING}any = 4  # note\n",
        id="inline-comment",
    ),
    pytest.param(
        f"[tool.riko.coverage]\nany = 1\n\n{_TYPING}any = 9\n",
        f"[tool.riko.coverage]\nany = 1\n\n{_TYPING}any = 4\n",
        id="other-table-kept",
    ),
]


STALE_CASES = [
    pytest.param(_FRESH, 9, False, _FRESH, _HOLDS, id="fresh"),
    pytest.param(_STALE, 9, False, _STALE, f"Warning: {_HELD}", id="stale"),
    pytest.param(_STALE, 9, True, _STALE, f"::warning::{_HELD}", id="stale-ci"),
    pytest.param(_STALE, 8, False, _LOWERED, _RECORDED, id="lowering-resets"),
    pytest.param(_STALE, 8, True, _LOWERED, _CI_DISCARDS, id="ci-discards"),
    pytest.param("any = 8\n", 8, False, _DATED, _RECORDED, id="undated-starts-clock"),
    pytest.param(_DATETIME, 8, False, _DATED, _RECORDED, id="datetime-restarts-clock"),
    pytest.param(_UNWINDOWED, 9, False, _UNWINDOWED, _HOLDS, id="no-window"),
]


class TestCeilingRatchet:
    """The shared ``pyproject.toml`` ceiling a ratchet records."""

    @pytest.mark.parametrize(("text", "expected"), CEILING_TEXT_CASES)
    def test_ceiling_text_sets_only_the_named_key(
        self, text: str, expected: str
    ) -> None:
        assert build_ceiling_text(text, "typing", "any", 4) == expected

    @pytest.mark.parametrize(("text", "count", "ci", "expected", "report"), STALE_CASES)
    def test_ratchet_reports_ceiling_age(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        text: str,
        count: int,
        ci: bool,
        expected: str,
        report: str,
    ) -> None:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(f"{_TYPING}{text}")
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)

        if ci:
            monkeypatch.setenv("GITHUB_ACTIONS", "true")

        code = ratchet_ceiling(pyproject, "typing", "any", count, "uses", today=_TODAY)
        assert code == 0
        assert pyproject.read_text() == f"{_TYPING}{expected}"
        assert capsys.readouterr().out == f"{report}\n"


class TestConsoleScripts:
    """Every console script names an importable callable."""

    @pytest.mark.parametrize(("script", "target"), sorted(SCRIPTS.items()))
    def test_console_script_target_resolves(self, script: str, target: str) -> None:
        """
        Checks every console script names an importable callable.

        A script pointing at a renamed module installs fine but fails with
        ``ModuleNotFoundError`` when run.

        """
        module_name, attr = target.split(":")

        assert callable(getattr(import_module(module_name), attr)), script


EXAMPLE_PROSE = [
    pytest.param(">>> a\n1\n\nWith b:\n\n>>> b\n2", ["With b:"], id="narration"),
    pytest.param(">>> a\n1\n\nWith b\nand c:\n\n>>> b", ["With b"], id="multi-line"),
    pytest.param(">>> a\n1\n\n>>> # With b\n>>> b\n2", [], id="comment"),
    pytest.param(">>> a\n1\n\nAsync usage::\n\n>>> b", [], id="labelled-group"),
    pytest.param("Calls a.\n\n>>> a\n1", [], id="before-examples"),
    pytest.param(">>> a\n1\n\nRaises:\n\n    TypeError: x.", [], id="section"),
]


def _doctest(source: str) -> str:
    return f'def f():\n    """\n    Runs.\n\n    >>> {source}\n    """\n'


EXAMPLE_RULES = [
    pytest.param(
        "mod.py",
        _doctest("from riko.runtime._pipeline import Pipeline"),
        ['imports Pipeline privately (use "from riko import Pipeline")'],
        id="stable-name",
    ),
    pytest.param(
        "mod.py",
        _doctest("from riko.modules._decorators import processor"),
        ['imports processor privately (use "from riko.ext import processor")'],
        id="extension-name",
    ),
    pytest.param(
        "mod.py", _doctest("from riko.cli._docstyle import f"), [], id="nopub"
    ),
    pytest.param("mod.py", _doctest("from riko import Pipeline"), [], id="public"),
    pytest.param("_mod.py", _MODULE_EXAMPLE, _PRIVATE_MODULE, id="private-module"),
    pytest.param("_mod.py", f"{_MODULE_EXAMPLE}class Pipeline: ...\n", [], id="api"),
    pytest.param("mod.py", _MODULE_EXAMPLE, [], id="public-module"),
    pytest.param(
        "_mod.py", "def export(): ...\n", [_NO_MODULE_EXAMPLE], id="no-example"
    ),
    pytest.param("_mod.py", _TYPE_ONLY, [], id="type-only"),
    pytest.param("_mod.py", "class RikoError(Exception): ...\n", [], id="exception"),
    pytest.param("mod.py", "def export(): ...\n", [], id="public-no-example"),
    pytest.param(
        "mod.py",
        'def _build_x():\n    """Resolves x."""\n',
        ["summary verb does not match the name verb build"],
        id="verb-mismatch",
    ),
    pytest.param(
        "mod.py",
        'async def _abuild_x():\n    """Resolves x."""\n',
        ["summary verb does not match the name verb build"],
        id="verb-mismatch-twin",
    ),
    pytest.param(
        "mod.py", 'async def abuild_x():\n    """Builds x."""\n', [], id="verb-twin"
    ),
    pytest.param(
        "mod.py", 'def build_x():\n    """Finds x."""\n', [], id="verb-off-table"
    ),
    pytest.param(
        "_require_guards.py",
        'def require_from_keys():\n    """Builds x."""\n',
        [],
        id="compound",
    ),
]


class TestDocstyle:
    """Docstring summary and example-prose checks."""

    @pytest.mark.parametrize(("doc", "expected"), EXAMPLE_PROSE)
    def test_example_prose_detection(self, doc: str, expected: list[str]) -> None:
        assert list(gen_example_prose(doc)) == expected

    @pytest.mark.parametrize(("name", "source", "expected"), EXAMPLE_RULES)
    def test_example_import_and_module_example_rules(
        self, tmp_path: Path, name: str, source: str, expected: list[str]
    ) -> None:
        path = tmp_path / name
        path.write_text(source, encoding="utf-8")
        assert [issue.problem for issue in gen_docstring_issues(path)] == expected

    def test_docstring_summary_output_lead_detection(self) -> None:
        assert summary_leads_with_output("Returns the parsed response body.")
        assert not summary_leads_with_output("Parses the response body.")


VERB_TABLE_MARKERS = [
    pytest.param("md", "<!-- verbs -->\n<!-- /verbs -->", "| `load` |", id="md"),
    pytest.param("rst", ".. begin verbs\n.. end verbs", "| ``load`` ", id="rst"),
]


class TestVerbTables:
    """Generated function-name verb tables."""

    @pytest.mark.parametrize(("fmt", "text", "row"), VERB_TABLE_MARKERS)
    def test_generation_is_idempotent(
        self, fmt: TableFormat, text: str, row: str
    ) -> None:
        generated = generate_verb_tables(text, fmt)
        assert row in generated
        assert get_codegen_note("--verbs") in generated.splitlines()[0]
        assert generate_verb_tables(generated, fmt) == generated


class TestGenerateApiSurface:
    """The generated name blocks in the API-surface reference."""

    def test_generation_names_its_command_and_is_idempotent(self) -> None:
        text = "<!-- api-surface:export -->\n\n<!-- /api-surface:export -->"
        generated = generate_api_surface(text)
        assert get_codegen_note("--api") in generated.splitlines()[0]
        assert "'export'" in generated
        assert generate_api_surface(generated) == generated


CITATION_SCANS = [
    pytest.param(
        gen_stale_test_citations,
        "public/test_{}.py",
        "tests/public/test_kept.py",
        id="tests",
    ),
    pytest.param(gen_stale_path_citations, "riko/{}.py", "riko/kept.py", id="paths"),
    pytest.param(
        gen_stale_test_symbol_citations,
        "TestKept::test_{}",
        "TestKept::test_kept",
        id="symbols",
    ),
]


class TestCitationLint:
    """The stale test-file and source-file citation checks."""

    @pytest.mark.parametrize(("scan", "template", "kept"), CITATION_SCANS)
    def test_every_document_is_checked_against_the_known_files(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        scan: Callable[[str, Iterable[str]], Iterator[tuple[int, str]]],
        template: str,
        kept: str,
    ) -> None:
        monkeypatch.setattr(_docs, "ROOT_DIR", tmp_path)
        gone = template.format("gone")
        paths = (tmp_path / "a.md", tmp_path / "b.md")

        for path in paths:
            text = f"See `{template.format('kept')}` and `{gone}`.\n"
            path.write_text(text, encoding="utf-8")

        known = (name for name in (kept,))
        offenders = _docs._gen_citation_offenders(scan, known, *paths)
        assert list(offenders) == [f"a.md:1: {gone}", f"b.md:1: {gone}"]

    def test_test_symbols_cover_files_classes_and_tests(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(_docs, "ROOT_DIR", tmp_path)
        path = tmp_path / "tests" / "public" / "test_alpha.py"
        path.parent.mkdir(parents=True)
        path.write_text("class TestAlpha:\n    def test_one(self): ...\n")
        rel = "tests/public/test_alpha.py"
        expected = [rel, f"{rel}::TestAlpha", f"{rel}::TestAlpha::test_one"]
        assert list(_docs.gen_test_symbols(path)) == [*expected, "TestAlpha::test_one"]

    def test_source_symbol_pairs_check_both_names_with_the_class_prefix(self) -> None:
        path = "riko/x.py"
        known = (path, f"{path}::C", f"{path}::C.y")
        text = f"`C.x()`/`y()` (`{path}`), `C.y`/`z` (`{path}`)"
        stale = [f"{path}::C.x", f"{path}::C.z"]
        assert [
            key for _, key in gen_stale_source_symbol_citations(text, known)
        ] == stale

    def test_source_symbols_cover_bindings_in_every_scope_shape(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(_docs, "ROOT_DIR", tmp_path)
        path = tmp_path / "riko" / "alpha.py"
        path.parent.mkdir()
        source = (
            "import os.path as osp\n"
            "if TYPE:\n    from x import Y\n"
            "try:\n    import z\nexcept ImportError:\n    w = None\n"
            "type Alias = int\nCONST: int = 1\na, b = 1, 2\n"
            "class C:\n    attr = 1\n    def method(self): ...\n"
            "def func():\n    local = 1\n"
        )
        path.write_text(source)
        names = ("osp", "Y", "z", "w", "Alias", "CONST", "a", "b", "C", "func")
        members = ("C.attr", "C.method")
        expected = {"riko/alpha.py", *(f"riko/alpha.py::{n}" for n in names + members)}
        assert set(_docs.gen_source_symbols(path)) == expected


TERM_PATTERNS = [
    pytest.param(
        'REASON = "owned by R5C: write is still a sink module"\n'
        "# see R4B.2 and P10, not R2D2 or PR9\n",
        [(1, "R5C"), (2, "R4B.2"), (2, "P10")],
        id="phase-codes",
    ),
    pytest.param(
        "# scope the run with open(), or Scopes a run\n"
        "# open it to scope one; scope a run's resources is fine\n",
        [(1, "scope the run"), (1, "Scopes a run"), (2, "open it to scope")],
        id="run-scoping",
    ),
    pytest.param(
        "# import from riko.ext.registry, not riko.ext.modules\n"
        "# riko.ext.names is gone too\n",
        [(1, "riko.ext.registry"), (2, "riko.ext.names")],
        id="removed-ext-paths",
    ),
    pytest.param(
        "# it pulls its upstream, then its upstream node runs\n"
        "# a suspended upstream; their upstream reader reads upstream\n",
        [(1, "its upstream"), (2, "a suspended upstream")],
        id="upstream-nouns",
    ),
]


class TestTermLint:
    """The reserved-terms lint check."""

    def test_a_missing_reserved_terms_section_rules_on_nothing(self) -> None:
        text = "## Voice\n\nSay sync for `Other Mode`.\n"
        terms = (BannedTerm("other mode", "sync"), BannedTerm("cross-mode", "sync"))
        assert list(gen_unruled_terms(text, *terms)) == ["other mode", "cross-mode"]

    def test_python_strings_and_comments_are_checked_but_code_is_not(
        self, tmp_path: Path
    ) -> None:
        source = tmp_path / "mod.py"
        source.write_text(
            "cross_mode = 1  # a cross-mode bridge\n"
            'MESSAGE = "two Execution Contexts"\n'
            "def other_mode(): ...\n"
            'ERROR = f"{ref} in the other mode"\n',
            encoding="utf-8",
        )
        found = [(issue.lineno, issue.found) for issue in gen_term_issues(source)]
        assert found == [
            (1, "cross-mode"),
            (2, "Execution Contexts"),
            (4, "other mode"),
        ]

    @pytest.mark.parametrize(("text", "expected"), TERM_PATTERNS)
    def test_patterns_are_checked(
        self, tmp_path: Path, text: str, expected: list[tuple[int, str]]
    ) -> None:
        source = tmp_path / "mod.py"
        source.write_text(text, encoding="utf-8")
        found = [(issue.lineno, issue.found) for issue in gen_term_issues(source)]
        assert found == expected

    def test_phrases_split_across_lines_are_checked(self, tmp_path: Path) -> None:
        (tmp_path / "GUIDE.md").write_text(
            "Intro.\n\nA node with bound\nkeywords and a\nsub-pipeline.\n",
            encoding="utf-8",
        )
        (tmp_path / "mod.py").write_text(
            '"""\nSummary.\n\nRuns in the other\n    mode.\n"""\n', encoding="utf-8"
        )
        found = [(issue.path.name, issue.lineno) for issue in gen_term_issues(tmp_path)]
        assert found == [("GUIDE.md", 3), ("GUIDE.md", 5), ("mod.py", 4)]

    def test_prose_files_are_checked_except_the_migration_guide(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "GUIDE.rst").write_text("Run a sub-pipeline.\n", encoding="utf-8")
        (tmp_path / "CHANGES.rst").write_text("Run a sub-pipeline.\n", encoding="utf-8")
        (tmp_path / "MIGRATION.rst").write_text(
            "Run a sub-pipeline.\n", encoding="utf-8"
        )
        found = [issue.path.name for issue in gen_term_issues(tmp_path)]
        assert found == ["CHANGES.rst", "GUIDE.rst"]


class TestLiteralLint:
    """The inline-literal quoting lint check."""

    def test_python_strings_and_comments_are_checked_but_code_is_not(
        self, tmp_path: Path
    ) -> None:
        source = tmp_path / "mod.py"
        source.write_text(
            "fmt = 'list'  # fmt may be ``'list'``\n"
            '"""field (str): Item field (default: ``"content"``)."""\n'
            "def f(x=\"``'x'``\"): ...\n",
            encoding="utf-8",
        )
        found = [(issue.lineno, issue.found) for issue in gen_literal_issues(source)]
        assert found == [
            (1, "``'list'``"),
            (2, '(default: ``"content"``'),
            (3, "``'x'``"),
        ]

    def test_plain_defaults_constant_names_and_double_quotes_pass(
        self, tmp_path: Path
    ) -> None:
        source = tmp_path / "mod.py"
        source.write_text(
            '"""\n'
            'field (str): Item field (default: "content").\n'
            "limit: Maximum calls (default: ``DEF_CONCURRENCY_LIMIT``).\n"
            'executor: One of ``"thread"`` or ``"process"``; yields ``""``.\n'
            '"""\n',
            encoding="utf-8",
        )
        assert list(gen_literal_issues(source)) == []

    def test_bare_string_defaults_are_flagged_only_for_string_signature_defaults(
        self, tmp_path: Path
    ) -> None:
        source = tmp_path / "mod.py"
        source.write_text(
            "def f(a='content', b=None, *, c='x', d=3):\n"
            '    """\n'
            "    Args:\n"
            "        a: The field (default: content).\n"
            "        b: The other field (default: content).\n"
            "    Kwargs:\n"
            "        c: A key (default: x).\n"
            "        d: A count (default: 3).\n"
            '    """\n',
            encoding="utf-8",
        )
        found = [(issue.lineno, issue.found) for issue in gen_literal_issues(source)]
        assert found == [(4, "(default: content)"), (7, "(default: x)")]

    def test_prose_files_are_checked_including_the_changelog(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "GUIDE.rst").write_text("Set ``'auto'``.\n", encoding="utf-8")
        (tmp_path / "CHANGES.rst").write_text("Set ``'auto'``.\n", encoding="utf-8")
        found = [issue.path.name for issue in gen_literal_issues(tmp_path)]
        assert found == ["CHANGES.rst", "GUIDE.rst"]


BINDING_CASES = [
    pytest.param("def f(workflow: Workflow): ...\n", [1], id="param"),
    pytest.param("def f(workflow: WorkflowLike | None): ...\n", [1], id="like-param"),
    pytest.param("def f(workflow: RawWorkflow): ...\n", [], id="raw-param"),
    pytest.param("workflow = Workflow.parse(dag)\n", [1], id="parsed-local"),
    pytest.param("workflow = pipeline.workflow\n", [1], id="attribute-local"),
    pytest.param("workflow = load(dag)\n", [], id="unknown-call"),
    pytest.param(
        "def build() -> Workflow: ...\nworkflow = build()\n", [2], id="helper-local"
    ),
    pytest.param("class P:\n    workflow: Workflow = field()\n", [], id="field"),
    pytest.param("evolve(self, workflow=flow)\n", [], id="keyword"),
    pytest.param(
        "class P:\n    workflow: Workflow\n"
        "    def replace(self, *, workflow: Workflow | None = None): ...\n",
        [],
        id="field-keyword",
    ),
    pytest.param(
        "class P:\n    flow: Workflow\n"
        "    def replace(self, *, workflow: Workflow | None = None): ...\n",
        [3],
        id="non-field-keyword",
    ),
    pytest.param(
        "class P:\n    workflow: Workflow\n"
        "    def replace(self, workflow: Workflow): ...\n",
        [3],
        id="positional-field-name",
    ),
    pytest.param("def from_workflow(cls, flow: Workflow): ...\n", [], id="method"),
    pytest.param(
        'def f():\n    """\n    >>> workflow = Workflow(nodes=[])\n    """\n',
        [3],
        id="doctest",
    ),
]


class TestBindingLint:
    """The ``Workflow`` binding-name lint check."""

    @pytest.mark.parametrize(("source", "expected"), BINDING_CASES)
    def test_workflow_values_bound_as_workflow_are_flagged(
        self, source: str, expected: list[int]
    ) -> None:
        assert list(gen_binding_lines(source)) == expected

    def test_check_exits_by_whether_issues_were_found(
        self, tmp_path: Path, capsys
    ) -> None:
        clean, flagged = tmp_path / "clean.py", tmp_path / "flagged.py"
        clean.write_text("flow = Workflow()\n", encoding="utf-8")
        flagged.write_text("workflow = Workflow()\n", encoding="utf-8")

        assert _lint._lint_bindings(str(clean)) == 0
        assert _lint._lint_bindings(str(flagged)) == 1
        assert "flagged.py:1" in capsys.readouterr().out

    def test_prose_doctests_are_checked_from_a_file_or_directory_root(
        self, tmp_path: Path
    ) -> None:
        guide = tmp_path / "GUIDE.rst"
        guide.write_text(
            "Parse it::\n\n    >>> workflow = Workflow.parse(dag)\n"
            "    >>> flow = Workflow.parse(dag)\n",
            encoding="utf-8",
        )
        (tmp_path / "NOTES.md").write_text("workflow = Workflow()\n", encoding="utf-8")
        found = [(issue.path.name, issue.lineno) for issue in gen_binding_issues(guide)]
        assert found == [("GUIDE.rst", 3)]
        assert [issue.path.name for issue in gen_binding_issues(tmp_path)] == [
            "GUIDE.rst"
        ]


def _write_suite(root: Path, **files: str) -> Path:
    tests_dir = root / "tests"
    tier = tests_dir / "public"
    tier.mkdir(parents=True)
    init = tier / "__init__.py"
    (tier / "test_alpha.py").write_text(_ALPHA + "\n" * MERGE_LINES, encoding="utf-8")
    init.write_text(generate_tier_index(tier), encoding="utf-8")

    for name, text in files.items():
        path = tests_dir / name.replace("__", "/")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    return tests_dir


TIER_INDEX_CASES = [
    pytest.param(None, ALPHA_ROW, id="twin-collapses"),
    pytest.param(LONG, LONG_ROWS, id="wraps-under-column"),
    pytest.param(
        "class TestAsyncGamma: ...\n",
        f"{ALPHA_ROW}    test_long.py     AsyncGamma\n",
        id="lone-async-kept",
    ),
    pytest.param(
        "def helper(): ...\n", f"{ALPHA_ROW}    test_long.py\n", id="no-subjects"
    ),
]


class TestTierIndexCodegen:
    """The generated test tier index."""

    @pytest.mark.parametrize(("source", "rows"), TIER_INDEX_CASES)
    def test_index_rows_come_from_subject_classes(
        self, tmp_path: Path, source: str | None, rows: str
    ) -> None:
        tier = _write_suite(tmp_path) / "public"

        if source is not None:
            (tier / "test_long.py").write_text(source, encoding="utf-8")

        generated = generate_tier_index(tier)
        assert generated.split("order):\n\n")[1] == f'{rows}"""\n'

    def test_regenerating_a_current_index_changes_nothing(self, tmp_path: Path) -> None:
        tier = _write_suite(tmp_path) / "public"
        text = (tier / "__init__.py").read_text(encoding="utf-8")
        assert generate_tier_index(tier) == text

    def test_a_folder_outside_the_tiers_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="'other' is not a test tier"):
            generate_tier_index(tmp_path / "other")

    def test_the_file_starts_with_the_generated_header(self, tmp_path: Path) -> None:
        tier = _write_suite(tmp_path) / "public"
        assert generate_tier_index(tier).startswith(f'{GENERATED_HEADER}\n\n"""\n')


INDEX_FORMS = [
    pytest.param(f"{GENERATED_HEADER}\n", "", [STALE], id="header-removed"),
    pytest.param("Alpha, Beta\n", "Alpha\n", [STALE], id="hand-edited"),
    pytest.param("", "", [], id="current"),
]


def _messages(tests_dir: Path) -> list[tuple[str, bool]]:
    issues = gen_layout_issues(tests_dir, _BACKSTOP)
    return [(issue.message, issue.fatal) for issue in issues]


def _case(body: str, marker: str = "", prefix: str = "") -> str:
    method = f"    {marker}\n    def test_one(self):\n        {body}\n"
    return f"\n{prefix}\nclass TestGamma:\n{method}"


BOUND_CASES = [
    pytest.param(
        _case("...", "@pytest.mark.timeout(4)"),
        f"timeout(4) {_LADDER}",
        id="off-ladder-marker",
    ),
    pytest.param(
        _case("with fail_after(0.5): ..."),
        f"fail_after(0.5) {_LADDER}",
        id="off-ladder-inner",
    ),
    pytest.param(
        _case("with fail_after(5): ...", _MARK),
        "fail_after(5) must stay below its timeout marker (5 s)",
        id="inner-at-marker",
    ),
    pytest.param(
        _case("with fail_after(30): ..."),
        "fail_after(30) must stay below its pyproject timeout (30 s)",
        id="inner-at-global",
    ),
    pytest.param(
        _case("event.wait(timeout=0.5)"),
        f"wait(timeout=0.5) {_LADDER}",
        id="keyword-bound",
    ),
    pytest.param(
        _case("thread.join(0.5)"), f"join(0.5) {_LADDER}", id="positional-bound"
    ),
    pytest.param(_case("...", _ROW_MARK), f"timeout(4) {_LADDER}", id="row-marker"),
    pytest.param(
        _case("with fail_after(_BOUND): ...", prefix="_BOUND = 4"),
        f"fail_after(_BOUND) {_LADDER}",
        id="module-constant",
    ),
    pytest.param(
        _case("sleep(5)", _MARK),
        "sleep(5) outlasts its timeout marker (5 s); "
        "the test can end only by its backstop",
        id="own-path-sleep",
    ),
    pytest.param(
        _case('ROOT_DIR / "_docs" / "X.md"'),
        _DOC_READ.format("ROOT_DIR / '_docs' / 'X.md'"),
        id="docs-chain",
    ),
    pytest.param(
        _case('DOCS_DIR / "FAQ.rst"'),
        _DOC_READ.format("DOCS_DIR / 'FAQ.rst'"),
        id="docs-dir",
    ),
    pytest.param(
        _case('Path("README.rst")'),
        _DOC_READ.format("Path('README.rst')"),
        id="cwd-doc",
    ),
]
CLEAN_BOUND_CASES = [
    pytest.param(
        _case("async def block(): await async_sleep(3600)", _MARK), id="nested-sleep"
    ),
    pytest.param(_case("AsyncExecution(shutdown_timeout=0.05)"), id="subject-timeout"),
    pytest.param(_case("with fail_after(delay): ..."), id="non-literal"),
    pytest.param(_case("event.wait()"), id="no-argument"),
    pytest.param(_case("thread.join(x)"), id="non-literal-positional"),
    pytest.param(_case("...", "@pytest.mark.timeout(T)"), id="non-literal-marker"),
    pytest.param(_case("with fail_after(1): ...", _MARK), id="inner-below-marker"),
    pytest.param(_case('text = "@pytest.mark.timeout(0.5)"'), id="string-marker"),
    pytest.param(
        _case("def block(): sleep(_BLOCK)", _MARK, "_BLOCK = 10"),
        id="nested-constant-sleep",
    ),
    pytest.param(_case('tmp_path / "GUIDE.md"'), id="tmp-doc"),
]
BACKSTOP_CASES = [
    pytest.param(f"{_OPTIONS}timeout = 30\n", 30, id="recorded"),
    pytest.param(f"{_OPTIONS}timeout = 30.0\n", 30.0, id="float"),
    pytest.param("", None, id="missing"),
]
GLOBAL_BOUND_CASES = [
    pytest.param("timeout = 30\nfaulthandler_timeout = 15\n", [], id="clean"),
    pytest.param(
        "timeout = 25\nfaulthandler_timeout = 15\n",
        [f"timeout = 25 {_LADDER}"],
        id="off-ladder",
    ),
    pytest.param(
        "timeout = 30\nfaulthandler_timeout = 30\n",
        ["faulthandler_timeout = 30 must stay below timeout (30 s)"],
        id="faulthandler-at-timeout",
    ),
]


class TestLayoutLint:
    """The tier test-layout lint check."""

    def test_an_indexed_suite_passes(self, tmp_path: Path) -> None:
        assert _messages(_write_suite(tmp_path)) == []

    @pytest.mark.parametrize(
        ("files", "message"),
        [
            pytest.param(
                {"public__test_gamma.py": "class TestGamma: ...\n"},
                STALE,
                id="unindexed-file",
            ),
            pytest.param(
                {"public__test_gamma.py": "class TestBeta: ...\n"},
                "Beta is owned by both test_alpha.py and test_gamma.py",
                id="duplicate-subject",
            ),
            pytest.param(
                {"public__test_regressions.py": ""},
                "name the file for its subject, not its history",
                id="history-name",
            ),
            pytest.param(
                {"public__helpers.py": ""},
                "shared helpers belong in a tests/_*.py module",
                id="helper-in-tier",
            ),
            pytest.param(
                {"test_root.py": ""},
                "test files live in public, internal, functional",
                id="root-test-file",
            ),
            pytest.param(
                {"misc__test_x.py": ""},
                "unexpected folder; tests live in public, internal, functional",
                id="stray-folder",
            ),
        ],
    )
    def test_misplaced_files_fail(
        self, tmp_path: Path, files: dict[str, str], message: str
    ) -> None:
        assert (message, True) in _messages(_write_suite(tmp_path, **files))

    @pytest.mark.parametrize(
        ("addition", "message"),
        [
            pytest.param(
                "\ndef test_loose(): ...\n",
                "test_loose must live in a Test<Subject> class",
                id="top-level-test",
            ),
            pytest.param("\nclass TestGamma: ...\n", STALE, id="unindexed-class"),
            pytest.param(
                "\nfrom riko.x import _hidden\n",
                "public tests import supported names: _hidden",
                id="private-import",
            ),
            *BOUND_CASES,
        ],
    )
    def test_in_file_departures_fail(
        self, tmp_path: Path, addition: str, message: str
    ) -> None:
        tests_dir = _write_suite(tmp_path)
        path = tests_dir / "public" / "test_alpha.py"
        path.write_text(path.read_text(encoding="utf-8") + addition, encoding="utf-8")
        assert (message, True) in _messages(tests_dir)

    @pytest.mark.parametrize("addition", CLEAN_BOUND_CASES)
    def test_bounds_and_doc_reads_outside_the_rules_pass(
        self, tmp_path: Path, addition: str
    ) -> None:
        tests_dir = _write_suite(tmp_path)
        path = tests_dir / "public" / "test_alpha.py"
        path.write_text(path.read_text(encoding="utf-8") + addition, encoding="utf-8")
        messages = [message for message, _ in _messages(tests_dir)]
        assert not [m for m in messages if any(f in m for f in _BOUND_FRAGMENTS)]

    @pytest.mark.parametrize(("text", "expected"), BACKSTOP_CASES)
    def test_backstop_comes_from_the_pytest_timeout(
        self, text: str, expected: int | None
    ) -> None:
        assert get_backstop(text) == expected

    @pytest.mark.parametrize(("options", "expected"), GLOBAL_BOUND_CASES)
    def test_pytest_timeout_globals_sit_on_the_ladder(
        self, options: str, expected: list[str]
    ) -> None:
        issues = gen_global_bound_issues(f"{_OPTIONS}{options}", Path("pyproject.toml"))
        assert [issue.message for issue in issues] == expected

    @pytest.mark.parametrize(("old", "new", "expected"), INDEX_FORMS)
    def test_the_index_must_match_its_generated_form(
        self, tmp_path: Path, old: str, new: str, expected: list[str]
    ) -> None:
        tests_dir = _write_suite(tmp_path)
        init = tests_dir / "public" / "__init__.py"
        init.write_text(init.read_text(encoding="utf-8").replace(old, new, 1))
        assert [message for message, _ in _messages(tests_dir)] == expected

    def test_long_files_get_advice_to_split(self, tmp_path: Path) -> None:
        tests_dir = _write_suite(tmp_path)
        (tests_dir / "public" / "test_alpha.py").write_text(_ALPHA + "\n" * SPLIT_LINES)
        messages = _messages(tests_dir)
        assert [fatal for _, fatal in messages] == [False]
        assert "move its largest Test<Subject> class" in messages[0][0]

    @pytest.mark.parametrize(
        ("fatal", "line", "code"),
        [
            pytest.param(True, "a.py:3: error: bad", 1, id="error"),
            pytest.param(False, "a.py:3: advice: bad", 0, id="advice"),
        ],
    )
    def test_findings_print_and_set_the_exit_code(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        fatal: bool,
        line: str,
        code: int,
    ) -> None:
        issue = LayoutIssue(Path("a.py"), 3, "bad", fatal=fatal)
        monkeypatch.setattr(_lint, "gen_layout_issues", lambda *_: [issue])

        assert str(issue) == line
        assert _lint._lint_tests() == code
        assert line in capsys.readouterr().out

    def test_short_files_get_advice_not_failure(self, tmp_path: Path) -> None:
        tests_dir = _write_suite(tmp_path)
        (tests_dir / "public" / "test_alpha.py").write_text(_ALPHA, encoding="utf-8")
        messages = _messages(tests_dir)
        assert [fatal for _, fatal in messages] == [False]
        assert "consider merging" in messages[0][0]


BASENAME_CASES = [
    pytest.param(("a/x.py", "b/y.py"), frozenset(), [], id="clean"),
    pytest.param(
        ("a/x.py", "b/x.py"),
        frozenset(),
        [("x.py", ("pkg/a/x.py", "pkg/b/x.py"), _SHARED)],
        id="duplicate",
    ),
    pytest.param(("a/x.py", "b/x.py"), frozenset({"x.py"}), [], id="allowlisted"),
    pytest.param(
        ("a/x.py",),
        frozenset({"x.py"}),
        [("x.py", ("pkg/a/x.py",), _STALE_BASENAME)],
        id="stale",
    ),
    pytest.param(("a/__init__.py", "b/__init__.py"), frozenset(), [], id="init"),
]


class TestBasenameLint:
    """The duplicate module-basename lint check."""

    @pytest.mark.parametrize(("names", "allowed", "expected"), BASENAME_CASES)
    def test_shared_basenames_and_stale_allowlist_entries_are_flagged(
        self,
        tmp_path: Path,
        names: tuple[str, ...],
        allowed: frozenset[str],
        expected: list[tuple[str, tuple[str, ...], str]],
    ) -> None:
        package = tmp_path / "pkg"

        for name in names:
            (package / name).parent.mkdir(parents=True, exist_ok=True)
            (package / name).write_text("", encoding="utf-8")

        issues = gen_basename_issues(package, allowed=allowed)
        found = [(i.basename, tuple(map(str, i.paths)), i.message) for i in issues]
        assert found == expected

    def test_findings_print_and_fail_the_check(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        issue = BasenameIssue("x.py", (Path("a/x.py"), Path("b/x.py")), "bad")
        monkeypatch.setattr(_lint, "gen_basename_issues", lambda _: [issue])
        line = "x.py: bad (a/x.py, b/x.py)"

        assert str(issue) == line
        assert _lint._lint_basenames() == 1
        assert line in capsys.readouterr().out


def _try(body: str, caught: str = "ImportError", handler: str = "pass") -> str:
    return f"try:\n    {body}\nexcept {caught}:\n    {handler}\n"


ESCAPE_CASES = [
    pytest.param("from typing import Any\nx: Any\n", 1, 0, id="bare-any"),
    pytest.param("import typing as t\nx: t.Any\n", 1, 0, id="qualified-any"),
    pytest.param("from typing import Any as A\nx: A\n", 1, 0, id="aliased-any"),
    pytest.param("from typing import Any\nx: 'list[Any]'\n", 1, 0, id="quoted-any"),
    pytest.param("from typing import Any\nX = A[B['Any']]\n", 1, 0, id="subscript"),
    pytest.param("from typing import Any\ndef f() -> Any: ...\n", 1, 0, id="return"),
    pytest.param("from typing import cast\ncast('int', x)\n", 0, 1, id="cast"),
    pytest.param("import typing\ntyping.cast(int, x)\n", 0, 1, id="typing-cast"),
    pytest.param(
        "from typing import cast\ncast('dict[str, Any]', x)\n", 0, 1, id="unbound"
    ),
    pytest.param("from riko import cast\ncast(x)\nAny = 1\n", 0, 0, id="foreign"),
]

ESCAPE_RATCHET_CASES = [
    pytest.param(_ANY, 0, "any = 0\ncast = 0", id="gain-lowers"),
    pytest.param(_ANY_CAST, 0, "any = 2\ncast = 1", id="equal-holds"),
    pytest.param(_ANY + "x: Any\n" * 3, 1, "any = 2\ncast = 0", id="loss-fails"),
]


class TestEscapeLint:
    """The ``Any`` and ``cast`` ceiling lint check."""

    @pytest.mark.parametrize(("source", "any_", "cast"), ESCAPE_CASES)
    def test_escapes_are_counted_once_by_binding(
        self, source: str, any_: int, cast: int
    ) -> None:
        assert get_escape_counts(source) == {"Any": any_, "cast": cast}

    @pytest.mark.parametrize(("source", "code", "ceilings"), ESCAPE_RATCHET_CASES)
    def test_check_ratchets_each_ceiling(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        source: str,
        code: int,
        ceilings: str,
    ) -> None:
        package = tmp_path / "pkg"
        package.mkdir()
        (package / "mod.py").write_text(source, encoding="utf-8")
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("[tool.riko.typing]\nany = 2\ncast = 1\n")
        monkeypatch.setattr(_lint, "ROOT_DIR", tmp_path)
        monkeypatch.setattr(_lint, "PACKAGE_DIR", package)

        assert _lint._lint_escapes() == code
        typing = tomllib.loads(pyproject.read_text())["tool"]["riko"]["typing"]
        recorded = {k: v for k, v in typing.items() if not k.endswith("-lowered")}
        assert recorded == tomllib.loads(ceilings)


def _issues(tmp_path: Path, source: str) -> tuple[list[str], list[int]]:
    package = tmp_path / "pkg"
    package.mkdir(exist_ok=True)
    (package / "mod.py").write_text(source, encoding="utf-8")
    config = tmp_path / "pyproject.toml"
    config.write_text(PYPROJECT_TOML, encoding="utf-8")
    issues = list(gen_import_issues(package, config, DISTRIBUTIONS))
    required = [issue.message for issue in issues if issue.where == str(config)]
    lines = [int(i.where.rsplit(":", 1)[1]) for i in issues if i.where != str(config)]
    return required, lines


RUNTIME_NAME_CASES = [
    pytest.param(ABSOLUTE, ["a", "c"], id="absolute-only"),
    pytest.param(_if(TC) + "import b\n", ["b"], id="type-checking-body"),
    pytest.param(_if("typing.TYPE_CHECKING"), [], id="typing-attribute"),
    pytest.param(_if(TC, "pass", "import a"), ["a"], id="type-checking-else"),
    pytest.param(_if(NOT_TC), ["a"], id="not-type-checking-body"),
    pytest.param(_if(NOT_TC, "pass", "import a"), [], id="not-type-checking-else"),
    pytest.param(_if(f"{TC} and flag"), ["a"], id="compound-test"),
    pytest.param(ELIF, ["a"], id="elif-branch"),
    pytest.param(LOCAL, ["b"], id="function-local"),
    pytest.param(TRY, ["a"], id="try-block"),
]

REQUIREMENT_CASES = [
    pytest.param(f"{REQUESTS}import dateutil\n", [], id="both-used"),
    pytest.param(REQUESTS + _if(TC, "import dateutil"), [ONLY], id="typing-only"),
    pytest.param(REQUESTS + _if(NOT_TC, "import dateutil"), [], id="not-type-checking"),
]

OPTIONAL_CASES = [
    pytest.param(LXML, [1], id="unguarded"),
    pytest.param(_try("import lxml"), [], id="import-error"),
    pytest.param(_try("import lxml", "ModuleNotFoundError"), [], id="not-found"),
    pytest.param(_try("import lxml", "(ValueError, ImportError)"), [], id="tuple"),
    pytest.param(_try("import lxml", "ValueError"), [2], id="wrong-handler"),
    pytest.param(_try("pass", handler="import lxml"), [4], id="in-handler"),
    pytest.param(_try("import a") + "else:\n    import lxml\n", [], id="try-else"),
    pytest.param(_if(TC, "import lxml"), [], id="typing-only"),
    pytest.param("def f():\n    import lxml\n", [2], id="function-local"),
    pytest.param(REQUESTS, [], id="also-required"),
]


class TestDependencyLint:
    """The run-time requirement lint check."""

    @pytest.mark.parametrize(("source", "expected"), RUNTIME_NAME_CASES)
    def test_runtime_names_skip_only_typing_only_branches(
        self, source: str, expected: list[str]
    ) -> None:
        assert [runtime.name for runtime in gen_runtime_imports(source)] == expected

    @pytest.mark.parametrize(("source", "expected"), REQUIREMENT_CASES)
    def test_required_dependencies_must_be_imported_at_run_time(
        self, tmp_path: Path, source: str, expected: list[str]
    ) -> None:
        assert _issues(tmp_path, source)[0] == expected

    @pytest.mark.parametrize(("source", "expected"), OPTIONAL_CASES)
    def test_optional_extras_must_be_imported_under_a_guard(
        self, tmp_path: Path, source: str, expected: list[int]
    ) -> None:
        assert _issues(tmp_path, source)[1] == expected


def _pin_issues(tmp_path: Path, hooks: str) -> list[tuple[str, str]]:
    config = tmp_path / ".pre-commit-config.yaml"
    config.write_text(hooks, encoding="utf-8")
    lockfile = tmp_path / "uv.lock"
    lockfile.write_text(LOCK, encoding="utf-8")
    issues = gen_hook_pin_issues(config, lockfile)
    return [(issue.where.rsplit(":", 1)[-1], issue.message) for issue in issues]


class TestHookPinLint:
    """Pre-commit hook pins checked against uv.lock."""

    def test_hook_pin_must_match_the_lock(self, tmp_path: Path) -> None:
        """A hook that pins another ruff than uv.lock is reported at its line."""
        expected = [("8", "hook pins ruff==0.16.9 but uv.lock has 0.16.10")]
        assert _pin_issues(tmp_path, HOOKS) == expected

    def test_hooks_must_pin_each_locked_tool(self, tmp_path: Path) -> None:
        """A configuration that never pins ruff is reported."""
        hooks = "repos: []\n"
        found = [message for _, message in _pin_issues(tmp_path, hooks)]
        assert found == ["no hook pins 'ruff'; pin it as ruff==0.16.10"]

    def test_upgrade_rewrites_hook_pins_to_the_lock(self, tmp_path: Path) -> None:
        """After an upgrade, every hook pin names the locked version."""
        config = tmp_path / ".pre-commit-config.yaml"
        config.write_text(HOOKS, encoding="utf-8")
        lockfile = tmp_path / "uv.lock"
        lockfile.write_text(LOCK, encoding="utf-8")
        _pin_hooks(config, lockfile)
        assert list(gen_hook_pin_issues(config, lockfile)) == []
        assert config.read_text(encoding="utf-8").count("ruff==0.16.10") == 2

    def test_locked_version_lookup_names_a_missing_package(
        self, tmp_path: Path
    ) -> None:
        """Asking the lock for a package it lacks raises instead of guessing."""
        lockfile = tmp_path / "uv.lock"
        lockfile.write_text(LOCK, encoding="utf-8")
        assert get_locked_version(lockfile, "Ruff") == "0.16.10"

        with pytest.raises(LookupError, match="'pyright' is not in"):
            get_locked_version(lockfile, "pyright")


class TestCanonicalImportLint:
    """The canonical-import lint check."""

    def test_canonical(self, tmp_path: Path) -> None:
        root = tmp_path / "riko"
        write(root, "__init__.py", "from .core import Thing\n")
        write(root, "core.py", "class Thing: pass\n")
        write(root, "use.py", "from riko import Thing\n")
        issues = canonical_issues(root)
        assert len(issues) == 1
        assert issues[0].canonical_module == "riko.core"


class TestRelativeImportLint:
    """The relative-import lint check."""

    def test_relative(self, tmp_path: Path) -> None:
        root = tmp_path / "riko"
        write(root, "__init__.py", "")
        write(root, "pkg/__init__.py", "")
        write(root, "pkg/a.py", "from riko.pkg.b import thing\n")
        write(root, "pkg/b.py", "thing = 1\n")
        issues = relative_issues(root)
        assert len(issues) == 1
        assert issues[0].suggestion == "from .b import thing"


ARCHITECTURE_IMPORTS = [
    pytest.param(_UPWARD, ["runtime"], id="upward"),
    pytest.param(_GUARDED, [], id="type-checking-is-exempt"),
    pytest.param(_LOCAL, ["runtime"], id="function-local-upward-fails"),
]


class TestImportArchitectureLint:
    """The import-architecture lint check."""

    @pytest.mark.parametrize(("source", "targets"), ARCHITECTURE_IMPORTS)
    def test_architecture(self, tmp_path: Path, source, targets) -> None:
        root = tmp_path / "riko"
        write(root, "__init__.py", "")
        write(root, "types/__init__.py", "")
        write(root, "types/a.py", source)
        write(root, "runtime/__init__.py", "")
        write(root, "runtime/b.py", "thing = 1\n")
        report = load_architecture_report(root)
        assert not report.unclassified
        assert [v.target_label for v in report.violations] == targets
        assert ("architecture violations:" in render_architecture(report)) == bool(
            targets
        )

    def test_unclassified_fails(self, tmp_path: Path) -> None:
        root = tmp_path / "riko"
        write(root, "__init__.py", "")
        write(root, "mystery/__init__.py", "")
        report = load_architecture_report(root)
        assert report.unclassified[0].module == "riko.mystery"

    def test_layer_graph_validation_accepts_a_reduced_dag(self):
        _validate_graph("test", {"a": {"b"}, "b": {"c"}, "c": set()})

    @pytest.mark.parametrize(
        ("graph", "match"),
        [
            pytest.param(
                {"a": {"b", "c"}, "b": {"c"}, "c": set()},
                "redundant dependency: a -> c",
                id="redundant",
            ),
            pytest.param({"a": {"b"}, "b": {"a"}}, "cyclic layer graph", id="cyclic"),
            pytest.param({"a": {"b"}}, "undeclared layers: b", id="undeclared"),
        ],
    )
    def test_layer_graph_validation_rejects(self, graph, match):
        with pytest.raises(InvalidArchitectureError, match=match):
            _validate_graph("test", graph)


LEGACY = [pytest.param(DAG, id="dag"), pytest.param(PIPE_DEF, id="v1")]


class TestRequireWorkflow:
    """Workflow documents accepted by the console scripts."""

    @pytest.mark.parametrize("document", LEGACY)
    def test_require_workflow_points_at_the_converter(self, document):
        with pytest.raises(InvalidPipelineError, match="build-workflow"):
            require_workflow(document)

    def test_require_workflow_accepts_a_workflow_document(self):
        assert require_workflow(WORKFLOW) == Workflow.parse(DAG)

    def test_require_workflow_rejects_a_non_mapping(self):
        with pytest.raises(InvalidPipelineError, match="must be a mapping"):
            require_workflow([])


class TestRunTarget:
    """Running the targets run-pipe resolves."""

    def test_workflow_module_honors_test(self, capsys, monkeypatch):
        """A workflow module's input node uses its default under test, not a prompt."""
        conf = {"name": "fmt", "prompt": "enter", "default": "%Y"}
        flow = Workflow.parse({"modules": [{"name": "input", "conf": conf}]})
        module = ModuleType("generated")
        exec(compile_workflow(flow), module.__dict__)
        monkeypatch.setattr("sys.stdin", io.StringIO(""))

        run_target(module, test=True)

        assert capsys.readouterr().out == "%Y\n"


def _record_warnings(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    warnings: list[str] = []
    warning = lambda msg, *args: warnings.append(msg % args)
    monkeypatch.setattr(_document.logger, "warning", warning)
    return warnings


class TestReadDocument:
    """Reading JSON inputs from paths and stdin."""

    def test_read_document_reports_a_missing_path(self, monkeypatch):
        warnings = _record_warnings(monkeypatch)
        assert read_document("no-such-flow.json") == (None, "no-such-flow")
        assert any("Unable to read input file" in warning for warning in warnings)

    def test_read_document_reports_malformed_json(self, tmp_path, monkeypatch):
        warnings = _record_warnings(monkeypatch)
        malformed = tmp_path / "malformed.json"
        malformed.write_text("{bad json", encoding="utf-8")
        assert read_document(str(malformed)) == (None, "malformed")
        assert any("Unable to parse input" in warning for warning in warnings)

    def test_read_document_reports_malformed_stdin(self, monkeypatch):
        warnings = _record_warnings(monkeypatch)
        monkeypatch.setattr("sys.stdin", io.StringIO("{bad json"))
        assert read_document("-") == (None, "anonymous")
        assert any("Unable to parse input" in warning for warning in warnings)

    def test_read_document_parses_a_committed_document(self):
        document, name = read_document(str(DAG_PATH))
        assert (document, name) == (DAG, "pipe_forever")


class TestTimeouts:
    def test_a_timeout_fails_an_xfail_test(self, pytester: pytest.Pytester) -> None:
        """
        An xfail test that ends by its timeout is reported as failed.

        Runs in a subprocess so the signal never fires under this process's
        coverage tracer.
        """
        pytester.makepyfile(_TIMEOUT_SUITE)
        result = pytester.runpytest_subprocess(
            "-p",
            "tests._timeouts",
            "-p",
            "no:cacheprovider",
            "-o",
            "addopts=",
            timeout=8,
        )
        result.assert_outcomes(failed=1, xfailed=1)
        result.stdout.fnmatch_lines(["*test_hangs hit its timeout*never ends*"])


class TestSubprocessImports:
    def test_a_script_imports_the_checkout_under_test(self, tmp_path):
        # A script outside the checkout resolves riko the way a console script does.
        probe = tmp_path / "probe.py"
        probe.write_text("import riko\nprint(riko.__file__)\n")
        done = run_python(str(probe), cwd=tmp_path)
        assert done.stdout.strip() == str(ROOT_DIR / "riko" / "__init__.py")


LOG_LEVELS = [
    pytest.param(0, False, WARNING, id="default"),
    pytest.param(1, False, INFO, id="verbose"),
    pytest.param(2, False, DEBUG, id="very-verbose"),
    pytest.param(3, False, DEBUG, id="capped"),
    pytest.param(0, True, ERROR, id="quiet"),
    pytest.param(2, True, ERROR, id="quiet-wins"),
]
MANAGER_LEVELS = [
    pytest.param(["-vv"], DEBUG, id="verbose"),
    pytest.param(["-q"], ERROR, id="quiet"),
]


class TestLogLevel:
    """The manage flags select the level every riko logger inherits."""

    @pytest.mark.parametrize(("verbose", "quiet", "level"), LOG_LEVELS)
    def test_resolve_log_level(self, verbose, quiet, level):
        assert resolve_log_level(verbose, quiet) == level

    @pytest.mark.parametrize(("args", "level"), MANAGER_LEVELS)
    def test_manager_sets_the_riko_level(self, riko_level, args, level):
        result = CliRunner().invoke(manager, [*args, "hello"])
        assert result.exit_code == 0
        assert getLogger("riko").level == level

    def test_exception_hook_logs_the_error(self, caplog):
        error = ValueError("bad value")

        with caplog.at_level(ERROR, logger="riko"):
            exception_hook(ValueError, error, None)

        assert any(
            record.levelno == ERROR and "bad value" in record.getMessage()
            for record in caplog.records
        )
