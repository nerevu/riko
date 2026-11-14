# vim: sw=4:ts=4:expandtab
"""
Provides internal tests for the test-suite layout checks.

Covers the generated tier indexes, the ``manage lint --tests`` layout and bound
rules, and the suite's ``timeout`` backstop.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import RUN_CALL
from riko.cli import _lint
from riko.cli._gen_tier_index import GENERATED_HEADER, generate_tier_index
from riko.cli._lint_tests import (
    MERGE_LINES,
    SPLIT_LINES,
    LayoutIssue,
    gen_global_bound_issues,
    gen_inline_tables,
    gen_layout_issues,
    gen_rows_without_id,
    get_backstop,
)

_ALPHA = """
class TestAlpha:
    def test_one(self): ...


class TestAsyncAlpha:
    def test_one(self): ...


class TestBeta:
    def test_two(self): ...
"""

_BACKSTOP = 30
_BARE_PARAM = "from pytest import param\nV = [param(1)]"
_LADDER = "is not on the bound ladder: 1, 2, 3, 5, 8, 10, 15, 20, 30 s"
_MARK = "@pytest.mark.timeout(5)"

_ROW_MARK = (
    '@pytest.mark.parametrize("v", [pytest.param("x", marks=[pytest.mark.timeout(4)])])'
)

_DOC_READ = "tests never read tracked docs: {}; check it in manage lint --docs"
_STRICT = "pytest.mark.xfail(strict=True)"
_NO_RAISES = "strict xfail sets no raises=; name the exception it fails with today"
_PARAMETRIZE = '@pytest.mark.parametrize("v", {})'

_BOUND_FRAGMENTS = (
    "bound ladder",
    "must stay below",
    "outlasts",
    "tracked docs",
    "sets no timeout",
    "equals the pyproject",
    "awaits nothing",
    "sets no raises=",
)

_OPTIONS = "[tool.pytest.ini_options]\n"

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

ALPHA_ROW = "    test_alpha.py    Alpha, Beta\n"
LONG = "".join(f"class TestSubject{n:02}: ...\n" for n in range(12))

SUBJECTS = [
    ", ".join(f"Subject{n:02}" for n in range(start, start + 6)) for start in (0, 6)
]

LONG_ROWS = f"{ALPHA_ROW}    test_long.py     {SUBJECTS[0]},\n{' ' * 21}{SUBJECTS[1]}\n"
STALE = "the index is stale; run `manage codegen --tests`"


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
    pytest.param("def f(): ...\n", f"{ALPHA_ROW}    test_long.py\n", id="no-subjects"),
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

    def test_the_file_starts_with_the_generated_header(self, tmp_path: Path) -> None:
        tier = _write_suite(tmp_path) / "public"
        assert generate_tier_index(tier).startswith(f'{GENERATED_HEADER}\n\n"""\n')

    def test_a_folder_outside_the_tiers_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="'other' is not a test tier"):
            generate_tier_index(tmp_path / "other")


INDEX_FORMS = [
    pytest.param(f"{GENERATED_HEADER}\n", "", [STALE], id="header-removed"),
    pytest.param("Alpha, Beta\n", "Alpha\n", [STALE], id="hand-edited"),
]


def _messages(tests_dir: Path) -> list[tuple[str, bool]]:
    issues = gen_layout_issues(tests_dir, _BACKSTOP)
    return [(issue.message, issue.fatal) for issue in issues]


def _case(body: str, marker: str = "", prefix: str = "", kind: str = "def") -> str:
    method = f"    {marker}\n    {kind} test_one(self):\n        {body}\n"
    return f"\n{prefix}\nclass TestGamma:\n{method}"


def _write_alpha(root: Path, addition: str) -> Path:
    tests_dir = _write_suite(root)
    path = tests_dir / "public" / "test_alpha.py"
    path.write_text(path.read_text(encoding="utf-8") + addition, encoding="utf-8")
    return tests_dir


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
        _case("event.wait(timeout=0.5)"), f"wait(timeout=0.5) {_LADDER}", id="keyword"
    ),
    pytest.param(_case("thread.join(0.5)"), f"join(0.5) {_LADDER}", id="positional"),
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
    pytest.param(
        "\nclass TestGamma:\n    def setup(self):\n        thread.join(0.5)\n",
        f"join(0.5) {_LADDER}",
        id="helper-method",
    ),
    pytest.param(
        "\ndef wait():\n    thread.join(30)\n",
        "join(30) must stay below its pyproject timeout (30 s)",
        id="top-level-helper",
    ),
    pytest.param(
        _case('subprocess.run(["x"])'),
        "subprocess.run() sets no timeout=",
        id="subprocess-without-timeout",
    ),
    pytest.param(
        _case("...", "@pytest.mark.timeout(30)"),
        "timeout(30) equals the pyproject timeout; drop the marker",
        id="marker-at-backstop",
    ),
    pytest.param(
        _case("assert 1", kind="async def"),
        "test_one awaits nothing; make it a plain def",
        id="idle-async",
    ),
    pytest.param(_case("assert 0", f"@{_STRICT}"), _NO_RAISES, id="xfail-decorator"),
    pytest.param(
        _case(
            "...", _PARAMETRIZE.format(f'[pytest.param(1, marks={_STRICT}, id="a")]')
        ),
        _NO_RAISES,
        id="xfail-row-mark",
    ),
    pytest.param(
        _case("...", prefix=f"X_PENDING = {_STRICT}"), _NO_RAISES, id="xfail-constant"
    ),
]


