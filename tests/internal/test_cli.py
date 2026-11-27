# vim: sw=4:ts=4:expandtab
"""Provides internal tests for the manage commands, lint checks, and workflow input."""

from __future__ import annotations

import io
import json
import tomllib
from contextlib import nullcontext
from datetime import date, timedelta
from importlib import import_module
from logging import DEBUG, ERROR, INFO, WARNING, getLogger
from pathlib import Path
from textwrap import indent
from types import ModuleType
from typing import TYPE_CHECKING

import pytest
from click.testing import CliRunner

from riko.base._exceptions import InvalidPipelineError
from riko.base._funcutils import map_keys
from riko.base._paths import PYPROJECT
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
    gen_stale_private_names,
    gen_stale_source_symbol_citations,
    gen_stale_test_citations,
    gen_stale_test_symbol_citations,
    gen_unruled_terms,
)
from riko.cli._docstyle import gen_docstring_issues, gen_example_prose
from riko.cli._document import read_document, require_workflow
from riko.cli._import_graph import InvalidArchitectureError
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
from riko.cli._lint_helpers import ChainReport
from riko.cli._lint_import_architecture import (
    _validate_graph,
    lint_architecture,
    load_architecture_report,
    render_architecture,
)
from riko.cli._lint_literals import gen_literal_issues
from riko.cli._lint_ownership import ADD_MESSAGE, gen_ownership_lines
from riko.cli._lint_relative_imports import _iter_issues as relative_issues
from riko.cli._lint_rst import gen_plain_block_lines, gen_unrendered_literal_lines
from riko.cli._lint_terms import BannedTerm, gen_phrase_issues, gen_term_issues
from riko.cli._logging import exception_hook, resolve_log_level
from riko.cli._ratchet import build_ceiling_text, ratchet_ceiling
from riko.cli._upgrade import _pin_hooks
from riko.cli.manage import manager
from riko.cli.runpipe import run_target
from riko.definitions._workflow_definition import Workflow
from riko.runtime._compile import compile_workflow
from tests._workflows import DAG, DOCUMENT, PIPE_DEF

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator

    from riko.types._wrappers import Func

_TYPING = "[tool.riko.typing]\n"
_TODAY = date(2026, 10, 27)
_WINDOW = "\n[tool.riko.ratchet]\nstale-days = 7\n"
_FRESH = f"any = 9\nany-lowered = 2026-10-25\n{_WINDOW}"
_STALE = f"any = 9\nany-lowered = 2026-10-19\n{_WINDOW}"
_STALE_ZERO = f"any = 0\nany-lowered = 2026-10-19\n{_WINDOW}"
_DATED = "any = 8\nany-lowered = 2026-10-27\n"
_LOWERED = f"{_DATED}{_WINDOW}"
_DATETIME = "any = 8\nany-lowered = 2026-10-01T10:00:00\n"
_UNWINDOWED = "any = 9\nany-lowered = 2026-01-01\n"
_HOLDS = "9 uses hold the ceiling of 9."
_HOLDS_ZERO = "0 uses hold the ceiling of 0."
_HELD = "9 uses have held the ceiling of 9 since 2026-10-19, over 7 days; lower it."
_RECORDED = "8 uses; recorded the ceiling as 8 on 2026-10-27."

_DISCARDED = (
    " CI discards this change; run the ratchet locally and commit pyproject.toml."
)

_CI_DISCARDS = f"::warning::{_RECORDED}{_DISCARDED}"
_MODULE_EXAMPLE = '"""\nDoes.\n\n>>> 1\n1\n"""\n'
_PRIVATE_MODULE = ["private module without a public API carries a module example"]
_NO_MODULE_EXAMPLE = "private module with a public runtime API has no module example"

_TYPE_ONLY_EXAMPLE = (
    "private module with a type-only public API carries a module example"
)

_TYPE_ONLY = "class Item(Protocol): ...\nclass Stream(Item): ...\n"
_TYPED_DOC = f"{_MODULE_EXAMPLE}{_TYPE_ONLY}"
_SHARED = "basename is shared; rename one or allowlist the pair"
_STALE_BASENAME = "allowlisted basename is no longer duplicated; remove it"
_ANY = "from typing import Any\n"
_ANY_CAST = "from typing import Any, cast\nx: Any = cast(Any, y)\n"
_UPWARD = "from riko.runtime.b import thing\n"
_GUARDED = "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    " + _UPWARD

_NEGATED = (
    "from typing import TYPE_CHECKING\nif not TYPE_CHECKING:\n    pass\nelse:\n    "
)

_LOCAL = "def load():\n    " + _UPWARD + "\n    return thing\n"

_RUN_BINDING = (
    "binds a run( result that is skipped without async support "
    "(move it to an async example)"
)

_RUN_DOC = ">>> from riko import run\n>>> g = list\n>>> x = run(g())"
_CHAIN = "def run():\n    _a()\ndef _a():\n    _b()\ndef _b(): ...\n"
_TWO = "def two():\n    _c()\ndef _c():\n    _b()\n"

_STEPS = (
    "class A:\n"
    "    def run(self):\n        self._step()\n"
    "    def _step(self):\n        self._go()\n"
    "    def _go(self): ...\n"
    "class B:\n"
    "    def other(self):\n        self._step()\n"
    "    def _step(self): ...\n"
)

