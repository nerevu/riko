"""
Smoke-tests overlap_scan.py's sections on a throwaway repository.

Run after editing the tidy scripts:

    uv run --active pytest .claude/skills/tidy/test_overlap_scan.py
"""

from __future__ import annotations

import ast
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


def rewind(stream):
    """
    Rewinds a stream.

    >>> rewind(StringIO("a"))
    0
    >>> rewind(StringIO("b"))
    0
    >>> rewind(StringIO("c"))
    0
    >>> rewind(StringIO("d"))
    0
    >>> rewind(StringIO("e"))
    0
    >>> rewind(StringIO("f"))
    0
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
LAST = 1


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
        assert shared() == shared() == LAST
"""
SCRIPT = """\
from tests import run_module, run_python


class TestRunPipe:
    def test_spawns(self):
        assert run_module("runpipe", "demo")

    def test_entry_point(self):
        assert run_module("runpipe", "demo", entry_point=True)

    def test_module_form(self):
        \"\"\"The ``python -m`` form runs.\"\"\"
        assert run_module("runpipe", "demo")


class TestScriptImports:
    def test_a_script_imports_riko(self, tmp_path):
        assert run_python("probe.py", cwd=tmp_path)
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
    pytest.param(
        "placement", "TestReiteration: Reiteration is not a riko", id="foreign-subject"
    ),
    pytest.param("doctest-balance", "ticks: 6 examples; tables:", id="balance"),
    pytest.param("processes", "TestRunPipe::test_spawns: starts", id="process"),
    pytest.param("doctest-messages", "'must be a string' -> riko", id="message"),
    pytest.param("assertless", "TestTicks::test_ticks_inline: no", id="assertless"),
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


PARAMETER_NAME = """\
import pytest


class TestOther:
    @pytest.mark.parametrize("ticks", [pytest.param(7, id="seven")])
    def test_counts(self, ticks):
        assert ticks == 7
"""
SHORT_FRAGMENT = """\
import pytest

FORMS = [pytest.param(ValueError, "a", id="a")]


class TestForms:
    @pytest.mark.parametrize(("error", "match"), FORMS)
    def test_raises(self, error, match):
        with pytest.raises(error, match=match):
            parse()
"""
LONE_PIECE = """\
class TestMessages:
    def test_message(self, key, suffix):
        assert describe(key) == f"{key} must be a string{suffix} in every settings file"
"""
SHARED_STDLIB = """\
from io import StringIO

import pytest


class TestStreams:
    @pytest.mark.parametrize("text", [pytest.param("a", id="a")])
    def test_reads(self, text):
        assert StringIO(text).read() == text
"""
HELPER_CHAIN = """\
def _load(value):
    return value


def _build(value):
    return _load(value)


class TestTicks:
    def test_builds(self):
        assert _build(1) == ticks(1)


class TestRewind:
    def test_builds(self):
        assert _build(2) == rewind(2)


class TestGizmo:
    def test_loads(self):
        assert _load(Gizmo())
"""
HELPER_SUBJECT = """\
async def _afeed(stream):
    return _drain(stream)


def _drain(stream):
    return rewind(stream)


class TestAsyncRewind:
    async def test_feeds(self):
        assert await _afeed("a") == 0
