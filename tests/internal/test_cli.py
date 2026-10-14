# vim: sw=4:ts=4:expandtab
"""Provides internal tests for the manage commands, lint checks, and workflow input."""

from __future__ import annotations

import io
import json
import tomllib
from datetime import date, timedelta
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from click.testing import CliRunner

from riko.base._paths import ROOT_DIR
from riko.base.exceptions import InvalidArchitectureError, InvalidPipelineError
from riko.cli import _codegen, _import_commands, _lint, _test, _upgrade, _workflow
from riko.cli._coverage import build_ceiling_text
from riko.cli._docstyle import summary_leads_with_output
from riko.cli._lint_canonical_imports import _iter_issues as canonical_issues
from riko.cli._lint_deps import (
    gen_dependency_issues,
    gen_hook_pin_issues,
    gen_import_sites,
    get_locked_version,
)
from riko.cli._lint_import_architecture import (
    _validate_graph,
    load_architecture_report,
    render_architecture,
)
from riko.cli._lint_literals import gen_literal_issues
from riko.cli._lint_relative_imports import _iter_issues as relative_issues
from riko.cli._lint_terms import BANNED_TERMS, BannedTerm, gen_term_issues
from riko.cli._lint_tests import LayoutIssue, format_layout_issue, gen_layout_issues
from riko.cli._upgrade import _pin_hooks
from riko.cli._workflow import read_document, require_workflow
from riko.cli.manage import manager
from riko.definitions._workflow import Workflow
from tests._workflows import DAG, DAG_PATH, PIPE_DEF

if TYPE_CHECKING:
    from collections.abc import Callable


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
            (["--all"], ["config", "names", "api"]),
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


