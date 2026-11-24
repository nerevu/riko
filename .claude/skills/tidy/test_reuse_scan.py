"""
Smoke-tests reuse_scan.py on in-memory helper and site modules.

Run after editing the tidy scripts:

    uv run --active pytest .claude/skills/tidy/test_reuse_scan.py --no-cov
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import reuse_scan

ALIST = """\
def as_async(source):
    return source


async def alist(source):
    return [item async for item in as_async(source)]
"""
INDENT = """\
def get_indent(line):
    return len(line) - len(line.lstrip())
"""
RELAY = """\
async def relay(stream):
    async for item in stream:
        yield item
"""
PARSER = """\
def parser(content, objconf):
    return cast_value(content, objconf.type) if objconf.type else content
"""
PIPE_WRAPPER = """\
from typing import cast


def _pipe_wrapper(**attrs):
    wrapper = cast("SyncModuleWrapper", lambda source, **_: source)

    for key, value in attrs.items():
        setattr(wrapper, key, value)

    return wrapper
"""
ACME_DEFINITION = """\
from typing import cast


def _acme_definition(**attrs: object) -> ModuleDefinition:
    pipe = cast("SyncModuleWrapper", lambda source, **_: source)

    for key, value in attrs.items():
        setattr(pipe, key, value)

    return ModuleDefinition(name=_ACME, sync_pipe=pipe)
"""
TEST_ONLY = """\
import pytest


@pytest.fixture(scope="module")
def doubled_lengths(lines):
    return [len(line) * 2 for line in lines]


def test_doubled_lengths(lines):
    return [len(line) * 2 for line in lines]
"""
TWINS = """\
def gen_doubled(items):
    for item in items:
        yield item * 2


async def agen_doubled(items):
    for item in items:
        yield item * 2
"""
LITERAL = """\
async def awaitable_source():
    return [{"x": 1}, {"x": 2}]