"""
FALSE_LEADS = [
    pytest.param(
        "doctest-balance", PARAMETER_NAME, "doctest ticks", id="parameter-name"
    ),
    pytest.param(
        "doctest-balance", SHARED_STDLIB, "doctest rewind", id="shared-stdlib-callee"
    ),
    pytest.param("doctest-raises", SHORT_FRAGMENT, "TestForms", id="short-fragment"),
    pytest.param(
        "doctest-messages", LONE_PIECE, "TestMessages", id="lone-fstring-piece"
    ),
    pytest.param("placement", HELPER_CHAIN, "_load:", id="helper-called-by-helper"),
    pytest.param(
        "placement", HELPER_SUBJECT, "never names", id="subject-named-in-helper"
    ),
]


@pytest.mark.parametrize(("section", "source", "fragment"), FALSE_LEADS)
def test_a_coincidental_match_is_not_a_lead(tmp_path, section, source, fragment):
    (tmp_path / "riko" / "base").mkdir(parents=True)
    (tmp_path / "tests" / "internal").mkdir(parents=True)
    (tmp_path / "riko" / "_config.py").write_text(CONFIG)
    (tmp_path / "riko" / "base" / "_api_surface.py").write_text(SURFACE)
    (tmp_path / "tests" / "internal" / "test_leads.py").write_text(source)
    found = overlap_scan.build_sections(tmp_path, 2)[section]
    assert not [text for text, _ in found if fragment in text]


CHAIN_LOAD = "def _load(value):\n    return value\n\n\n"
CHAIN_BUILD = "def _build(value):\n    return _load(value)\n\n\n"
CHAIN_OTHER = "class TestOther:\n    def test_other(self):\n        assert True\n\n\n"
CHAIN_USER = "class TestX:\n    def test_x(self):\n        assert _build(1)\n"
CALLER_CHAINS = [
    pytest.param(
        CHAIN_LOAD + CHAIN_OTHER + CHAIN_BUILD + CHAIN_USER,
        [("_load", "_build", 1, "not directly above its caller _build")],
        id="caller-in-place",
    ),
    pytest.param(
        CHAIN_LOAD + CHAIN_BUILD + CHAIN_OTHER + CHAIN_USER,
        [
            ("_load", "TestX", 1, "not directly above its one user TestX"),
            ("_build", "TestX", 5, "not directly above its one user TestX"),
        ],
        id="caller-misplaced",
    ),
]


@pytest.mark.parametrize(("source", "expected"), CALLER_CHAINS)
def test_a_helper_called_by_a_helper_targets_its_caller_in_place(source, expected):
    tree = ast.parse(source)
    file = overlap_scan.TestFile(Path("test_chain.py"), "internal", tree, source)
    assert overlap_scan.get_misplaced(file) == expected


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


def test_a_constant_stays_at_the_top(report):
    assert not [text for text in report["placement"] if "LAST" in text]


def test_a_commented_row_is_never_joined(report):
    assert not [text for text in report["rows"] if "commented" in text]


def test_a_process_with_a_stated_reason_is_not_a_lead(report):
    assert len(report["processes"]) == 1, report["processes"]


def test_a_run_python_probe_is_a_functional_marker(report):
    assert not report["tier"]


def test_a_concept_named_class_is_not_an_unnamed_subject(report):
    assert not [text for text in report["placement"] if "never names Reit" in text]


CONCEPT_CLASSES = frozenset(
    {
        "TestOverloadTypes",
        "TestTimeouts",
        "TestWorkflowFields",
        "TestWorkflowFixtures",
        "TestRequireGuards",
        "TestAsyncOperatorLaziness",
        "TestSyncPipeAsyncInput",
        "TestImportSurface",
        "TestConfigCodegen",
        "TestMeza",
        "TestExamplePipelines",
        "TestConsoleScripts",
        "TestDoctestSkips",
        "TestCapabilityFlags",
        "TestBareDecorator",
    }
)


def test_the_concept_classes_come_from_the_suite_docstring():
    root = Path(__file__).resolve().parents[3]
    assert overlap_scan.load_concept_classes(root) == CONCEPT_CLASSES


KNOWN_SUBJECTS = [
    pytest.param(
        "riko/_pool.py",
        "class _ThreadBudget:\n    pass\n",
        "TestThreadBudget",
        id="private-class",
    ),
    pytest.param(
        "riko/_values.py", "XML_PARSER = None\n", "TestXmlParser", id="constant-case"
    ),
    pytest.param(
        "riko/modules/exchangerate.py", "", "TestExchangeRate", id="joined-module"
    ),
    pytest.param(
        "riko/_iterators.py",
        "async def async_merge(sources):\n    pass\n",
        "TestAsyncMerge",
        id="async-function",
    ),
]


@pytest.mark.parametrize(("path", "source", "name"), KNOWN_SUBJECTS)
def test_a_subject_named_for_a_riko_name_is_not_foreign(tmp_path, path, source, name):
    (tmp_path / "riko" / "base").mkdir(parents=True)
    (tmp_path / "riko" / "modules").mkdir()
    (tmp_path / "tests" / "internal").mkdir(parents=True)
    (tmp_path / "riko" / "_config.py").write_text(CONFIG)
    (tmp_path / "riko" / "base" / "_api_surface.py").write_text(SURFACE)
    (tmp_path / path).write_text(source)
    test = f"class {name}:\n    def test_runs(self):\n        assert True\n"
    (tmp_path / "tests" / "internal" / "test_leads.py").write_text(test)
    found = overlap_scan.build_sections(tmp_path, 2)["placement"]
    assert not [text for text, _ in found if "is not a riko name" in text]


REJECTIONS = [
    pytest.param("with pytest.raises(E):\n    f()", True, id="only-raises"),
    pytest.param(
        "x = 1\nwith pytest.raises(E):\n    f(x)", True, id="setup-then-raises"
    ),
    pytest.param(
        "with pytest.raises(E) as exc:\n    f()\nmsg = str(exc.value)\nassert msg",
        True,
        id="asserts-about-the-error",
    ),
    pytest.param("pytest.raises(E, f)", True, id="call-form"),
    pytest.param(
        "with pytest.raises(E):\n    f()\nassert closed == []",
        False,
        id="asserts-after",
    ),
    pytest.param(
        "assert ready\nwith pytest.raises(E):\n    f()", False, id="asserts-before"
    ),
    pytest.param("assert f() == 1", False, id="no-raises"),
]


@pytest.mark.parametrize(("body", "expected"), REJECTIONS)
def test_is_rejection_reads_the_test_body(body, expected):
    source = "def test_x():\n" + "".join(f"    {line}\n" for line in body.splitlines())
    func = ast.parse(source).body[0]
    assert overlap_scan.is_rejection(func) is expected


RUNS = """\
class TestSyncRun:
    def test_runs(self):
        assert run()
        assert done

    def test_closes(self):
        assert close()

    def test_resumes(self):
        assert resume()

    def test_stops(self):
        assert stop()


