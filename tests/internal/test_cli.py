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

from riko.base._paths import ROOT_DIR
from riko.base.exceptions import InvalidArchitectureError, InvalidPipelineError
from riko.cli import (
    _codegen,
    _docs,
    _document,
    _import_commands,
    _lint,
    _test,
    _upgrade,
)
from riko.cli._coverage import build_ceiling_text
from riko.cli._docs import gen_stale_path_citations, gen_stale_test_citations
from riko.cli._docstyle import (
    gen_docstring_issues,
    gen_example_prose,
    summary_leads_with_output,
)
from riko.cli._document import read_document, require_workflow
from riko.cli._gen_tier_index import INDEX_HEADER, generate_tier_index
from riko.cli._lint_basenames import BasenameIssue, gen_basename_issues
from riko.cli._lint_bindings import gen_binding_issues, gen_binding_lines
from riko.cli._lint_canonical_imports import _iter_issues as canonical_issues
from riko.cli._lint_deps import (
    gen_hook_pin_issues,
    gen_import_issues,
    gen_runtime_imports,
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
from riko.cli._lint_tests import (
    MERGE_LINES,
    SPLIT_LINES,
    LayoutIssue,
    gen_layout_issues,
)
from riko.cli._logging import exception_hook, resolve_log_level
from riko.cli._upgrade import _pin_hooks
from riko.cli.manage import manager
from riko.cli.runpipe import run_target
from riko.definitions._workflow_definition import Workflow
from riko.runtime._compile import compile_workflow
from tests._workflows import DAG, DAG_PATH, PIPE_DEF

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator


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
            (["--tests"], ["tests"]),
            (["--all"], ["config", "names", "api", "tests"]),
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


_MODULE_EXAMPLE = '"""\nDoes.\n\n>>> 1\n1\n"""\n'
_PRIVATE_MODULE = ["private module without a public API carries a module example"]
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


CITATION_SCANS = [
    pytest.param(
        gen_stale_test_citations,
        "public/test_{}.py",
        "tests/public/test_kept.py",
        id="tests",
    ),
    pytest.param(gen_stale_path_citations, "riko/{}.py", "riko/kept.py", id="paths"),
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

    def test_phase_codes_are_checked(self, tmp_path: Path) -> None:
        source = tmp_path / "mod.py"
        source.write_text(
            'REASON = "owned by R5C: write is still a sink module"\n'
            "# see R4B.2 and P10, not R2D2 or PR9\n",
            encoding="utf-8",
        )
        found = [(issue.lineno, issue.found) for issue in gen_term_issues(source)]
        assert found == [(1, "R5C"), (2, "R4B.2"), (2, "P10")]

    def test_removed_ext_paths_are_checked(self, tmp_path: Path) -> None:
        source = tmp_path / "mod.py"
        source.write_text(
            "# import from riko.ext.registry, not riko.ext.modules\n"
            "# riko.ext.names is gone too\n",
            encoding="utf-8",
        )
        found = [(issue.lineno, issue.found) for issue in gen_term_issues(source)]
        assert found == [(1, "riko.ext.registry"), (2, "riko.ext.names")]

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


_INIT = f'"""\nProvides tests.\n\n{INDEX_HEADER}\n\n"""\n'
NO_INDEX = f"the docstring has no {INDEX_HEADER!r} block"

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
    init = tier / "__init__.py"
    init.write_text(_INIT, encoding="utf-8")
    (tier / "test_alpha.py").write_text(_ALPHA + "\n" * MERGE_LINES, encoding="utf-8")
    init.write_text(generate_tier_index(tier), encoding="utf-8")

    for name, text in files.items():
        path = tests_dir / name.replace("__", "/")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    return tests_dir


def _messages(tests_dir: Path) -> list[tuple[str, bool]]:
    return [(issue.message, issue.fatal) for issue in gen_layout_issues(tests_dir)]


STALE = "the index is stale; run `manage codegen --tests`"
ALPHA_ROW = "    test_alpha.py    Alpha, Beta\n"
LONG = "".join(f"class TestSubject{n:02}: ...\n" for n in range(12))
SUBJECTS = [
    ", ".join(f"Subject{n:02}" for n in range(start, start + 6)) for start in (0, 6)
]
LONG_ROWS = f"{ALPHA_ROW}    test_long.py     {SUBJECTS[0]},\n{' ' * 21}{SUBJECTS[1]}\n"
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

    def test_a_docstring_without_an_index_header_is_refused(
        self, tmp_path: Path
    ) -> None:
        tier = _write_suite(tmp_path) / "public"
        (tier / "__init__.py").write_text('"""Provides tests."""\n')

        with pytest.raises(ValueError, match="has no 'Index"):
            generate_tier_index(tier)


INDEX_FORMS = [
    pytest.param(None, [NO_INDEX], id="no-index"),
    pytest.param("    test_alpha.py    Alpha\n", [STALE], id="hand-edited"),
    pytest.param("    test_alpha.py    Alpha, Beta\n", [], id="current"),
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
        ],
    )
    def test_in_file_departures_fail(
        self, tmp_path: Path, addition: str, message: str
    ) -> None:
        tests_dir = _write_suite(tmp_path)
        path = tests_dir / "public" / "test_alpha.py"
        path.write_text(path.read_text(encoding="utf-8") + addition, encoding="utf-8")
        assert (message, True) in _messages(tests_dir)

    @pytest.mark.parametrize(("rows", "expected"), INDEX_FORMS)
    def test_the_index_must_match_its_generated_form(
        self, tmp_path: Path, rows: str | None, expected: list[str]
    ) -> None:
        tests_dir = _write_suite(tmp_path)
        index = "Provides tests.\n" if rows is None else f"{INDEX_HEADER}\n\n{rows}"
        (tests_dir / "public" / "__init__.py").write_text(f'"""\n{index}"""\n')
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
        monkeypatch.setattr(_lint, "gen_layout_issues", lambda _: [issue])

        assert str(issue) == line
        assert _lint._lint_tests() == code
        assert line in capsys.readouterr().out

    def test_short_files_get_advice_not_failure(self, tmp_path: Path) -> None:
        tests_dir = _write_suite(tmp_path)
        (tests_dir / "public" / "test_alpha.py").write_text(_ALPHA, encoding="utf-8")
        messages = _messages(tests_dir)
        assert [fatal for _, fatal in messages] == [False]
        assert "consider merging" in messages[0][0]


_SHARED = "basename is shared; rename one or allowlist the pair"
_STALE = "allowlisted basename is no longer duplicated; remove it"
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
        [("x.py", ("pkg/a/x.py",), _STALE)],
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


def _if(test: str, body: str = "import a", orelse: str = "") -> str:
    tail = f"else:\n    {orelse}\n" if orelse else ""
    return f"if {test}:\n    {body}\n{tail}"


TC, NOT_TC = "TYPE_CHECKING", "not TYPE_CHECKING"
ABSOLUTE = "import a.b\nfrom c import d\nfrom . import e\n"
LOCAL = "def f():\n" + indent(_if(TC) + "import b\n", "    ")
ELIF = _if(TC, "pass") + "elif flag:\n    import a\n"
TRY = "try:\n    import a\nexcept ImportError:\n    pass\n"
REQUESTS = "import requests\n"
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
ONLY = (
    "'python-dateutil' is a [project] dependency that nothing imports at run time; "
    "import it outside TYPE_CHECKING or move it to a dependency group"
)
REQUIREMENT_CASES = [
    pytest.param(f"{REQUESTS}import dateutil\n", [], id="both-used"),
    pytest.param(REQUESTS + _if(TC, "import dateutil"), [ONLY], id="typing-only"),
    pytest.param(REQUESTS + _if(NOT_TC, "import dateutil"), [], id="not-type-checking"),
]

LXML = "import lxml\n"


def _try(body: str, caught: str = "ImportError", handler: str = "pass") -> str:
    return f"try:\n    {body}\nexcept {caught}:\n    {handler}\n"


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