CLEAN_BOUND_CASES = [
    pytest.param(_case("async def f(): await async_sleep(3600)", _MARK), id="nested"),
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
    pytest.param(_case('subprocess.run(["x"], timeout=5)'), id="subprocess-timeout"),
    pytest.param(_case('subprocess.run(["x"], **options)'), id="subprocess-splat"),
    pytest.param(_case("...", "@pytest.mark.timeout(20)"), id="marker-below-backstop"),
    pytest.param(_case("[x async for x in agen()]", kind="async def"), id="async-for"),
    pytest.param(_case("async with lock: ...", kind="async def"), id="async-with"),
    pytest.param(
        _case("assert 0", "@pytest.mark.xfail(strict=True, raises=AssertionError)"),
        id="xfail-raises",
    ),
]


HELPER_BOUND_CASES = [
    pytest.param(
        "def wait():\n    t.join(timeout=0.5)\n",
        [f"join(timeout=0.5) {_LADDER}"],
        id="off-ladder",
    ),
    pytest.param("def wait():\n    t.join(timeout=1)\n", [], id="on-ladder"),
    pytest.param(
        'subprocess.run(["x"])\n',
        ["subprocess.run() sets no timeout="],
        id="subprocess",
    ),
    pytest.param(f"X_PENDING = {_STRICT}\n", [_NO_RAISES], id="xfail-constant"),
]


SITE_CASES = [
    pytest.param(_case("...", _PARAMETRIZE.format("[\n1,\n]")), 1, 0, id="multi-line"),
    pytest.param(
        _case("...", _PARAMETRIZE.format('[1], ids=["a"]')), 0, 0, id="one-line-inline"
    ),
    pytest.param(
        _case("...", _PARAMETRIZE.format("V"), "V = [\n    1,\n]"),
        0,
        0,
        id="module-table",
    ),
    pytest.param(_case("...", prefix="V = [pytest.param(1)]"), 0, 1, id="without-id"),
    pytest.param(_case("...", "", 'V = [pytest.param(1, id="a")]'), 0, 0, id="with-id"),
    pytest.param(_case("...", prefix=_BARE_PARAM), 0, 1, id="bare-param-without-id"),
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
        assert (message, True) in _messages(_write_alpha(tmp_path, addition))

    @pytest.mark.parametrize("addition", CLEAN_BOUND_CASES)
    def test_bounds_and_doc_reads_outside_the_rules_pass(
        self, tmp_path: Path, addition: str
    ) -> None:
        messages = [
            message for message, _ in _messages(_write_alpha(tmp_path, addition))
        ]
        assert not [m for m in messages if any(f in m for f in _BOUND_FRAGMENTS)]

    @pytest.mark.parametrize(("source", "expected"), HELPER_BOUND_CASES)
    def test_shared_helper_modules_keep_the_bound_rules(
        self, tmp_path: Path, source: str, expected: list[str]
    ) -> None:
        tests_dir = _write_suite(tmp_path, **{"_helper.py": source})
        assert [message for message, _ in _messages(tests_dir)] == expected

    @pytest.mark.parametrize(("addition", "tables", "rows"), SITE_CASES)
    def test_inline_tables_and_rows_without_ids_are_counted(
        self, tmp_path: Path, addition: str, tables: int, rows: int
    ) -> None:
        tests_dir = _write_alpha(tmp_path, addition)
        found = (gen_inline_tables(tests_dir), gen_rows_without_id(tests_dir))
        assert tuple(len(list(sites)) for sites in found) == (tables, rows)

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
        monkeypatch.setattr(_lint, "gen_inline_tables", lambda _: iter(()))
        monkeypatch.setattr(_lint, "gen_rows_without_id", lambda _: iter(()))
        monkeypatch.setattr(_lint, "ratchet_ceiling", lambda *_: 0)

        assert str(issue) == line
        assert _lint._lint_tests() == code
        assert line in capsys.readouterr().out

    def test_short_files_get_advice_not_failure(self, tmp_path: Path) -> None:
        tests_dir = _write_suite(tmp_path)
        (tests_dir / "public" / "test_alpha.py").write_text(_ALPHA, encoding="utf-8")
        messages = _messages(tests_dir)
        assert [fatal for _, fatal in messages] == [False]
        assert "consider merging" in messages[0][0]


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


_RUN_CALLS = [
    pytest.param("run(main)\n", True, id="leading"),
    pytest.param("total = run(anext, stream)\n", True, id="assigned"),
    pytest.param("[e.value for e in run(alist, stream)]\n", True, id="nested"),
    pytest.param("header = 'def run(flow):'\n", False, id="definition"),
    pytest.param("execution.run(plan)\n", False, id="method"),
    pytest.param("arun(plan)\n", False, id="suffix"),
    pytest.param("run_bridged(f.close)\n", False, id="prefix"),
]


class TestDoctestSkips:
    @pytest.mark.parametrize(("source", "skipped"), _RUN_CALLS)
    def test_run_call_is_found_anywhere_on_the_line(
        self, source: str, skipped: bool
    ) -> None:
        """Without the async extra, every bare ``run(`` call example is skipped."""
        assert bool(RUN_CALL.search(source)) is skipped