class TestAsyncRun:
    async def test_runs(self):
        assert await arun()

    async def test_closes(self):
        assert await aclose()

    async def test_resumes(self):
        assert await aresume()


class TestOther:
    async def test_drains(self):
        stream = astream()
        await stream.aclose()
        assert stream.closed

    def test_reads_once(self):
        assert read()

    def test_generation_is_deterministic(self):
        assert generate() == generate()
"""
FOREVER = """\
def _forever():
    while True:
        yield 1
"""
RUN_LEADS = [
    pytest.param("twins", "test_runs: 2 checks vs 1 in TestAsyncRun", id="twin-checks"),
    pytest.param("twins", "test_stops: no twin in TestAsyncRun", id="twin-missing"),
    pytest.param("endless", "tests/_streams.py:1 _forever: loops", id="endless"),
    pytest.param("once", "TestOther::test_reads_once: says once", id="once"),
    pytest.param("determinism", "test_generation_is_deterministic: ", id="determinism"),
    pytest.param("drains", "TestOther::test_drains: drains with no", id="drains"),
]


@pytest.mark.parametrize(("section", "fragment"), RUN_LEADS)
def test_a_run_section_lists_the_lead(tmp_path, section, fragment):
    (tmp_path / "riko" / "base").mkdir(parents=True)
    (tmp_path / "tests" / "internal").mkdir(parents=True)
    (tmp_path / "riko" / "base" / "_api_surface.py").write_text(SURFACE)
    (tmp_path / "tests" / "_streams.py").write_text(FOREVER)
    (tmp_path / "tests" / "internal" / "test_runs.py").write_text(RUNS)
    found = overlap_scan.build_sections(tmp_path, 2, doctests=False)[section]
    assert any(fragment in text for text, _ in found), found


TWIN_CLASSES = """\
class TestSyncRun:
    def test_refuses(self):
        with pytest.raises(E):
            run()

    def test_refuses_a_closed_run(self):
        with pytest.raises(E):
            run()


class TestAsyncRun:
    async def test_refuses(self):
        with pytest.raises(E):
            await arun()

    async def test_refuses_a_closed_run(self):
        with pytest.raises(E):
            await arun()

        assert not held
"""
TWIN_METHODS = """\
class TestRun:
    def test_refuses(self):
        with pytest.raises(E):
            run()

    def test_sync_refuses_a_closed_run(self):
        with pytest.raises(E):
            run()

    async def test_async_refuses_a_closed_run(self):
        with pytest.raises(E):
            await arun()

        assert not held
"""
LONE_BEHAVIOR = """\
class TestRun:
    def test_refuses(self):
        with pytest.raises(E):
            run()

    def test_runs(self):
        assert run()