_STRAY_ADD = "def f(run, s):\n    run.add(s)\n"
_UPGRADE_ALL = ["uv", "lock", "--upgrade"]
_ALL_LINTS = [
    "ruff",
    "rumdl",
    "rst",
    "docs",
    "docstrings",
    "terms",
    "literals",
    "deps",
    "bindings",
    "tests",
    "basenames",
    "escapes",
    "helpers",
    "ownership",
    "actions",
    "yaml",
    "imports",
]
_PATCHED_LINTS = (
    ("_lint_python", "ruff"),
    ("_lint_markdown", "rumdl"),
    ("lint_rst", "rst"),
    ("lint_docs", "docs"),
    ("_lint_docstrings", "docstrings"),
    ("_lint_terms", "terms"),
    ("_lint_literals", "literals"),
    ("_lint_deps", "deps"),
    ("_lint_bindings", "bindings"),
    ("_lint_tests", "tests"),
    ("_lint_actions", "actions"),
    ("_lint_yaml", "yaml"),
    ("run_import_checks", "imports"),
    ("_lint_basenames", "basenames"),
    ("_lint_escapes", "escapes"),
    ("_lint_helpers", "helpers"),
    ("_lint_ownership", "ownership"),
    ("_lint_types", "types"),
    ("_verify_types", "verify-types"),
    ("twine_check", "dist"),
    ("_lint_python_strict", "strict"),
)

SYNC = ["uv", "sync", "--active", "--locked", "--group", "dev", "--all-extras"]
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

DATA_ONLY_TOML = f"""{PYPROJECT_TOML}
[tool.deptry.per_rule_ignores]
DEP002 = ["Python.Dateutil"]
"""

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

[[package]]
name = "rumdl"
version = "0.3.2"
"""

HOOKS = """
repos:
  - repo: local
    hooks:
      - id: ruff-check
        additional_dependencies: [ruff==0.16.10]
      - id: ruff-format
        additional_dependencies: [ruff==0.16.9]
      - id: rumdl-check
        additional_dependencies: [rumdl==0.3.2]