SYNC = ["uv", "sync", "--active", "--locked", "--group", "dev", "--all-extras"]


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
    monkeypatch.setattr(_lint, "_twine_check", lambda: calls.append("dist") or 0)
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
        monkeypatch.setattr(_lint, "gen_dependency_issues", lambda *_: [])
        monkeypatch.setattr(_lint, "gen_hook_pin_issues", lambda *_: [])
        monkeypatch.setattr(_lint, "format_dependency_issue", str)
        assert _lint._lint_deps() == 0

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
                    "tests",
                    "actions",
                    "yaml",
                    "imports",
                ],
            ),
            (
                ["--terms", "--literals", "--deps", "--tests"],
                ["terms", "literals", "deps", "tests"],
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


PYPROJECT = Path(__file__).parents[2] / "pyproject.toml"
SCRIPTS: dict[str, str] = tomllib.loads(PYPROJECT.read_text())["project"]["scripts"]


def _coverage_report(root: Path, uncovered: int) -> Path:
    report = root / "coverage.json"
    report.write_text(json.dumps({"totals": {"missing_lines": uncovered}}))
    return report


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

    def test_a_table_without_a_ceiling_line_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="has no uncovered line"):
            build_ceiling_text("[tool.riko.coverage]\nother = 1\n", 5)

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
        calls: list[list[str]] = []
        monkeypatch.setattr(_test, "_pytest", "pytest")
        monkeypatch.setattr(_test, "check_call", calls.append)
        monkeypatch.setattr(_test, "_ratchet_coverage", lambda _: 0)

        result = CliRunner().invoke(_test.TEST_COMMAND, args)
        command = " ".join(calls[0])
        assert result.exit_code == 0
        assert present in command
        assert not absent or absent not in command

    def test_ratchet_refuses_a_partial_run(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        folders: list[str] = []
        monkeypatch.setattr(_test, "mkdtemp", lambda: folders.append("made") or "")

        result = CliRunner().invoke(_test.TEST_COMMAND, ["--ratchet", "tests/public"])
        assert result.exit_code == 2
        assert "measures the whole suite" in result.output
        assert folders == []


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


class TestDocstyle:
    """Docstring summary checks."""

    def test_docstring_summary_output_lead_detection(self) -> None:
        assert summary_leads_with_output("Returns the parsed response body.")
        assert not summary_leads_with_output("Parses the response body.")


STANDARD = ROOT_DIR / "_docs" / "DOCUMENTATION_STANDARD.md"


def _reserved_terms_section() -> str:
    text = STANDARD.read_text(encoding="utf-8")
    return text.split("## Reserved terms", 1)[1].split("\n## ", 1)[0].lower()


class TestTermLint:
    """The reserved-terms lint check."""

    @pytest.mark.parametrize("term", BANNED_TERMS, ids=lambda term: term.phrase)
    def test_every_banned_phrase_has_a_reserved_terms_ruling(
        self, term: BannedTerm
    ) -> None:
        assert term.phrase.lower() in _reserved_terms_section()

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

    def test_prose_files_are_checked_except_the_changelog(self, tmp_path: Path) -> None:
        (tmp_path / "GUIDE.rst").write_text("Run a sub-pipeline.\n", encoding="utf-8")
        (tmp_path / "CHANGES.rst").write_text("Run a sub-pipeline.\n", encoding="utf-8")
        found = [issue.path.name for issue in gen_term_issues(tmp_path)]
        assert found == ["GUIDE.rst"]


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


DISTRIBUTIONS = {
    "dateutil": ["python-dateutil"],
    "lxml": ["lxml"],
    "requests": ["requests"],
    "typing_extensions": ["typing_extensions"],
}


PYPROJECT_TOML = """
[project]
dependencies = ["python-dateutil>=2", "requests"]

[project.optional-dependencies]
perf = ["lxml"]

[dependency-groups]
lint = ["types-requests", {include-group = "test"}]
"""


def _issues(tmp_path: Path, source: str, pyproject: str = PYPROJECT_TOML) -> list[str]:
    package = tmp_path / "pkg"
    package.mkdir(exist_ok=True)
    (package / "mod.py").write_text(source, encoding="utf-8")
    config = tmp_path / "pyproject.toml"
    config.write_text(pyproject, encoding="utf-8")
    issues = gen_dependency_issues(package, config, DISTRIBUTIONS)
    return [issue.message for issue in issues]


_INDEX = """
Index (file, then the subjects it owns, in file order):

    test_alpha.py    Alpha, Beta
"""

_ALPHA = """
class TestAlpha:
    def test_one(self): ...


class TestAsyncAlpha:
    def test_one(self): ...


class TestBeta:
    def test_two(self): ...
"""


def _write_suite(root: Path, **files: str) -> Path:
    tests_dir = root / "tests"
    tier = tests_dir / "public"
    tier.mkdir(parents=True)
    (tier / "__init__.py").write_text(f'"""{_INDEX}"""\n', encoding="utf-8")
    (tier / "test_alpha.py").write_text(_ALPHA * 40, encoding="utf-8")

    for name, text in files.items():
        path = tests_dir / name.replace("__", "/")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    return tests_dir


def _messages(tests_dir: Path) -> list[tuple[str, bool]]:
    return [(issue.message, issue.fatal) for issue in gen_layout_issues(tests_dir)]


class TestLayoutLint:
    """The indexed test-layout lint check."""

    def test_an_indexed_suite_passes(self, tmp_path: Path) -> None:
        assert _messages(_write_suite(tmp_path)) == []

    @pytest.mark.parametrize(
        ("files", "message"),
        [
            pytest.param(
                {"public__test_gamma.py": _ALPHA},
                "test_gamma.py has no row in __init__.py",
                id="unindexed-file",
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
            pytest.param(
                "\nclass TestGamma: ...\n",
                "TestGamma names no subject in the index row",
                id="unlisted-class",
            ),
            pytest.param(
                "\nfrom riko.x import _hidden\n",
                "public tests import supported names: _hidden",
                id="private-import",
            ),
        ],
    )
    def test_in_file_departures_fail(
        self, tmp_path: Path, addition: str, message: str
    ) -> None:
        tests_dir = _write_suite(tmp_path)
        path = tests_dir / "public" / "test_alpha.py"
        path.write_text(path.read_text(encoding="utf-8") + addition, encoding="utf-8")
        assert (message, True) in _messages(tests_dir)

    @pytest.mark.parametrize(
        ("rows", "message"),
        [
            pytest.param(None, "the docstring has no test index", id="no-index"),
            pytest.param(
                "    test_alpha.py    Alpha, Beta, Alpha\n",
                "Alpha is indexed under both test_alpha.py and test_alpha.py",
                id="duplicate-subject",
            ),
            pytest.param(
                "    test_alpha.py    Alpha, Beta\n    test_ghost.py    Ghost\n",
                "test_ghost.py is indexed but does not exist",
                id="missing-file",
            ),
        ],
    )
    def test_index_departures_fail(
        self, tmp_path: Path, rows: str | None, message: str
    ) -> None:
        tests_dir = _write_suite(tmp_path)
        header = "Index (file, then the subjects it owns, in file order):\n\n"
        index = "Provides tests." if rows is None else f"{header}{rows}"
        (tests_dir / "public" / "__init__.py").write_text(f'"""{index}"""\n')
        assert (message, True) in _messages(tests_dir)

    def test_long_files_get_advice_to_split(self, tmp_path: Path) -> None:
        tests_dir = _write_suite(tmp_path)
        (tests_dir / "public" / "test_alpha.py").write_text(_ALPHA * 400)
        messages = _messages(tests_dir)
        assert [fatal for _, fatal in messages] == [False]
        assert "split its largest index row" in messages[0][0]

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
        monkeypatch.setattr(_lint, "gen_layout_issues", lambda _: [issue])

        assert format_layout_issue(issue) == line
        assert _lint._lint_tests() == code
        assert line in capsys.readouterr().out

    def test_short_files_get_advice_not_failure(self, tmp_path: Path) -> None:
        tests_dir = _write_suite(tmp_path)
        (tests_dir / "public" / "test_alpha.py").write_text(_ALPHA, encoding="utf-8")
        messages = _messages(tests_dir)
        assert [fatal for _, fatal in messages] == [False]
        assert "consider merging" in messages[0][0]


def _unguarded(name: str) -> str:
    return f"'{name}' is imported unguarded but is not a [project] dependency"


def _try_import(*names: str) -> str:
    imports = "".join(f"    import {name}\n" for name in names)
    return f"try:\n{imports}except ImportError:\n    pass\n"


IMPORTS = "import requests\nimport dateutil\n"
TYPING = "import typing_extensions\n"
FROM_DATEUTIL = f"import requests\nfrom dateutil import parser\n{TYPING}"
LOCAL_TYPING = f"{IMPORTS}def f():\n    {TYPING}"
TRY_UJSON = IMPORTS + _try_import("lxml", "ujson")
TRY_HTTPX = IMPORTS + _try_import("httpx")
TYPE_ONLY = f"import requests\nif TYPE_CHECKING:\n    import dateutil\n    {TYPING}"
UNGUARDED = [_unguarded("typing_extensions")]
UNDECLARED = ["'ujson' is imported in a try block but declared nowhere"]
UNUSED = ["'python-dateutil' is a [project] dependency that nothing imports"]
STUB = ["'types-lxml' is a typing stub; declare it in a dependency group"]
PERF = 'perf = ["lxml"]'
STUB_TOML = PYPROJECT_TOML.replace(PERF, 'perf = ["lxml", "types-lxml"]')
HTTPX_TOML = PYPROJECT_TOML.replace(PERF, 'perf = ["httpx"]')
DEPENDENCY_ISSUES = [
    pytest.param(FROM_DATEUTIL, PYPROJECT_TOML, UNGUARDED, id="unguarded-transitive"),
    pytest.param(LOCAL_TYPING, PYPROJECT_TOML, UNGUARDED, id="function-local"),
    pytest.param(TRY_UJSON, PYPROJECT_TOML, UNDECLARED, id="try-undeclared"),
    pytest.param(TYPE_ONLY, PYPROJECT_TOML, UNUSED, id="type-checking-only"),
    pytest.param(IMPORTS, PYPROJECT_TOML, [], id="stub-in-group-ok"),
    pytest.param(IMPORTS, STUB_TOML, STUB, id="stub-in-extra"),
    pytest.param(TRY_HTTPX, HTTPX_TOML, [], id="uninstalled-extra-name"),
]


class TestDependencyLint:
    """The declared-dependencies lint check."""

    def test_import_sites_record_their_guard(self, tmp_path: Path) -> None:
        """Each third-party import is tagged by the strongest statement guarding it."""
        package = tmp_path / "pkg"
        package.mkdir()
        (package / "mod.py").write_text(
            "import os\n"
            "import requests\n"
            "from . import sibling\n"
            "try:\n"
            "    import lxml\n"
            "except ImportError:\n"
            "    pass\n"
            "if TYPE_CHECKING:\n"
            "    try:\n"
            "        import dateutil\n"
            "    except ImportError:\n"
            "        pass\n",
            encoding="utf-8",
        )
        sites = [(site.name, site.guard) for site in gen_import_sites(package)]
        expected = [
            ("requests", "none"),
            ("lxml", "try"),
            ("dateutil", "type_checking"),
        ]
        assert sites == expected

    @pytest.mark.parametrize(("source", "pyproject", "expected"), DEPENDENCY_ISSUES)
    def test_dependency_issues(
        self, tmp_path: Path, source: str, pyproject: str, expected: list[str]
    ) -> None:
        """Each import is checked against the declaration its guard requires."""
        assert _issues(tmp_path, source, pyproject) == expected


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


class TestImportArchitectureLint:
    """The import-architecture lint check."""

    def test_architecture(self, tmp_path: Path) -> None:
        root = tmp_path / "riko"
        write(root, "__init__.py", "")
        write(root, "types/__init__.py", "")
        write(root, "types/a.py", "from riko.runtime.b import thing\n")
        write(root, "runtime/__init__.py", "")
        write(root, "runtime/b.py", "thing = 1\n")
        report = load_architecture_report(root)
        assert not report.unclassified
        assert len(report.violations) == 1
        assert "types > {runtime}" in render_architecture(report)

    def test_type_checking_is_exempt(self, tmp_path: Path) -> None:
        root = tmp_path / "riko"
        write(root, "__init__.py", "")
        write(root, "types/__init__.py", "")
        write(
            root,
            "types/a.py",
            (
                "from typing import TYPE_CHECKING\n"
                "if TYPE_CHECKING:\n"
                "    from riko.runtime.b import thing\n"
            ),
        )
        write(root, "runtime/__init__.py", "")
        write(root, "runtime/b.py", "thing = 1\n")
        assert not load_architecture_report(root).violations

    def test_function_local_upward_import_fails(self, tmp_path: Path) -> None:
        root = tmp_path / "riko"
        write(root, "__init__.py", "")
        write(root, "types/__init__.py", "")
        write(
            root,
            "types/a.py",
            "def load():\n    from riko.runtime.b import thing\n\n    return thing\n",
        )
        write(root, "runtime/__init__.py", "")
        write(root, "runtime/b.py", "thing = 1\n")
        report = load_architecture_report(root)
        assert len(report.violations) == 1
        assert report.violations[0].target_label == "runtime"

    def test_unclassified_fails(self, tmp_path: Path) -> None:
        root = tmp_path / "riko"
        write(root, "__init__.py", "")
        write(root, "mystery/__init__.py", "")
        report = load_architecture_report(root)
        assert report.unclassified[0].module == "riko.mystery"


class TestValidateGraph:
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


WORKFLOW = json.loads(Workflow.parse(DAG).serialize())
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


def _record_warnings(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    warnings: list[str] = []
    warning = lambda msg, *args: warnings.append(msg % args)
    monkeypatch.setattr(_workflow.logger, "warning", warning)
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


class TestTimeouts:
    def test_a_timeout_fails_an_xfail_test(
        self, pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        An xfail test that ends by its timeout is reported as failed.

        Runs in a subprocess so the signal never fires under this process's
        coverage tracer.
        """
        monkeypatch.setenv("PYTHONPATH", str(ROOT_DIR))
        pytester.makepyfile(_TIMEOUT_SUITE)
        result = pytester.runpytest_subprocess(
            "-p", "tests._timeouts", "-p", "no:cacheprovider", "-o", "addopts="
        )
        result.assert_outcomes(failed=1, xfailed=1)
        result.stdout.fnmatch_lines(["*test_hangs hit its timeout*never ends*"])