"""
DOUBLE = "def f(rows):\n    return [len(row) * 2 for row in rows]\n"
IMPORT_ALIST = "from riko.bado.itertools import alist, as_async\n"
COLLECT = "async def f(items):\n    return [x async for x in as_async(items)]\n"
CASES = [
    pytest.param(
        ("riko/bado/itertools.py", ALIST),
        ("riko/runtime/_write.py", IMPORT_ALIST + COLLECT),
        [("alist", ("?0=items",))],
        id="restated-alist",
    ),
    pytest.param(
        ("riko/bado/itertools.py", ALIST),
        ("riko/runtime/_write.py", IMPORT_ALIST + COLLECT.rstrip() + "  # reuse-ok\n"),
        [],
        id="reuse-ok",
    ),
    pytest.param(
        ("riko/bado/itertools.py", ALIST),
        ("riko/runtime/_write.py", "def as_async(s):\n    return s\n\n\n" + COLLECT),
        [],
        id="other-origin",
    ),
    pytest.param(
        ("riko/runtime/_strutils.py", INDENT),
        (
            "riko/base/_text.py",
            "def f(raw):\n    return len(raw) - len(raw.lstrip())\n",
        ),
        [],
        id="upward-layer",
    ),
    pytest.param(
        ("riko/base/_strutils.py", INDENT),
        ("riko/cli/_docs.py", "def f(raw):\n    return len(raw) - len(raw.lstrip())\n"),
        [("get_indent", ("?0=raw",))],
        id="downward-layer",
    ),
    pytest.param(
        ("riko/base/_strutils.py", INDENT),
        ("riko/cli/_docs.py", "def f(a, b):\n    return len(a) - len(b.lstrip())\n"),
        [],
        id="inconsistent-wildcard",
    ),
    pytest.param(
        ("riko/bado/_relay.py", RELAY),
        (
            "riko/runtime/_run.py",
            "async def f(s):\n    async for x in s:\n        yield x\n",
        ),
        [],
        id="passthrough-not-indexed",
    ),
    pytest.param(
        ("riko/modules/typecast.py", PARSER),
        (
            "riko/modules/input.py",
            "def f(v, c):\n    return cast_value(v, c.type) if c.type else v\n",
        ),
        [],
        id="pipe-contract-not-indexed",
    ),
    pytest.param(
        ("tests/internal/test_resolution.py", PIPE_WRAPPER),
        ("tests/public/test_modules.py", ACME_DEFINITION),
        [("_pipe_wrapper", ("?0=attrs",))],
        id="setup-then-return-test-helper",
    ),
    pytest.param(
        ("tests/internal/test_resolution.py", PIPE_WRAPPER),
        ("riko/modules/_definition.py", ACME_DEFINITION),
        [],
        id="test-helper-skips-riko-site",
    ),
    pytest.param(
        ("tests/internal/test_values.py", TEST_ONLY),
        ("tests/public/test_modules.py", DOUBLE),
        [],
        id="fixture-and-test-not-indexed",
    ),
    pytest.param(
        ("riko/base/_strutils.py", INDENT),
        (
            "tests/public/test_modules.py",
            "def f(raw):\n    return len(raw) - len(raw.lstrip())\n",
        ),
        [("get_indent", ("?0=raw",))],
        id="riko-helper-matches-test-site",
    ),
]


def _build_source(rel: str, text: str) -> reuse_scan.Source:
    path = reuse_scan.ROOT / rel
    module = reuse_scan.get_module(path)
    tree = ast.parse(text)
    origins = reuse_scan.build_origins(tree, module, path)
    return reuse_scan.Source(path, module, tree, text.splitlines(), origins)


def _gen_found(
    helper_spec: tuple[str, str],
    site_spec: tuple[str, str],
    lines: set[int] | None = None,
):
    helper_source = _build_source(*helper_spec)
    site = _build_source(*site_spec)
    helpers = list(reuse_scan.gen_helpers([helper_source], 4, include_tests=True))
    bodies = reuse_scan.get_whole_bodies(helpers)
    sites = [site, helper_source]
    scope = None if lines is None else {site.path: lines}

    for match in reuse_scan.gen_matches(helpers, sites, scope, bodies):
        yield match.helper.name, match.bindings


@pytest.mark.parametrize(("helper", "site", "expected"), CASES)
def test_gen_matches_flags_restated_helper_bodies(helper, site, expected):
    assert list(_gen_found(helper, site)) == expected


def test_gen_matches_reads_only_the_lines_in_scope():
    helper = ("riko/bado/itertools.py", ALIST)
    site = ("riko/runtime/_write.py", IMPORT_ALIST + COLLECT)
    assert list(_gen_found(helper, site, {3})) == [("alist", ("?0=items",))]
    assert not list(_gen_found(helper, site, {1}))


def test_check_site_tags_a_second_definition_of_a_body():
    source = _build_source(
        "riko/base/_strutils.py",
        INDENT
        + "\n\ndef indent_of(text):\n    return len(text) - len(text.lstrip())\n",
    )
    helpers = list(reuse_scan.gen_helpers([source], 4))
    bodies = reuse_scan.get_whole_bodies(helpers)
    found = {
        (m.helper.name, m.tags)
        for m in reuse_scan.gen_matches(helpers, [source], None, bodies)
    }
    assert found == {
        ("get_indent", ("duplicate helper indent_of",)),
        ("indent_of", ("duplicate helper get_indent",)),
    }


def _gen_tags(source: reuse_scan.Source, *sites: reuse_scan.Source):
    helpers = list(reuse_scan.gen_helpers([source], 4))
    bodies = reuse_scan.get_whole_bodies(helpers)

    for match in reuse_scan.gen_matches(helpers, [source, *sites], None, bodies):
        yield match.helper.name, match.tags


def test_check_site_tags_a_sync_async_pair_as_color_twins():
    source = _build_source("riko/base/_iterutils.py", TWINS)
    assert set(_gen_tags(source)) == {
        ("gen_doubled", ("color twin agen_doubled",)),
        ("agen_doubled", ("color twin gen_doubled",)),
    }


def test_check_site_tags_a_literal_only_helper_as_a_shared_literal():
    source = _build_source("riko/base/_sources.py", LITERAL)
    site = _build_source(
        "riko/cli/_docs.py", 'def f():\n    rows = [{"x": 1}, {"x": 2}]\n'
    )
    assert list(_gen_tags(source, site)) == [
        ("awaitable_source", ("shared literal: name a constant",))
    ]


def test_report_prints_a_helper_matched_twice_on_one_line_once(capsys):
    helper = _build_source("riko/bado/itertools.py", ALIST)
    site = _build_source("riko/runtime/_write.py", IMPORT_ALIST + COLLECT)
    helpers = list(reuse_scan.gen_helpers([helper], 4))
    match = next(reuse_scan.gen_matches(helpers, [site], None, {}))
    reuse_scan.report([match, match._replace(bindings=())], counts_only=False)
    assert capsys.readouterr().out.count("_write.py:") == 1


NODES = """\
A = ModuleNode(id="a", name="src")
B = ModuleNode(id="b", name="m")
C = ModuleNode(id="c", name="probe")
"""
DOCUMENTS = """\
A = {"id": "a", "name": "fetch"}
B = {"id": "b", "name": "fetch"}
C = {"id": "c", "name": "hash", "conf": 1}
"""
EDGES = """\
A = {"source": {"node": "a", "port": "out", "kind": "x"}, "family": "stream"}
B = {"source": {"node": "b", "port": "out", "kind": "x"}, "family": "stream"}
C = {"source": {"node": "c", "port": "out", "kind": "x"}, "family": "stream"}
"""
TABLE = """\
ROWS = [
    {"id": "a", "name": "fetch"},
    {"id": "b", "name": "fetch"},
    {"id": "c", "name": "hash"},
]
"""


def _build_clusters(text: str, min_count: int = 3):
    source = _build_source("tests/_shapes.py", text)
    members = [
        m for m in reuse_scan.gen_members(source, 5) if not reuse_scan.is_shape_ok(m)
    ]
    return reuse_scan.build_clusters(members, min_count)


def test_build_clusters_groups_calls_differing_in_values(capsys):
    clusters, _ = _build_clusters(NODES)
    assert [(len(c.members), c.is_keys) for c in clusters] == [(3, False)]
    reuse_scan.report_shapes(clusters)
    out = capsys.readouterr().out
    assert "## ModuleNode(id=<str>, name=<str>): 3 members (values)" in out
    assert "slots: id: a×1, b×1, c×1; name: src×1, m×1, probe×1" in out


def test_build_clusters_groups_dicts_differing_by_one_key():
    clusters, _ = _build_clusters(DOCUMENTS)
    assert [(len(c.members), c.is_keys) for c in clusters] == [(3, True)]
    skeleton = reuse_scan.get_skeleton(clusters[0])
    assert skeleton == "{'id': <str>, 'name': <str>, ['conf': …]}"


def test_build_clusters_skips_a_group_below_the_minimum_count():
    assert _build_clusters(NODES, min_count=4) == ([], {})


def test_build_clusters_skips_a_cluster_nested_in_a_reported_one():
    clusters, skipped = _build_clusters(EDGES)
    assert [len(c.members) for c in clusters] == [3]
    assert "family" in reuse_scan.get_skeleton(clusters[0])
    assert skipped["nested"] == 1


def test_build_clusters_skips_rows_of_one_table():
    clusters, skipped = _build_clusters(TABLE)
    assert not clusters
    assert skipped["table"] == 1


def test_build_clusters_drops_a_member_marked_reuse_ok():
    text = NODES.replace('"probe")', '"probe")  # reuse-ok')
    assert _build_clusters(text)[0] == []


def test_build_clusters_keeps_apart_shapes_differing_in_one_value():
    text = 'A = {"id": "a", "pipe": src}\nB = {"id": "b", "pipe": sink}\n' * 2
    assert [len(c.members) for c in _build_clusters(text, min_count=2)[0]] == [2, 2]


IDIOMS = """\
A = attrs.field(default="a", init=False, repr=False)
B = attrs.field(default="b", init=False, repr=False)
C = attrs.field(default="", init=False, repr=False)
"""
PARAMETRIZE_IDIOMS = """\
A = pytest.mark.parametrize("x", TABLE, ids=["a"])
B = pytest.mark.parametrize("y", TABLE, ids=["b"])
C = pytest.mark.parametrize("z", TABLE, ids=["c"])
"""


@pytest.mark.parametrize("text", [IDIOMS, PARAMETRIZE_IDIOMS])
def test_gen_members_skips_declaration_idioms_unless_all_callees(text):
    source = _build_source("riko/base/_records.py", text)
    assert not list(reuse_scan.gen_members(source, 5))
    assert len(list(reuse_scan.gen_members(source, 5, frozenset()))) == 3


def test_main_all_callees_reports_the_idiom_cluster(monkeypatch, capsys):
    source = _build_source("riko/base/_records.py", IDIOMS)
    monkeypatch.setattr(reuse_scan, "gen_paths", lambda *_: [source.path])
    monkeypatch.setattr(reuse_scan, "load_source", lambda _: source)
    assert reuse_scan.main(["--all", "--shapes"]) == 0
    assert reuse_scan.main(["--all", "--shapes", "--all-callees"]) == 1
    assert "## attrs.field(" in capsys.readouterr().out


def _build_spread_clusters(*rels: str):
    sources = [_build_source(rel, NODES) for rel in rels]
    members = [m for s in sources for m in reuse_scan.gen_members(s, 5)]
    return reuse_scan.build_clusters(members, 3)[0]


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ("examples,tests", [False, True, False]),
        ("only:examples", [True, False, False]),
        ("riko,mixed", [False, False, True]),
        ("tests", [False, True, True]),
    ],
)
def test_spans_keeps_clusters_spanning_the_named_roots(spec, expected):
    spreads = [
        ("examples/demo.py", "examples/usage.py"),
        ("examples/demo.py", "tests/_shapes.py"),
        ("riko/base/_nodes.py", "tests/_shapes.py"),
    ]
    clusters = [c for rels in spreads for c in _build_spread_clusters(*rels)]
    spans = reuse_scan.Spans.parse(spec)
    assert [spans.is_spanned(c) for c in clusters] == expected


def test_main_spans_rejects_an_unknown_root(capsys):
    with pytest.raises(SystemExit):
        reuse_scan.main(["--all", "--shapes", "--spans", "docs"])
    assert "unknown roots ['docs']" in capsys.readouterr().err