"""
TWIN_ORDERS = [
    pytest.param(TWIN_CLASSES, 0, id="twin-rejection-across-classes"),
    pytest.param(TWIN_METHODS, 0, id="twin-rejection-in-one-class"),
    pytest.param(LONE_BEHAVIOR, 1, id="behavior-after-a-rejection"),
]


@pytest.mark.parametrize(("source", "expected"), TWIN_ORDERS)
def test_a_twin_of_a_rejection_sorts_as_a_rejection(source, expected):
    tree = ast.parse(source)
    file = overlap_scan.TestFile(Path("test_run.py"), "internal", tree, source)
    assert len(list(overlap_scan.gen_order_issues(file))) == expected


_VACUOUS = "asserts only inside a for loop or all(...)"
VACUITY = [
    pytest.param("f()", "no assertion", id="no-assertion"),
    pytest.param("for x in xs:\n    assert x", _VACUOUS, id="loop"),
    pytest.param("assert all(map(ok, xs))", _VACUOUS, id="all-map"),
    pytest.param("xs = [1, 2]\nassert all(map(ok, xs))", None, id="all-literal"),
    pytest.param("for x in xs:\n    assert x\nassert len(xs) == 2", None, id="counted"),
    pytest.param("for x in xs:\n    assert x\n_assert_done(xs)", None, id="helper"),
    pytest.param("with pytest.raises(E):\n    f()", None, id="raises"),
    pytest.param("result.stdout.fnmatch_lines(['ok'])", None, id="fnmatch"),
    pytest.param("result.stdout.no_re_match_line('err')", None, id="no-match"),
]
ABSENT = [
    pytest.param("assert d.get('k') is None", True, id="is-none"),
    pytest.param("assert not d.get('k')", True, id="not"),
    pytest.param("assert d.get('k') == 1", False, id="value"),
]


def _parse_test(body: str) -> ast.FunctionDef:
    source = "def test_x():\n" + "".join(f"    {line}\n" for line in body.splitlines())
    func = ast.parse(source).body[0]
    assert isinstance(func, ast.FunctionDef)
    return func


@pytest.mark.parametrize(("body", "expected"), VACUITY)
def test_get_vacuity_reads_where_the_checks_sit(body, expected):
    assert overlap_scan.get_vacuity(_parse_test(body), set()) == expected


@pytest.mark.parametrize(("body", "expected"), ABSENT)
def test_is_absent_get_flags_a_lookup_compared_to_none(body, expected):
    node = _parse_test(body).body[0]
    assert isinstance(node, ast.Assert)
    assert overlap_scan.is_absent_get(node) is expected


FIXTURE_PLUGIN = """\
import pytest

orphan = pytest.fixture(lambda: 1)


@pytest.fixture
def probes():
    return {}
"""
FIXTURE_USERS = {
    "test_a.py": "def test_a(probes):\n    assert probes == {}\n",
    "test_b.py": 'NAMES = ["probes"]\n',
}


def test_a_fixture_counts_the_files_that_request_it(tmp_path):
    tier = tmp_path / "tests" / "internal"
    tier.mkdir(parents=True)
    (tmp_path / "tests" / "_plugin.py").write_text(FIXTURE_PLUGIN)

    for name, source in FIXTURE_USERS.items():
        (tier / name).write_text(source)

    issues = [text for text, _ in overlap_scan.gen_helper_issues(tmp_path, [])]
    assert issues == ["tests/_plugin.py:3 orphan: used by no test file"]


RELAY = """\
async def _arelay(stream, **_):
    async for item in as_async(stream):
        yield item
"""
ROWS = '''\
async def _agen_rows(rows, **kwargs):
    """Yields each row."""
    async for row in as_async(rows):
        yield row
'''
NESTED = """\
class TestRelay:
    def test_relays(self):
        async def relay(source, **_):
            async for value in as_async(source):
                yield value

        assert relay
"""
AITER = """\
async def _agen_rows(rows, **_):
    async for row in aiter(rows):
        yield row
"""
TRIVIAL = """\
def _first(value):
    return value


def _second(other):
    return other
"""
FAKES = """\
class _First:
    def close(self):
        self.closed.append("closed")


class _Second:
    def close(self):
        self.closed.append("closed")
"""
DUPLICATES = [
    pytest.param(
        {"internal/test_a.py": RELAY, "internal/test_b.py": ROWS},
        ["identical in 2 files: def _arelay / _agen_rows"],
        id="alpha-renamed",
    ),
    pytest.param(
        {"internal/test_a.py": RELAY, "internal/test_b.py": NESTED},
        ["identical in 2 files: def _arelay / relay"],
        id="nested-closure",
    ),
    pytest.param(
        {"internal/test_a.py": f"{RELAY}\n\n{ROWS}"},
        ["repeated 2 times in tests/internal/test_a.py: def _arelay / _agen_rows"],
        id="same-file",
    ),
    pytest.param(
        {"_streams.py": RELAY, "internal/test_b.py": NESTED},
        ["identical in 2 files: def _arelay / relay"],
        id="shared-helper",
    ),
    pytest.param(
        {"internal/test_a.py": RELAY, "internal/test_b.py": AITER},
        [],
        id="other-callee",
    ),
    pytest.param({"internal/test_a.py": TRIVIAL}, [], id="trivial"),
    pytest.param({"internal/test_a.py": FAKES}, [], id="one-statement-methods"),
]


@pytest.mark.parametrize(("sources", "expected"), DUPLICATES)
def test_a_renamed_copy_is_a_duplicate(tmp_path, sources, expected):
    (tmp_path / "tests" / "internal").mkdir(parents=True)

    for name, source in sources.items():
        (tmp_path / "tests" / name).write_text(source)

    files = overlap_scan.load_test_files(tmp_path)
    found = overlap_scan.gen_helper_issues(tmp_path, files)
    heads = [text.split("\n")[0] for text, _ in found]
    assert [h for h in heads if h.startswith(("identical", "repeated"))] == expected