"""

TC, NOT_TC = "TYPE_CHECKING", "not TYPE_CHECKING"


def _if(test: str, body: str = "import a", orelse: str = "") -> str:
    tail = f"else:\n    {orelse}\n" if orelse else ""
    return f"if {test}:\n    {body}\n{tail}"


LOCAL = "def f():\n" + indent(_if(TC) + "import b\n", "    ")
ELIF = _if(TC, "pass") + "elif flag:\n    import a\n"


def write(root: Path, path: str, text: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)


def _record(calls: list[str], name: str, code: int = 0) -> Func[int]:
    def runner(*_: object, **_kw: object) -> int:
        calls.append(name)
        return code

    return runner


CODEGEN_SELECTORS = [
    pytest.param([], ["config"], id="default"),
    pytest.param(["--names", "--api"], ["names", "api"], id="names-api"),
    pytest.param(["--tests", "--verbs"], ["tests", "verbs"], id="tests-verbs"),
    pytest.param(["--user-agents"], ["user-agents"], id="user-agents"),
    pytest.param(
        ["--all"], ["config", "names", "api", "tests", "verbs", "user-agents"], id="all"
    ),
]


class TestCodegenCommand:
    """The ``manage codegen`` selectors."""

    @pytest.mark.parametrize(("args", "expected"), CODEGEN_SELECTORS)
    def test_codegen_selectors(
        self, monkeypatch: pytest.MonkeyPatch, args: list[str], expected: list[str]
    ) -> None:
        calls: list[str] = []
        monkeypatch.setattr(
            _codegen,
            "_CODEGEN",
            {
                name: (_record(calls, name), name, f"{name} failed")
                for name in _codegen._CODEGEN
            },
        )

        result = CliRunner().invoke(_codegen.CODEGEN_COMMAND, args)
        assert result.exit_code == 0
        assert calls == expected


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


UPGRADE_RUNS = [
    pytest.param([], [_UPGRADE_ALL, SYNC], id="default"),
    pytest.param(
        ["-p", "ruff", "--package", "pyright"],
        [["uv", "lock", "--upgrade-package=ruff", "--upgrade-package=pyright"], SYNC],
        id="packages",
    ),
    pytest.param(["--no-sync"], [_UPGRADE_ALL], id="no-sync"),
]


class TestUpgradeCommand:
    """The ``manage upgrade`` lock, sync, and daily stamp."""

    @pytest.mark.parametrize(("args", "expected"), UPGRADE_RUNS)
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


IMPORT_SELECTORS = [
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
]


class TestImportsCommand:
    """The ``manage lint imports`` selectors."""

    @pytest.mark.parametrize(
        ("args", "failing", "expected", "exit_code"), IMPORT_SELECTORS
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
        monkeypatch.setattr(_import_commands, "IMPORT_CHECKS", checks)

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
    for name, tag in _PATCHED_LINTS:
        monkeypatch.setattr(_lint, name, _record(calls, tag))


TEXT_CHECKS = [
    pytest.param(_lint._lint_terms, "Run a sub-pipeline.\n", id="terms"),
    pytest.param(_lint._lint_literals, "Pass ``'list'``.\n", id="literals"),
]
LINT_SELECTORS = [
    pytest.param([], ["ruff", "rumdl"], id="default"),
    pytest.param(["--rst", "--yaml"], ["rst", "yaml"], id="rst-yaml"),
    pytest.param(["--all"], _ALL_LINTS, id="all"),
    pytest.param(
        ["--terms", "--literals", "--deps", "--bindings", "--tests"],
        ["terms", "literals", "deps", "bindings", "tests"],
        id="text-and-code-checks",
    ),
    pytest.param(["--check-types", "--strict"], ["types", "strict"], id="types-strict"),
    pytest.param(["--helpers"], ["helpers"], id="helpers"),
    pytest.param(["--ownership"], ["ownership"], id="ownership"),
]


class TestLintCommand:
    """The ``manage lint`` selectors."""

    @pytest.mark.parametrize(("check", "text"), TEXT_CHECKS)
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

    def test_staged_check_lints_python_with_ruff_and_markdown_with_rumdl(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[list[str]] = []
        staged = "a.py\nREADME.md\nsetup.cfg\n"
        monkeypatch.setattr(_lint, "_ruff", "ruff")
        monkeypatch.setattr(_lint, "_rumdl", "rumdl")
        monkeypatch.setattr(_lint, "check_output", lambda *_, **_kw: staged)
        monkeypatch.setattr(_lint, "call", lambda args: calls.append(args) or 0)

        assert _lint._lint_staged() == 0
        assert calls == [
            ["ruff", "check", "a.py"],
            ["ruff", "format", "--check", "a.py"],
            ["rumdl", "check", "README.md"],
        ]

    @pytest.mark.parametrize(("args", "expected"), LINT_SELECTORS)
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


COVERAGE_RATCHETS = [
    pytest.param(1249, 1240, 0, "uncovered = 1240", id="gain-lowers"),
    pytest.param(1249, 1249, 0, "uncovered = 1249", id="equal-holds"),
    pytest.param(1249, 1250, 1, "uncovered = 1249", id="loss-fails"),
    pytest.param(None, 1250, 0, "uncovered = 1250", id="first-run-records"),
]
COVERAGE_OPTIONS = [
    pytest.param(["-q"], "--cov=riko", "--cov-report", id="default"),
    pytest.param(["-q", "--no-cov"], "--no-cov", "--cov-report", id="no-cov"),
    pytest.param(["-q", "--ratchet"], "--cov-report=json:", "", id="ratchet"),
]
PARTIAL_RATCHET_CASES = [
    pytest.param(["tests/public"], id="paths"),
    pytest.param(["--tox"], id="tox"),
    pytest.param(["--failed"], id="failed"),
]


class TestCoverageRatchet:
    """The ``manage test --ratchet`` uncovered-line ceiling."""

    @pytest.mark.parametrize(
        ("recorded", "uncovered", "code", "ceiling"), COVERAGE_RATCHETS
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

        if recorded is None:
            table = ""
        else:
            table = f"[tool.riko.coverage]\nuncovered = {recorded}\n"

        pyproject.write_text(f"[project]\nname = 'x'\n{table}")
        monkeypatch.setattr(_test, "PYPROJECT", pyproject)

        assert _test._ratchet_coverage(_coverage_report(tmp_path, uncovered)) == code
        assert ceiling in pyproject.read_text()

    @pytest.mark.parametrize(("args", "present", "absent"), COVERAGE_OPTIONS)
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
        monkeypatch.setattr(
            _test, "get_temp_path", lambda *_: folders.append("made") or nullcontext()
        )

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
    pytest.param(_STALE_ZERO, 0, False, _STALE_ZERO, _HOLDS_ZERO, id="stale-at-zero"),
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
    pytest.param(">>> a\n1\n\nWith b\nand c:\n\n>>> b", ["With b"], id="multi-line"),
    pytest.param(">>> a\n1\n\nAsync usage::\n\n>>> b", [], id="labelled-group"),
    pytest.param("Calls a.\n\n>>> a\n1", [], id="before-examples"),
    pytest.param(">>> a\n1\n\nRaises:\n\n    TypeError: x.", [], id="section"),
]


def _function(doc: str) -> str:
    body = indent(f"Runs.\n\n{doc}", "    ")
    return f'def f():\n    """\n{body}\n    """\n'


def _doctest(source: str) -> str:
    return _function(f">>> {source}")


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
        "mod.py", _doctest("from riko.cli._docs import gen_todo_lines"), [], id="nopub"
    ),
    pytest.param("mod.py", _doctest("from riko import Pipeline"), [], id="public"),
    pytest.param("_mod.py", _MODULE_EXAMPLE, _PRIVATE_MODULE, id="private-module"),
    pytest.param("_mod.py", f"{_MODULE_EXAMPLE}class Pipeline: ...\n", [], id="api"),
    pytest.param("mod.py", _MODULE_EXAMPLE, [], id="public-module"),
    pytest.param("_mod.py", "def export(): ...\n", [_NO_MODULE_EXAMPLE], id="missing"),
    pytest.param("_mod.py", _TYPE_ONLY, [], id="type-only"),
    pytest.param("_mod.py", _TYPED_DOC, [_TYPE_ONLY_EXAMPLE], id="type-only-example"),
    pytest.param("_mod.py", "class RikoError(Exception): ...\n", [], id="exception"),
    pytest.param("mod.py", "def export(): ...\n", [], id="public-missing"),
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
    pytest.param("mod.py", 'async def abuild():\n    """Builds x."""\n', [], id="twin"),
    pytest.param("mod.py", 'def build_x():\n    """Finds x."""\n', [], id="off-table"),
    pytest.param(
        "_require_guards.py",
        'def require_from_keys():\n    """Builds x."""\n',
        [],
        id="compound",
    ),
    pytest.param(
        "mod.py",
        'def f():\n    """Returns x."""\n',
        ["summary leads with the output"],
        id="output-lead",
    ),
    pytest.param(
        "mod.py",
        _function("Raises:\n\n    KeyError if missing."),
        ["Raises: entry does not start with 'SomeError:'"],
        id="malformed-raises",
    ),
    pytest.param(
        "mod.py",
        _function(">>> a = 1\n>>> a\n1\n\nWith b:\n\n>>> b = 2\n>>> b\n2"),
        ["narrates between examples (use a # comment)"],
        id="narration",
    ),
    pytest.param(
        "mod.py",
        _doctest("f() is None"),
        ["checks for None (show the bare call instead)"],
        id="none-check",
    ),
    pytest.param(
        "mod.py",
        _function("Args:\n\n    a: A.\n    b: B.\n    c: C.").replace(
            "f()", "f(a, b=1, *, c)"
        ),
        ["documents a parameter in the wrong section"] * 2,
        id="misplaced-params",
    ),
    pytest.param(
        "mod.py",
        _function("Args:\n\n    a: A.\n\nKwargs:\n\n    b: B.\n    c: C.").replace(
            "f()", "f(a, b=1, *, c)"
        ),
        [],
        id="placed-params",
    ),
    pytest.param(
        "mod.py",
        _function("Args:\n\n    a: A.\n    kwargs: K.").replace(
            "f()", "f(a, **kwargs)"
        ),
        ["documents a parameter in the wrong section"],
        id="bag-under-args",
    ),
    pytest.param(
        "mod.py",
        _function("Kwargs:\n\n    c: C.\n    b: B.").replace("f()", "f(*, b=1, c=2)"),
        ["lists parameters out of signature order"],
        id="unordered-params",
    ),
    pytest.param(
        "mod.py",
        _function("More.\n\n\nArgs:\n\n    a: A.").replace("f()", "f(a)"),
        ["has a run of blank lines"],
        id="blank-run",
    ),
    pytest.param(
        "mod.py",
        _function("# TODO: clarify\nA mid-line TODO is prose."),
        ["leaves a TODO or ??? review note"],
        id="review-note",
    ),
    pytest.param("mod.py", _function(_RUN_DOC), [_RUN_BINDING], id="run-bind"),
    pytest.param(
        "mod.py",
        _function(_RUN_DOC).replace("f()", "async_f()"),
        [],
        id="run-bind-async",
    ),
    pytest.param(
        "mod.py",
        "class AsyncThing:\n" + indent(_function(_RUN_DOC), "    "),
        [],
        id="run-bind-method",
    ),
    pytest.param(
        "mod.py",
        _doctest("from mod import f"),
        ["imports its own module's f (use it bare)"],
        id="own-name-import",
    ),
    pytest.param(
        "mod.py",
        _doctest("g()"),
        ["uses a name it neither imports nor defines"],
        id="unbound-name",
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


CITATION_SCANS = [
    pytest.param(
        gen_stale_test_citations,
        "public/test_{}.py",
        "tests/public/test_kept.py",
        id="tests",
    ),
    pytest.param(gen_stale_path_citations, "riko/{}.py", "riko/kept.py", id="paths"),
    pytest.param(gen_stale_private_names, "_{}", "_kept", id="private"),
    pytest.param(
        gen_stale_test_symbol_citations,
        "TestKept::test_{}",
        "TestKept::test_kept",
        id="symbols",
    ),
    pytest.param(gen_stale_test_symbol_citations, "test_{}", "test_kept", id="bare"),
    pytest.param(
        gen_stale_test_symbol_citations,
        "test_{}[sync]",
        "test_kept",
        id="bare-param-id",
    ),
]


@pytest.fixture
def docs_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(_docs, "ROOT_DIR", tmp_path)
    return tmp_path


class TestDocsCitations:
    """The stale test-file and source-file citation checks."""

    @pytest.mark.parametrize(("scan", "template", "kept"), CITATION_SCANS)
    def test_every_document_is_checked_against_the_known_files(
        self,
        docs_root: Path,
        scan: Callable[[str, Iterable[str]], Iterator[tuple[int, str]]],
        template: str,
        kept: str,
    ) -> None:
        gone = template.format("gone")
        reported = gone.partition("[")[0]
        paths = (docs_root / "a.md", docs_root / "b.md")

        for path in paths:
            text = f"See `{template.format('kept')}` and `{gone}`.\n"
            path.write_text(text, encoding="utf-8")

        known = (name for name in (kept,))
        offenders = _docs._gen_citation_offenders(scan, known, *paths)
        assert list(offenders) == [f"a.md:1: {reported}", f"b.md:1: {reported}"]

    @pytest.mark.parametrize(("scan", "template", "kept"), CITATION_SCANS)
    def test_history_words_exempt_their_wrapped_sentence_only(
        self,
        scan: Callable[[str, Iterable[str]], Iterator[tuple[int, str]]],
        template: str,
        kept: str,
    ) -> None:
        gone = template.format("gone")
        reported = gone.partition("[")[0]
        text = (
            f"`{gone}` and its\nneighbors were deleted. See\n`{gone}`.\n\n"
            f"- `{gone}` stays.\n- Another was removed.\n"
        )
        assert list(scan(text, (kept,))) == [(3, reported), (5, reported)]

    def test_test_symbols_cover_files_classes_and_tests(self, docs_root: Path) -> None:
        path = docs_root / "tests" / "public" / "test_alpha.py"
        path.parent.mkdir(parents=True)
        path.write_text("class TestAlpha:\n    def test_one(self): ...\n")
        rel = "tests/public/test_alpha.py"
        expected = [
            rel,
            "test_alpha",
            f"{rel}::TestAlpha",
            f"{rel}::TestAlpha::test_one",
        ]
        bare = ["TestAlpha::test_one", "test_one"]
        assert list(_docs.gen_test_symbols(path)) == [*expected, *bare]

    def test_source_symbol_pairs_check_both_names_with_the_class_prefix(self) -> None:
        path = "riko/x.py"
        known = (path, f"{path}::C", f"{path}::C.y")
        text = f"`C.x()`/`y()` (`{path}`), `C.y`/`z` (`{path}`)"
        stale = [f"{path}::C.x", f"{path}::C.z"]
        assert [
            key for _, key in gen_stale_source_symbol_citations(text, known)
        ] == stale

    def test_source_symbols_cover_bindings_in_every_scope_shape(
        self, docs_root: Path
    ) -> None:
        path = docs_root / "riko" / "alpha.py"
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

    def test_private_names_cover_every_binding_shape(self, docs_root: Path) -> None:
        path = docs_root / "riko" / "_pkg" / "_mod.py"
        path.parent.mkdir(parents=True)
        source = (
            "from . import _sib as _alias\nimport os.path\n"
            "class _C:\n    def __init__(self, _arg):\n        self._attr = _arg\n"
            "async def _f(pool):\n    _local = '_TOKEN'\n    plain = pool._read\n"
        )
        path.write_text(source)
        names = {"riko", "_pkg", "_mod", "_alias", "os", "path", "_C", "__init__"}
        names |= {"self", "_arg", "_attr", "_f", "pool", "_local", "_TOKEN", "plain"}
        names |= {"_read"}
        assert set(_docs.gen_private_names(path)) == names


class TestDocsTodos:
    """The internal-docs lint checks over the shipped user docs."""

    def test_todo_lines_are_named_by_path_and_line(
        self, monkeypatch: pytest.MonkeyPatch, docs_root: Path
    ) -> None:
        monkeypatch.setattr(_docs, "DOCS_DIR", docs_root / "docs")
        (docs_root / "docs").mkdir()
        (docs_root / "README.rst").write_text("TODO: intro\n", encoding="utf-8")
        (docs_root / "docs" / "FAQ.rst").write_text(
            "Intro.\n\nTODO: add seeding\n", encoding="utf-8"
        )
        offenders = list(_docs._gen_todo_offenders())
        assert offenders == ["README.rst:1", "docs/FAQ.rst:3"]


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
    pytest.param(
        "# pass ExecutionMode.DESCRIBE; ExecutionModes stays\n# a Describe-Mode run\n",
        [(1, "ExecutionMode"), (2, "Describe-Mode")],
        id="retired-describe",
    ),
    pytest.param(
        "class Resolver: ...\nclass TestPipelineResolver: ...\n"
        "class InputResolver: ...\n",
        [(3, "InputResolver")],
        id="resolver-class",
    ),
    pytest.param(
        "# leaving early tears the run down\n"
        "# it enters the value and tears it down afterward\n",
        [(1, "tears the run down"), (2, "tears it down")],
        id="split-phrasal-verb",
    ),
]


RETIRED_NAMES = [
    pytest.param("Import riko.ext.registry.\n", id="removed-ext-path"),
    pytest.param("Pass ExecutionMode.\n", id="retired-describe"),
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

    @pytest.mark.parametrize("text", RETIRED_NAMES)
    def test_the_changelog_may_name_retired_names(
        self, tmp_path: Path, text: str
    ) -> None:
        for name in ("GUIDE.rst", "CHANGES.rst"):
            (tmp_path / name).write_text(text, encoding="utf-8")

        found = [issue.path.name for issue in gen_term_issues(tmp_path)]
        assert found == ["GUIDE.rst"]

    def test_internal_docs_are_held_to_phrases_but_not_phase_codes(
        self, tmp_path: Path
    ) -> None:
        source = tmp_path / "IMPLEMENTED.md"
        source.write_text("Landed in R4C.\n\nRun a sub-pipeline.\n", encoding="utf-8")
        found = [(issue.lineno, issue.found) for issue in gen_phrase_issues(source)]
        assert found == [(3, "sub-pipeline")]


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


PLAIN_BLOCK_CASES = [
    pytest.param(
        ".. code-block:: python\n\n    # pipe.py\n    x = 1\n", [], id="file-comment"
    ),
    pytest.param(
        ".. code-block:: python\n\n    x = 1\n\n.. note::\n\n   Pending. Soon.\n",
        [],
        id="pending-note-after",
    ),
    pytest.param(
        ".. note::\n\n   Pending. Soon.\n\n.. code-block:: python\n\n    x = 1\n",
        [],
        id="pending-note-before",
    ),
    pytest.param(
        ".. code-block:: python\n\n    x = 1\n\n.. note::\n\n   Use ``x``.\n",
        [1],
        id="other-note-after",
    ),
    pytest.param(
        "Intro.\n\n.. code-block:: python\n\n    x = 1\n\nOutro.\n\n"
        ".. code-block:: python\n\n    >>> x\n    1\n\n"
        ".. code-block:: python\n\n    y = 2\n",
        [3, 14],
        id="only-unmarked-blocks-with-their-lines",
    ),
]
UNRENDERED_LITERAL_CASES = [
    pytest.param(
        "Intro.\n\n*Use ``map`` lazily*\n", [(3, "Use ``map`` lazily")], id="emphasis"
    ),
    pytest.param(
        ".. code-block:: python\n\n    # filter by ``loopable``\n    x = 1\n",
        [],
        id="code-block-comment",
    ),
    pytest.param("Use ``map`` lazily.\n", [], id="plain-literal"),
    pytest.param("Use ``a``X`` here.\n", [], id="glued-literal"),
]


class TestRstLint:
    """The plain Python code-block marker and nested inline literal checks."""

    @pytest.mark.parametrize(("text", "expected"), PLAIN_BLOCK_CASES)
    def test_plain_python_blocks_need_a_marker(
        self, text: str, expected: list[int]
    ) -> None:
        assert list(gen_plain_block_lines(text)) == expected

    @pytest.mark.parametrize(("text", "expected"), UNRENDERED_LITERAL_CASES)
    def test_nested_literals_do_not_render(
        self, text: str, expected: list[tuple[int, str]]
    ) -> None:
        core = pytest.importorskip("docutils.core")
        doctree = core.publish_doctree(text, settings_overrides={"report_level": 5})
        assert list(gen_unrendered_literal_lines(doctree)) == expected


BINDING_CASES = [
    pytest.param("def f(workflow: Workflow): ...\n", [1], id="param"),
    pytest.param("def f(workflow: WorkflowLike | None): ...\n", [1], id="like-param"),
    pytest.param("def f(workflow: RawWorkflow): ...\n", [], id="raw-param"),
    pytest.param("workflow = Workflow.parse(dag)\n", [1], id="parsed-local"),
    pytest.param("workflow = pipeline.workflow\n", [1], id="attribute-local"),
    pytest.param("workflow = load(dag)\n", [], id="unknown-call"),
    pytest.param("def f() -> Workflow: ...\nworkflow = f()\n", [2], id="helper-local"),
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
    pytest.param("from typing import cast\ncast('list[Any]', x)\n", 0, 1, id="unbound"),
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
        monkeypatch.setattr(_lint, "PYPROJECT", pyproject)
        monkeypatch.setattr(_lint, "PACKAGE_DIR", package)

        assert _lint._lint_escapes() == code
        typing = tomllib.loads(pyproject.read_text())["tool"]["riko"]["typing"]
        recorded = {k: v for k, v in typing.items() if not k.endswith("-lowered")}
        assert recorded == tomllib.loads(ceilings)


HELPER_CASES = [
    pytest.param({"a.py": _CHAIN + _TWO}, (), 0, id="shared-callee"),
    pytest.param({"a.py": _STEPS}, (), 1, id="same-named-methods"),
    pytest.param({"a.py": _CHAIN, "b.py": "a._b()\n"}, (), 1, id="foreign-attribute"),
    pytest.param({"a.py": _CHAIN, "b.py": "X = '_b'\n"}, (), 1, id="foreign-string"),
    pytest.param({"a.py": _CHAIN}, (("a.py", "_a"),), 0, id="kept"),
    pytest.param(
        {"a.py": _STEPS, "b.py": "import a\nclass C(a.A):\n    def _go(self): ...\n"},
        (),
        0,
        id="foreign-override",
    ),
    pytest.param(
        {"a.py": _STEPS, "b.py": "class C:\n    def _go(self): ...\n"},
        (),
        1,
        id="foreign-unrelated-method",
    ),
]

HELPER_CHECK_CASES = [
    pytest.param(0, (), 1, True, id="above-ceiling"),
    pytest.param(1, (), 0, False, id="at-ceiling"),
    pytest.param(1, (("pkg/mod.py", "_b"),), 1, False, id="stale-keep"),
]


class TestHelperLint:
    """The single-use helper ceiling lint check."""

    @pytest.mark.parametrize(("sources", "keep", "count"), HELPER_CASES)
    def test_single_use_helpers_are_counted_per_function(
        self, sources: dict[str, str], keep: tuple[tuple[str, str], ...], count: int
    ) -> None:
        paths = map_keys(Path, sources)
        kept = frozenset((Path(path), name) for path, name in keep)
        assert ChainReport.from_sources(paths, keep=kept).helper_count == count

    @pytest.mark.parametrize(("ceiling", "keep", "code", "printed"), HELPER_CHECK_CASES)
    def test_check_prints_chains_only_above_the_ceiling(
        self,
        ceiling: int,
        keep: tuple[tuple[str, str], ...],
        code: int,
        printed: bool,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        package = tmp_path / "pkg"
        package.mkdir()
        (package / "mod.py").write_text(_CHAIN, encoding="utf-8")
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(f"[tool.riko.helpers]\nchains = {ceiling}\n")
        monkeypatch.setattr(_lint, "PYPROJECT", pyproject)
        monkeypatch.setattr(_lint, "PACKAGE_DIR", package)
        monkeypatch.setattr(_lint, "KEPT_HELPERS", keep)
        chain = f"{package / 'mod.py'}:5: run -> _a -> _b"
        stale = [f"{tmp_path / path}: {name}" for path, name in keep]

        assert _lint._lint_helpers() == code
        out = capsys.readouterr().out
        assert (chain in out) is printed
        assert all(line in out for line in stale)


OWNERSHIP_CASES = [
    pytest.param("def f(s):\n    amap(str, s)\n", [2], id="dropped"),
    pytest.param("def f(s):\n    return amap(str, s)\n", [], id="returned"),
    pytest.param("def f(s):\n    yield from gen_values(s)\n", [], id="delegated"),
    pytest.param("def f(s):\n    return list(gen_values(s))\n", [2], id="listed"),
    pytest.param(
        "def f(s):\n    with closing(gen_values(s)) as v:\n        return list(v)\n",
        [],
        id="drained",
    ),
    pytest.param(
        "def f(self, run, s):\n    x = self._to_async(run, gen_values(s))\n"
        "    return self._resolve_node_inputs(x, e.map_inputs(b, amap(g, s)))\n",
        [],
        id="execution-adapters",
    ),
    pytest.param(
        "def f(s):\n    return aauto_close(amap(g, async_iter(s)))\n",
        [],
        id="nested-owners",
    ),
    pytest.param(
        "def f(self, s):\n    v = as_async(s)\n    args = (1, v)\n"
        "    return self._abuild_envelope_stream(*args)\n",
        [],
        id="splatted-to-builder",
    ),
    pytest.param(
        "def f(s):\n    v = as_async(s)\n    args = (1, v)\n    return g(*args)\n",
        [2],
        id="splatted-elsewhere",
    ),
    pytest.param(
        "def f(s):\n    x = to_async(w, s)\n    return x\n", [], id="bound-returned"
    ),
    pytest.param(
        "def f(s):\n    x = to_async(w, s)\n    print(x)\n", [2], id="bound-dropped"
    ),
    pytest.param(
        "async def f(s):\n    async for v in agen_result_envelopes(s):\n        pass\n",
        [2],
        id="bare-async-for",
    ),
    pytest.param(
        "async def f(s):\n"
        "    async with aclosing(agen_result_envelopes(s)) as e:\n"
        "        pass\n",
        [],
        id="aclosing",
    ),
    pytest.param(
        "def _register_port(run, s):\n    xs = [to_async(w, t) for t in s]\n"
        "    run.add(*xs)\n",
        [],
        id="registrar-add",
    ),
    pytest.param(
        "def _build_splitter_ports(run, t):\n    run.add(t)\n", [], id="splitter-add"
    ),
    pytest.param(_STRAY_ADD, [2], id="stray-add"),
    pytest.param(
        "class _RunStream:\n    def m(self, s):\n        self.add(s)\n",
        [],
        id="run-stream-add",
    ),
    pytest.param("def f(self, s):\n    self.seen.add(s)\n", [], id="set-add"),
    pytest.param(
        "from x import _Owned as Owned\ndef f(c):\n    return map(Owned, c)\n",
        [1, 3],
        id="owned-wrapper",
    ),
]


class TestOwnershipLint:
    """The execution-stream ownership lint check."""

    @pytest.mark.parametrize(("source", "expected"), OWNERSHIP_CASES)
    def test_streams_outside_the_ownership_rules_are_flagged(
        self, source: str, expected: list[int]
    ) -> None:
        assert [line for line, _ in gen_ownership_lines(source)] == expected

    def test_a_stray_add_names_the_registrar_rule(self) -> None:
        assert list(gen_ownership_lines(_STRAY_ADD)) == [(2, ADD_MESSAGE)]

    def test_check_exits_by_whether_issues_were_found(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        clean, flagged = tmp_path / "clean.py", tmp_path / "flagged.py"
        clean.write_text("def f(s):\n    return amap(g, s)\n", encoding="utf-8")
        flagged.write_text("def f(s):\n    amap(g, s)\n", encoding="utf-8")

        assert _lint._lint_ownership(str(clean)) == 0
        assert _lint._lint_ownership(str(flagged)) == 1
        assert "flagged.py:2 `amap`" in capsys.readouterr().out


def _issues(
    tmp_path: Path, source: str, toml: str = PYPROJECT_TOML
) -> tuple[list[str], list[int]]:
    package = tmp_path / "pkg"
    package.mkdir(exist_ok=True)
    (package / "mod.py").write_text(source, encoding="utf-8")
    config = tmp_path / "pyproject.toml"
    config.write_text(toml, encoding="utf-8")
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
    pytest.param(_try("import a") + "else:\n    import lxml\n", [6], id="try-else"),
    pytest.param(
        _try("import lxml.etree") + "else:\n    import lxml.html\n",
        [],
        id="try-else-same-module",
    ),
    pytest.param(_if(TC, "import lxml"), [], id="typing-only"),
    pytest.param("def f():\n    import lxml\n", [2], id="function-local"),
    pytest.param(REQUESTS, [], id="also-required"),
]


class TestDepsLint:
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

    def test_data_only_dependencies_need_no_import(self, tmp_path: Path) -> None:
        assert _issues(tmp_path, REQUESTS, DATA_ONLY_TOML)[0] == []

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


class TestUpgradeHookPins:
    """Pre-commit hook pins checked against uv.lock."""

    def test_hook_pin_must_match_the_lock(self, tmp_path: Path) -> None:
        """A hook that pins another ruff than uv.lock is reported at its line."""
        expected = [("8", "hook pins ruff==0.16.9 but uv.lock has 0.16.10")]
        assert _pin_issues(tmp_path, HOOKS) == expected

    def test_hooks_must_pin_each_locked_tool(self, tmp_path: Path) -> None:
        """A configuration that never pins a pinned tool is reported."""
        hooks = "repos: []\n"
        found = [message for _, message in _pin_issues(tmp_path, hooks)]
        assert found == [
            "no hook pins 'ruff'; pin it as ruff==0.16.10",
            "no hook pins 'rumdl'; pin it as rumdl==0.3.2",
        ]

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
    pytest.param(_NEGATED + _UPWARD, [], id="negated-type-checking-else-is-exempt"),
    pytest.param(_LOCAL, ["runtime"], id="function-local-upward-fails"),
]

LAYER_GRAPH_REJECTIONS = [
    pytest.param(
        {"a": {"b", "c"}, "b": {"c"}, "c": set()},
        "redundant dependency: a -> c",
        id="redundant",
    ),
    pytest.param({"a": {"b"}, "b": {"a"}}, "cyclic layer graph", id="cyclic"),
    pytest.param({"a": {"b"}}, "undeclared layers: b", id="undeclared"),
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
        assert lint_architecture(report) == (1 if targets else 0)

    def test_unclassified_fails(self, tmp_path: Path) -> None:
        root = tmp_path / "riko"
        write(root, "__init__.py", "")
        write(root, "mystery/__init__.py", "")
        report = load_architecture_report(root)
        assert report.unclassified[0].module == "riko.mystery"
        assert lint_architecture(report) == 1

    @pytest.mark.parametrize(("graph", "match"), LAYER_GRAPH_REJECTIONS)
    def test_layer_graph_validation_rejects(self, graph, match):
        with pytest.raises(InvalidArchitectureError, match=match):
            _validate_graph("test", graph)


LEGACY = [pytest.param(DAG, id="dag"), pytest.param(PIPE_DEF, id="v1")]


class TestRequireWorkflow:
    """Workflow documents accepted by the console scripts."""

    def test_require_workflow_accepts_a_workflow_document(self):
        assert require_workflow(DOCUMENT) == Workflow.parse(DAG)

    @pytest.mark.parametrize("document", LEGACY)
    def test_require_workflow_points_at_the_converter(self, document):
        with pytest.raises(InvalidPipelineError, match="build-workflow"):
            require_workflow(document)

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


MALFORMED_JSON = [
    pytest.param("{bad json", id="syntax"),
    pytest.param('{"nodes": {"a": {}, "a": {}}}', id="duplicate-key"),
]


class TestReadDocument:
    """Reading JSON inputs from paths and stdin."""

    def test_read_document_reports_a_missing_path(self, monkeypatch):
        warnings = _record_warnings(monkeypatch)
        assert read_document("no-such-flow.json") == (None, "no-such-flow")
        assert any("Unable to read input file" in warning for warning in warnings)

    @pytest.mark.parametrize("text", MALFORMED_JSON)
    def test_read_document_reports_malformed_json(self, text, tmp_path, monkeypatch):
        warnings = _record_warnings(monkeypatch)
        malformed = tmp_path / "malformed.json"
        malformed.write_text(text, encoding="utf-8")
        assert read_document(str(malformed)) == (None, "malformed")
        assert any("Unable to parse input" in warning for warning in warnings)

    def test_read_document_reports_malformed_stdin(self, monkeypatch):
        warnings = _record_warnings(monkeypatch)
        monkeypatch.setattr("sys.stdin", io.StringIO("{bad json"))
        assert read_document("-") == (None, "anonymous")
        assert any("Unable to parse input" in warning for warning in warnings)


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


class TestResolveLogLevel:
    """The manage flags select the level every riko logger inherits."""

    @pytest.mark.parametrize(("verbose", "quiet", "level"), LOG_LEVELS)
    def test_resolve_log_level(self, verbose, quiet, level):
        assert resolve_log_level(verbose, quiet) == level

    @pytest.mark.usefixtures("riko_level")
    @pytest.mark.parametrize(("args", "level"), MANAGER_LEVELS)
    def test_manager_sets_the_riko_level(self, args, level):
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
