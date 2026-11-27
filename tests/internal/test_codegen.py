# vim: sw=4:ts=4:expandtab
"""Provides internal tests for codegen of workflows, names, ids, configs, and docs."""

from __future__ import annotations

import dataclasses
import importlib.util
import json
import re
from datetime import date
from importlib import import_module
from importlib.resources import files
from keyword import iskeyword
from types import BuiltinFunctionType, FunctionType
from typing import TYPE_CHECKING, Any

import pytest

import riko
import riko.bado
import riko.definitions._workflow_definition
import riko.exceptions
import riko.ext
import riko.ext.codegen
import riko.ext.modules
import riko.ext.targets
import riko.ext.workflows
import riko.modules
import riko.modules._names
import riko.runtime._compile
import riko.runtime._export
import riko.runtime._resolver
import riko.runtime._workflow_pipes
import riko.runtime._workflow_resolver
import riko.runtime._workflow_stores
import riko.types
from riko.bado._backend import fail_after
from riko.base._api_surface import (
    BADO,
    COMPILE,
    EXPORT,
    EXT_CODEGEN,
    EXT_MODULES,
    EXT_TARGETS,
    EXT_WORKFLOWS,
    EXTENSION,
    MODULES,
    PRIVATE_RESOLUTION,
    ROOT_EXCEPTIONS,
    STABLE,
    TYPES,
)
from riko.base._config import LINE_LENGTH
from riko.base._paths import (
    CONFIG_PATH,
    GAMEPLANS_DIR,
    MODULE_IDS_PATH,
    MODULE_NAMES_PATH,
    ROOT_DIR,
    USER_AGENTS_PATH,
)
from riko.base._strutils import get_codegen_note, pythonise
from riko.cli._gen_api_surface import (
    API_SURFACE_BLOCK,
    API_SURFACE_MARKERS,
    generate_api_surface,
)
from riko.cli._gen_blocks import gen_block_offenders
from riko.cli._gen_config import objconf_structure, render
from riko.cli._gen_forward_track import (
    Release,
    build_forward_track,
    gen_forward_track_problems,
    load_validator,
)
from riko.cli._gen_planning import Snapshot, build_export, generate_planning_blocks
from riko.cli._gen_user_agents import (
    USER_AGENT_COUNT,
    generate_user_agents,
    get_top_agents,
    load_user_agents,
)
from riko.cli._gen_verbs import TableFormat, generate_verb_tables
from riko.cli._planning import (
    PlanFile,
    PlanningData,
    PlanningError,
    Problem,
    Unlock,
    gen_sections,
)
from riko.definitions._workflow_definition import Workflow
from riko.execution._async_execution import AsyncExecution
from riko.execution._prepared import ExecutionPlan
from riko.ext.codegen import (
    gen_catalog_entries,
    generate_module_ids,
    generate_module_names,
)
from riko.modules._metadata import describe_module, gen_module_catalog, list_modules
from riko.runtime._compile import compile_workflow
from riko.runtime._pipeline import Pipeline
from riko.runtime._resolver import dispatcher
from riko.types._enums import UserAgent
from riko.types._wrappers import WrapperMeta, require_wrapper_meta
from riko.types.modules import (
    ConfArg,
    RenameRawConf,
    RenameRawRule,
    SortRawConf,
    SortRawRule,
)
from tests import TESTS_DIR, async_test, is_installed
from tests._workflows import EXAMPLES_DIR, TEST_CONTEXT, run_document, run_workflow

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path
    from types import ModuleType

    from riko.types._streams import Item
    from riko.types.modules import ModuleCategory


_SOURCES = {
    "csv",
    "feedautodiscovery",
    "fetch",
    "fetchdata",
    "fetchpage",
    "fetchsitefeed",
    "fetchtable",
    "fetchtext",
    "forever",
    "input",
    "itembuilder",
    "rssitembuilder",
    "urlbuilder",
    "xpathfetchpage",
}

_SINKS = {"write"}
_DAY1, _DAY2, _DAY3 = date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)
_TODAY = date(2026, 6, 1)
_HOMES_PLAN = {
    "phases": {"X1": {"doc": "plan.md", "slices": [{"id": "a"}, {"id": "add"}]}}
}
_LOCAL_PLAN = {"slices": [{"id": "S1"}]}
_LANE_PLAN = {"lanes": {"L1": {"owner": "user", "slices": [{"id": "D1"}]}}}
_X1_HEADING = "## X1: First\n\n"
_LANDED = {"landed": _DAY1}
_Q_RIDER = {"id": "a", "lands_with": ["X1.q"]}
_RENDER_PLANS = {
    "plan": {
        "phases": {
            "R20": {
                "area": "core",
                "doc": "plan.md",
                "slices": [{"id": "a", "landed": _DAY1}, {"id": "b"}],
                "decisions": [{"id": "q"}],
            },
            "R21": {"area": "core", "doc": "plan.md", "blocked_by": ["R20"]},
            "P20": {"doc": "../tracker.md", "scheduled_after": ["R21"]},
        },
        "milestones": {
            "M20": {"doc": "plan.md", "blocked_by": ["R21"], "proposed": True}
        },
        "lanes": {
            "tidy": {
                "owner": "user",
                "trigger": "weekly",
                "slices": [{"id": "D1", "lands_with": ["R21"]}],
            }
        },
    },
    "stream": {"slices": [{"id": "S1", "lands_with": ["R21"]}, {"id": "S2"}]},
}
_RENDER_TEXT = """## Areas

**core: Core work.** Context.

## Lanes

**tidy: Tidy lane.** Context.

### R20: First phase

**Goal:** Build it. Then more.

**R20.a: Slice one.** Prose.

**R20.q: A question.** Prose.

### R21: Second phase

**R20: needs the base.** Detail.

### M20: Preview
"""
_RENDER_DOCS = {
    "plan.md": _RENDER_TEXT,
    "../tracker.md": "### P20: Track item\n",
    "stream.md": "**S1: Local slice.** Prose.\n",
}
_SNAPSHOT = Snapshot("main", "abc123", _TODAY, "https://example.com/repo")
_EXITS = [{"id": "add"}, {"id": "migrate"}, {"id": "delete"}]
_TRACK_PHASES = {
    "R90": {
        "area": "core",
        "slices": [{**item, **_LANDED} for item in _EXITS],
        "decisions": [{"id": "p"}],
    },
    "R91": {
        "area": "core",
        "blocked_by": ["R90"],
        "decisions": [{"id": "q"}],
        "slices": [
            {"id": "a"},
            {"id": "b"},
            *({**item, "lands_with": ["R91.b"]} for item in _EXITS),
        ],
    },
    "R92": {"area": "edge", "blocked_by": ["R90"], "slices": _EXITS},
    "R93": {"area": "edge", "scheduled_after": ["R92", "R94"], "slices": _EXITS},
    "R94": {"area": "edge", "slices": [{"id": "add", "designing": _DAY1}, *_EXITS[1:]]},
}
_TRACK_PLANS = {
    "plan": {
        "phases": {
            key: {**phase, "doc": "plan.md"} for key, phase in _TRACK_PHASES.items()
        },
        "milestones": {
            "M90": {"doc": "plan.md", "blocked_by": ["R91.a"]},
            "M91": {"doc": "plan.md", "blocked_by": ["M90", "R91.b", "R92"]},
            "M93": {"doc": "plan.md", "blocked_by": ["R93"], "proposed": True},
        },
    },
    "stream": {"slices": [{"id": "S90", "lands_with": ["R91.a"]}]},
}
_TRACK_TEXT = """## Areas

**core: Core work.** Context.

**edge: Edge work.** Context.

### R90: Base

**Goal:** Lay the base.

**R90.p: Base question.** Prose.

### R91: Split

**Goal:** Split it.

**R91.a: First slice.** Prose.

**R91.b: Second slice.** Prose.

**R91.q: Split question.** Why split.

### R92: Side

**R90: needs the base.** Detail.

### R93: Later

### R94: Early

### M90: First release

### M91: Final release

### M93: Preview

**Goal:** Maybe ship.
"""
_TRACK_DOCS = {"plan.md": _TRACK_TEXT, "stream.md": "**S90: Riding slice.** Prose.\n"}
_TRACK_PAGE = {
    "brand": "brand",
    "documentTitle": "document",
    "sectionLabel": "section",
    "title": "title",
    "subtitle": "subtitle",
    "historyCaption": "caption",
    "outlook": {"heading": "heading", "body": "body"},
}
_TRACK_SNAPSHOT = Snapshot(
    "main", "abc1234", _TODAY, "https://example.com/org/repo", "v9.9.9"
)
_TRACK_RELEASES = [Release("v9.0.0", _DAY2, "Release")]

RENAME_CONF = RenameRawConf(
    {
        "rule": RenameRawRule(
            field=ConfArg(type="text", value="content"),
            newval=ConfArg(type="text", value="greeting"),
        )
    }
)

# These documents cannot run on their own: two name modules riko does not
# implement, and the third is a stored workflow that is only meaningful when another
# workflow embeds it. Their workflow modules are held to the same failure.
UNRUNNABLE = frozenset(
    {
        "pipe_93abb8500bd41d56a37e8885094c8d10",
        "pipe_b3d43c00f9e1145ff522fb71ea743e99",
        "pipe_bd0834cfe6cdacb0bea5569505d330b8",
    }
)

FIXTURE_MARKS: dict[str, tuple[pytest.MarkDecorator, ...]] = {}

ASYNC_FIXTURES = ("pipe_gigs", "pipe_loop_assign", "pipe_loop_subpipe")
FIXTURE_DIRS = (TESTS_DIR / "workflows", EXAMPLES_DIR / "workflows")
DESCRIBED_INPUTS = {"limit": {"type": "integer"}}

SORT_CONF = SortRawConf(
    {"rule": SortRawRule(field=ConfArg(type="text", value="title"))}
)

PROBE_PACKAGES = {
    TESTS_DIR / "pyworkflows": "tests.pyworkflows",
    EXAMPLES_DIR / "pyworkflows": "examples.pyworkflows",
}

# A stored-workflow fixture: it is only meaningful when another workflow embeds it.
SUBPIPE_ONLY = frozenset({"pipe_bd0834cfe6cdacb0bea5569505d330b8"})
PROBE_MARKS: dict[str, tuple[pytest.MarkDecorator, ...]] = {}

SURFACE_MODULES = (
    riko.bado,
    riko.runtime._export,
    riko.runtime._compile,
    riko.definitions._workflow_definition,
    riko.ext,
    riko.modules,
    riko.exceptions,
    riko,
    riko.types,
)

PARTIAL_SURFACES = (
    (riko.modules.__all__ + riko.modules._names.__all__, MODULES),
    (riko.exceptions.__all__, ROOT_EXCEPTIONS),
)

CONF_TYPES = riko.types.modules.__all__
CODEGEN = (COMPILE & {"compile_workflow"}) | {"RAW_CONFS", "render_value"}

EQUAL_SURFACES = (
    (riko.bado, BADO),
    (riko.runtime._export, EXPORT),
    (riko.runtime._compile, CODEGEN),
    (riko.definitions._workflow_definition, {"Workflow"}),
    (riko.ext, EXTENSION),
    (riko.ext.codegen, EXT_CODEGEN),
    (riko.ext.modules, EXT_MODULES),
    (riko.ext.targets, EXT_TARGETS),
    (riko.ext.workflows, EXT_WORKFLOWS),
    (riko, STABLE),
    (riko.types, TYPES),
)

PUBLIC_EXTENSION_MODULES = (
    "riko.ext.codegen",
    "riko.ext.modules",
    "riko.ext.targets",
    "riko.ext.workflows",
)

REMOVED_PUBLIC_PATHS = tuple(
    f"riko.ext.{name}" for name in ("config", "decorators", "protocols", "registry")
)

RESOLUTION_MODULES = (
    riko.runtime._resolver,
    riko.runtime._workflow_pipes,
    riko.runtime._workflow_stores,
    riko.runtime._workflow_resolver,
)

DECLARING_FLOW = Workflow.parse(
    {
        "nodes": [{"name": "loop", "embed": {"name": "tokenizer"}}],
        "input_schemas": DESCRIBED_INPUTS,
    }
)


def _load(source: str, name: str, directory: Path) -> ModuleType:
    """Imports generated ``source`` as a module named ``name`` under a directory."""
    path = directory / f"{name}.py"
    path.write_text(source)
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build(flow: Workflow, name: str, directory: Path, **kwargs) -> ModuleType:
    """Generates and imports the module for ``flow``."""
    return _load(compile_workflow(flow, name, **kwargs), name, directory)


def gen_fixture_paths() -> Iterator[Path]:
    """Finds every committed ``pipe_*.json`` workflow document, sorted per directory."""
    for directory in FIXTURE_DIRS:
        yield from sorted(directory.glob("pipe_*.json"))


def _compile_fixtures(unrunnable: bool = False) -> list[Any]:
    params = []

    for path in gen_fixture_paths():
        if (path.stem in UNRUNNABLE) != unrunnable:
            continue

        marks = FIXTURE_MARKS.get(path.stem, ())
        params.append(pytest.param(path, id=path.stem, marks=marks))

    return params


async def _arun_document(flow: Workflow) -> list[Item]:
    items: list[Item] = []

    async with AsyncExecution(context=TEST_CONTEXT) as execution:
        stream = await execution.arun(ExecutionPlan.from_workflow(flow, dispatcher))
        items = [item async for item in stream]

    return items


def _failure(call) -> tuple[str, str]:
    """Reports the type and message of the error ``call`` raises."""
    with pytest.raises(Exception) as info:  # noqa: PT011
        call()

    return type(info.value).__name__, str(info.value)


GENERATED_INPUTS = [
    pytest.param({"content": "hello"}, [{"greeting": "hello"}], id="one-item"),
    pytest.param(
        [{"content": "hello"}, {"content": "bye"}],
        [{"greeting": "hello"}, {"greeting": "bye"}],
        id="stream",
    ),
]


class TestWorkflowModule:
    """
    A workflow module produces exactly what running its workflow document produces.

    The equivalence holds over every committed fixture under both sync and async
    iteration.
    """

    @pytest.mark.parametrize("path", _compile_fixtures())
    def test_generated_matches_document(self, path: Path, tmp_path: Path):
        """Each workflow module yields the items its workflow document yields."""
        flow = Workflow.parse(path.read_text())
        module = _build(flow, path.stem, tmp_path)
        assert list(module.pipe(context=TEST_CONTEXT)) == run_workflow(flow)

    @pytest.mark.parametrize("path", _compile_fixtures(unrunnable=True))
    def test_generated_matches_document_failure(self, path: Path, tmp_path: Path):
        """A document that cannot run standalone fails the same way once generated."""
        flow = Workflow.parse(path.read_text())

        def run_generated() -> list[object]:
            module = _build(flow, path.stem, tmp_path)
            return list(module.pipe(context=TEST_CONTEXT))

        generated = _failure(run_generated)
        assert generated == _failure(lambda: run_workflow(flow))

    @pytest.mark.parametrize("stem", ASYNC_FIXTURES)
    @async_test
    async def test_async_generated_matches_document(self, stem: str, tmp_path: Path):
        """Each generated async module yields the items its document yields."""
        path = TESTS_DIR / "workflows" / f"{stem}.json"
        flow = Workflow.parse(path.read_text())
        module = _build(flow, stem, tmp_path, is_async=True)
        stream = module.async_pipe(context=TEST_CONTEXT)
        assert [item async for item in stream] == await _arun_document(flow)

    @pytest.mark.parametrize(("source", "expected"), GENERATED_INPUTS)
    def test_generated_pipe_maps_its_input(self, source, expected, tmp_path: Path):
        """A generated transformer maps a single item or every item of a stream."""
        flow = Pipeline.from_module("rename", conf=RENAME_CONF).workflow
        module = _build(flow, "pipe_rename", tmp_path)
        assert list(module.pipe(source)) == expected

    @async_test
    async def test_generated_async_pipe_accepts_an_async_stream(self, tmp_path: Path):
        """A generated async transformer maps every item of an async stream."""
        flow = Pipeline.from_module("rename", conf=RENAME_CONF).workflow
        module = _build(flow, "pipe_arename", tmp_path, is_async=True)

        async def source():
            yield {"content": "hello"}
            yield {"content": "bye"}

        expected = [{"greeting": "hello"}, {"greeting": "bye"}]
        assert [item async for item in module.async_pipe(source())] == expected

    @pytest.mark.parametrize("is_async", [False, True], ids=["sync", "async"])
    def test_generated_pipe_carries_its_declarations(self, is_async, tmp_path: Path):
        """A generated pipe declares its workflow's inputs and modules, embeds too."""
        module = _build(DECLARING_FLOW, "pipe_declared", tmp_path, is_async=is_async)
        pipe = module.async_pipe if is_async else module.pipe
        definition = describe_module(require_wrapper_meta(pipe))
        declared = (definition.input_schemas, definition.dependencies)
        assert declared == (DESCRIBED_INPUTS, ("loop", "tokenizer"))

    @async_test
    async def test_abandoned_async_pipe_closes_its_execution(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Closing an abandoned generated async stream exits its execution first."""
        log: list[str] = []
        aexit = AsyncExecution.__aexit__

        async def spy(self, *args):
            log.append("execution exit")
            return await aexit(self, *args)

        monkeypatch.setattr(AsyncExecution, "__aexit__", spy)
        flow = Pipeline.from_module("forever").workflow
        module = _build(flow, "pipe_aforever", tmp_path, is_async=True)
        stream = module.async_pipe()

        async for _ in stream:
            break

        with fail_after(1):
            await stream.aclose()

        log.append("after close")
        assert log == ["execution exit", "after close"]


class TestCompileWorkflow:
    def test_conf_is_typed_by_its_module(self):
        """A configured node is rendered through its module's raw config class."""
        flow = Pipeline.from_module("sort", conf=SORT_CONF).workflow
        assert "SortRawConf(" in compile_workflow(flow, "pipe_sorted")

    def test_generated_conf_keeps_its_keys_verbatim(self, tmp_path: Path):
        """A workflow module spells a configuration key exactly as the document does."""
        attrs = {
            "key": ConfArg(type="text", value="title"),
            "value": ConfArg(type="text", value="riko"),
        }
        conf = {"attrs": [attrs], "EXTRA": ConfArg(type="text", value="x")}
        flow = Workflow.from_raw({"nodes": [{"name": "itembuilder", "conf": conf}]})
        module = _build(flow, "pipe_verbatim", tmp_path)
        assert module.flow == flow
        assert list(module.pipe(context=TEST_CONTEXT)) == run_workflow(flow)

    def test_generation_is_deterministic(self):
        """Generating the same workflow twice produces identical source."""
        flow = (
            Pipeline.from_module("itembuilder")
            .pipe("rename", conf=RENAME_CONF)
            .workflow
        )
        assert compile_workflow(flow, "pipe_twice") == compile_workflow(
            flow, "pipe_twice"
        )

    def test_generation_is_stable_across_processes_with_different_hash_seeds(
        self, hash_seed_probes
    ):
        compiled = {probes["compiled"] for probes in hash_seed_probes.values()}
        assert len(compiled) == 1

    def test_empty_fields_are_left_out(self, tmp_path: Path):
        """A workflow without edges or input schemas generates neither keyword."""
        flow = Pipeline.from_module("hash").workflow
        source = compile_workflow(flow, "pipe_bare")
        assert "edges=" not in source
        assert "input_schemas=" not in source
        assert _load(source, "pipe_bare", tmp_path).flow == flow

    def test_generated_source_imports_back_to_the_same_flow(self, tmp_path: Path):
        """The generated source of an edged flow imports back to the same flow."""
        flow = (
            Pipeline.from_module("itembuilder")
            .pipe("rename", conf=RENAME_CONF)
            .workflow
        )
        source = compile_workflow(flow, "pipe_parsed")
        assert _load(source, "pipe_parsed", tmp_path).flow == flow


class TestPythonise:
    @pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason="pythonise does not sanitize ids into valid identifiers yet",
    )
    def test_pythonise_yields_valid_identifiers(self):
        """
        Every generated id must be a legal, non-keyword Python identifier.

        ``pythonise`` only replaces four characters and ASCII-``replace``-encodes, so
        ``"class"``/``"foo bar"``/``"foo.bar"``/``"café"`` survive into generated source
        as invalid identifiers (``"1st"`` already becomes ``"_1st"``).
        ``ext/codegen.py::enum_member_name`` already sanitizes properly.
        """
        results = [
            pythonise(raw) for raw in ("class", "foo bar", "foo.bar", "1st", "café")
        ]
        assert all(r.isidentifier() and not iskeyword(r) for r in results)


@pytest.fixture
def categories() -> dict[str, ModuleCategory]:
    return {md.name: md.category for md in gen_module_catalog()}


class TestModuleCategory:
    def test_taxonomy_partition_matches_golden(self, categories):
        buckets: dict[str, set[str]] = {
            "source": set(),
            "sink": set(),
            "transform": set(),
        }
        for name, category in categories.items():
            buckets[category].add(name)

        assert buckets["source"] == _SOURCES
        assert buckets["sink"] == _SINKS
        assert buckets["transform"] == set(categories) - _SOURCES - _SINKS

    def test_sink_name_is_classified_as_sink(self):
        md = next(md for md in gen_module_catalog() if md.name == "fetch")
        renamed = dataclasses.replace(md, name="write")
        assert renamed.category == "sink"

    @pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason="replacing the write module with write nodes is not yet implemented",
    )
    def test_no_module_is_a_sink(self):
        """Writes run through targets, so no module is categorized as a sink."""
        assert list_modules(category="sink") == []


class TestGenerateModuleNames:
    def test_generated_names_match(self):
        entries = gen_catalog_entries()
        assert MODULE_NAMES_PATH.read_text() == generate_module_names(*entries)


class TestGenerateModuleIds:
    def test_generated_module_ids_match(self):
        assert MODULE_IDS_PATH.read_text() == generate_module_ids()


class TestConfigCodegen:
    """Run ``manage codegen --config`` to update generated configs."""

    def test_configs_match_generated(self):
        assert CONFIG_PATH.read_text() == render()

    def test_fetchtable_inherits_csv(self):
        assert objconf_structure()["FetchTableObjconf"][0] == "CsvObjconf"


USER_AGENT_ENTRIES = [
    pytest.param("x" * 100 + " y", id="long-token"),
    pytest.param(" " + "lead " * 20, id="leading-space"),
]


@pytest.mark.skipif(
    not is_installed("fake_useragent"), reason="fake-useragent is not installed"
)
class TestGenerateUserAgents:
    """Run ``manage codegen --user-agents`` to update the random user-agent pools."""

    def test_user_agents_match_generated(self):
        assert USER_AGENTS_PATH.read_text() == load_user_agents()

    @pytest.mark.parametrize("device", [UserAgent.DESKTOP, UserAgent.MOBILE])
    def test_generated_pools_hold_distinct_agents_of_their_device(self, device):
        text = files("fake_useragent.data").joinpath("browsers.jsonl").read_text()
        rows = [json.loads(line) for line in text.splitlines() if line]
        matching = {row["useragent"] for row in rows if row["type"] == device}
        agents = get_top_agents(text, device)
        namespace: dict[str, object] = {}
        exec(generate_user_agents({device: agents}, "0"), namespace)

        assert len(set(agents)) == len(agents) == USER_AGENT_COUNT
        assert matching.issuperset(agents)
        assert namespace[f"{device.upper()}_USER_AGENTS"] == tuple(agents)

    @pytest.mark.parametrize("agent", USER_AGENT_ENTRIES)
    def test_generated_entries_round_trip_within_the_line_length(self, agent):
        source = generate_user_agents({UserAgent.DESKTOP: [agent]}, "0")
        namespace: dict[str, object] = {}
        exec(source, namespace)

        assert namespace["DESKTOP_USER_AGENTS"] == (agent,)
        assert max(map(len, source.splitlines())) <= LINE_LENGTH


def _render(flow: Workflow) -> str:
    """Renders a workflow as the indented document the fixtures are stored in."""
    return flow.serialize().decode("utf-8")


def _document_fixtures() -> list[Any]:
    return [pytest.param(path, id=path.stem) for path in gen_fixture_paths()]


class TestWorkflowFixtures:
    @pytest.mark.parametrize("path", _document_fixtures())
    def test_fixture_round_trips(self, path: Path):
        """Every committed fixture parses, validates, and is stored serialized."""
        flow = Workflow.parse(path.read_text())
        flow.validate()
        assert path.read_text() == _render(flow)


def _gen_probe_documents() -> Iterator[tuple[str, Path]]:
    """Finds each probe's package and its sibling workflow document."""
    for directory, package in PROBE_PACKAGES.items():
        for path in sorted(directory.glob("pipe_*.py")):
            document = directory.parent / "workflows" / f"{path.stem}.json"

            if document.exists():
                yield package, document


def _probes() -> list[Any]:
    return [
        pytest.param(
            package,
            document,
            id=document.stem,
            marks=PROBE_MARKS.get(document.stem, ()),
        )
        for package, document in _gen_probe_documents()
        if document.stem not in SUBPIPE_ONLY
    ]


def _declaring_probes() -> list[Any]:
    return [
        pytest.param(package, document, id=document.stem)
        for package, document in _gen_probe_documents()
    ]


def _building_probes() -> list[Any]:
    return [
        pytest.param(package, path.stem, id=path.stem)
        for directory, package in PROBE_PACKAGES.items()
        for path in sorted(directory.glob("pipe_*.py"))
        if "def build()" in path.read_text()
    ]


def _run_probe(package: str, name: str) -> list[object]:
    module = import_module(f"{package}.{name}")

    if package.startswith("examples"):
        stream = module.pipe(test=True)
    else:
        stream = module.pipe(context=TEST_CONTEXT)

    return list(stream)


def _probe_pipe(package: str, name: str) -> WrapperMeta:
    probe = import_module(f"{package}.{name}")
    attr = "pipe" if hasattr(probe, "pipe") else "async_pipe"
    return require_wrapper_meta(getattr(probe, attr))


class TestWorkflowProbes:
    @pytest.mark.parametrize(("package", "path"), _probes())
    def test_probe_matches_document(self, package: str, path: Path):
        """Each Python probe yields the items its workflow document yields."""
        expected = _run_probe(package, path.stem)
        assert run_document(path) == expected

    @pytest.mark.parametrize(("package", "document"), _declaring_probes())
    def test_probe_declares_what_its_document_declares(
        self, package: str, document: Path
    ):
        """Each probe declares the input schemas and dependencies its document does."""
        definition = describe_module(_probe_pipe(package, document.stem))
        flow = Workflow.parse(document.read_text())
        declared = (definition.input_schemas, definition.dependencies)
        assert declared == (flow.input_schemas, flow.dependencies)

    @pytest.mark.parametrize(("package", "name"), _building_probes())
    def test_probe_declares_what_it_builds(self, package: str, name: str):
        """A probe without a document declares the modules its ``build()`` runs."""
        dependencies = describe_module(_probe_pipe(package, name)).dependencies
        probe = import_module(f"{package}.{name}")
        assert dependencies == probe.build().workflow.dependencies


def id_func(val):
    if hasattr(val, "__name__"):
        return val.__name__
    else:
        return "vs-set"


def _gen_subclasses(cls):
    for subclass in cls.__subclasses__():
        yield subclass
        yield from _gen_subclasses(subclass)


class TestImportSurface:
    """
    Check the public API boundary.

    ``riko`` define the stable application API. ``riko.ext`` defines the
    extension-author API. ``riko.bado`` is a supported async-runtime namespace; the
    BADO subset is promoted into the stable application surface. These tests exercise
    public imports rather than implementation details.
    """

    @pytest.mark.smoke
    def test_package_ships_py_typed(self):
        assert files("riko").joinpath("py.typed").is_file()

    @pytest.mark.smoke
    @pytest.mark.parametrize(("module", "surface"), EQUAL_SURFACES, ids=id_func)
    def test_equal_surface_matches_expected(self, module, surface):
        assert sorted(set(module.__all__)) == sorted(surface)

    @pytest.mark.parametrize(("names", "surface"), PARTIAL_SURFACES, ids=id_func)
    def test_partial_surface_matches_expected(self, names, surface):
        assert surface.issubset(names)
        assert not any(name.startswith("_") for name in names)

    def test_normal_module_confs_are_public(self):
        assert "FetchConf" in CONF_TYPES
        assert "RegexConf" in CONF_TYPES
        assert "ItemBuilderConf" in CONF_TYPES

    def test_raw_module_confs_are_private(self):
        leaked = sorted(
            name for name in CONF_TYPES if name.endswith(("RawConf", "RawRule"))
        )
        assert not leaked, f"Raw module confs leaked into riko.types.modules: {leaked}"

    def test_module_metadas_are_same(self):
        assert riko.ext.ModuleMetadata is riko.types.modules.ModuleMetadata

    @pytest.mark.parametrize(
        ("module", "surface"), [(riko, STABLE), (riko.ext, EXTENSION)]
    )
    def test_stable_names_importable(self, module, surface):
        """Every declared stable names actually resolves on ``riko``."""
        assert all(hasattr(module, name) for name in surface)

    def test_bado_reexports_are_same_object(self):
        mismatches = sorted(
            name
            for name in riko.bado.__all__
            if getattr(riko, name) is not getattr(riko.bado, name)
        )
        assert not mismatches, f"Bado reexports differ from riko: {mismatches}"

    def test_exception_reexports_are_same_object(self):
        mismatches = sorted(
            name
            for name in ROOT_EXCEPTIONS
            if getattr(riko, name) is not getattr(riko.exceptions, name)
        )
        assert not mismatches, f"Exception reexports differ from riko: {mismatches}"

    def test_exceptions_naming_the_public_module_are_importable_from_it(self):
        public = riko.exceptions
        roots = (public.RikoError, public.RikoWarning)
        unexported = sorted(
            cls.__name__
            for root in roots
            for cls in (root, *_gen_subclasses(root))
            if cls.__module__ == public.__name__ and cls.__name__ not in public.__all__
        )
        assert not unexported, f"Not importable from {public.__name__}: {unexported}"

    def test_private_resolution_names_exist(self):
        """Every declared private resolution name is defined by a resolution module."""
        missing = sorted(
            name
            for name in PRIVATE_RESOLUTION
            if not any(hasattr(module, name) for module in RESOLUTION_MODULES)
        )
        assert not missing, f"Declared resolution internals do not exist: {missing}"

    @pytest.mark.parametrize(
        "module",
        [*SURFACE_MODULES, *map(import_module, PUBLIC_EXTENSION_MODULES)],
        ids=lambda module: module.__name__,
    )
    def test_no_accidental_internal_exports(self, module):
        """Private resolution internals are neither exported nor reachable publicly."""
        exported = PRIVATE_RESOLUTION.intersection(getattr(module, "__all__", ()))
        reachable = {name for name in PRIVATE_RESOLUTION if hasattr(module, name)}
        leaked = sorted(exported | reachable)
        assert not leaked, f"Private resolution internals exposed: {leaked}"

    @pytest.mark.parametrize("module", RESOLUTION_MODULES, ids=lambda m: m.__name__)
    def test_resolution_internals_have_no_public_path(self, module):
        """Resolution internals live only behind ``_``-prefixed modules."""
        package, _, private_name = module.__name__.rpartition(".")
        public_path = f"{package}.{private_name.lstrip('_')}"
        assert private_name.startswith("_")

        with pytest.raises(ModuleNotFoundError):
            import_module(public_path)

    def test_no_leaked_public_functions(self):
        """
        No bare function leaks into the top-level namespace outside ``__all__``.

        Scoped to *functions* on purpose: classes and constants (e.g. ``Context``,
        ``ENCODING``, ``objectify``) are intentionally importable while absent from
        ``__all__``, so this guards callables rather than the whole attribute surface
        (that surface is pinned by ``test_equal_surface_matches_expected``).
        """
        leaked = sorted(
            name
            for name, val in vars(riko).items()
            if not (name.startswith("_") or name in STABLE)
            and isinstance(val, (FunctionType, BuiltinFunctionType))
        )
        assert not leaked, f"Top-level functions leaked outside STABLE: {leaked}"

    def test_modules_package_drops_decorators(self):
        names = ("operator", "processor", "splitter")
        assert not any(hasattr(riko.modules, name) for name in names)

    def test_stable_and_extension_do_not_intersect(self):
        common = STABLE & EXTENSION
        assert not common, f"Stable and extension surfaces intersect: {common}"

    def test_all_has_no_duplicates(self):
        duplicates = {
            module.__name__: sorted(
                {name for name in module.__all__ if module.__all__.count(name) > 1}
            )
            for module in SURFACE_MODULES
            if len(module.__all__) != len(set(module.__all__))
        }
        assert not duplicates, f"Duplicate __all__ entries: {duplicates}"

    @pytest.mark.parametrize("path", REMOVED_PUBLIC_PATHS)
    def test_removed_public_paths_are_gone(self, path):
        with pytest.raises(ModuleNotFoundError):
            import_module(path)


VERB_TABLE_MARKERS = [
    pytest.param("md", "<!-- verbs -->\n<!-- /verbs -->", "| `load` |", id="md"),
    pytest.param("rst", ".. begin verbs\n.. end verbs", "| ``load`` ", id="rst"),
    pytest.param(
        "md",
        "<!-- verb-rules -->\n<!-- /verb-rules -->",
        "| `load` | Loads | **MUST** cross",
        id="md-rules",
    ),
]


class TestGenerateVerbTables:
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

    def test_unknown_block_keys_are_reported(self, tmp_path: Path) -> None:
        path = tmp_path / "surface.md"
        path.write_text("<!-- api-surface:exprot -->\n<!-- /api-surface:exprot -->\n")
        offenders = gen_block_offenders(
            path,
            API_SURFACE_BLOCK,
            frozenset(),
            generate_api_surface,
            "--api",
            API_SURFACE_MARKERS,
        )
        assert next(offenders) == "surface.md: unknown or unclosed blocks ['exprot']"


def _plan(phases: dict[str, object], **tables: object) -> PlanningData:
    """Builds planning data from one plan file and no Markdown."""
    return PlanningData.from_documents({"plan": {"phases": phases, **tables}}, {})


PLANNING_STATUSES = [
    pytest.param({"X1": _LANDED}, {}, "X1", "complete", id="dated-landing"),
    pytest.param(
        {"X1": _LANDED, "X2": {"lands_with": ["X1"]}},
        {},
        "X2",
        "complete",
        id="rider-one-host",
    ),
    pytest.param(
        {"X1": _LANDED, "X2": {"lands_with": ["X1", "X3"]}, "X3": {}},
        {},
        "X2",
        "planned",
        id="rider-one-of-two-hosts",
    ),
    pytest.param(
        {
            "X1": {
                "slices": [{"id": "a", "deferred": True}, {"id": "b", "deferred": True}]
            }
        },
        {},
        "X1",
        "deferred",
        id="all-deferred",
    ),
    pytest.param(
        {
            "X1": {
                "slices": [{"id": "a", "landed": _DAY1}, {"id": "b", "deferred": True}]
            }
        },
        {},
        "X1",
        "complete",
        id="landed-and-deferred",
    ),
    pytest.param({"X1": {"designing": _DAY1}}, {}, "X1", "in_design", id="in-design"),
    pytest.param(
        {"X1": {"designing": _DAY1, "started": _DAY2}},
        {},
        "X1",
        "in_progress",
        id="in-progress",
    ),
    pytest.param(
        {"X1": {"slices": [{"id": "a", "landed": _DAY1}, {"id": "b"}]}},
        {},
        "X1",
        "in_progress",
        id="partly-landed",
    ),
    pytest.param(
        {"X1": _LANDED},
        {"MX": {"blocked_by": ["X1"]}},
        "MX",
        "in_progress",
        id="milestone-done-prerequisite",
    ),
    pytest.param(
        {"X1": {"started": _DAY1}},
        {"MX": {"blocked_by": ["X1"]}},
        "MX",
        "planned",
        id="milestone-started-prerequisite",
    ),
    pytest.param(
        {"X1": _LANDED, "X2": {"blocked_by": ["X1"]}},
        {"MX": {"blocked_by": ["X2"]}},
        "MX",
        "planned",
        id="milestone-transitive-prerequisite",
    ),
    pytest.param(
        {"X1": {}},
        {"MX": {"blocked_by": ["X1"]}},
        "MX",
        "planned",
        id="milestone-planned",
    ),
    pytest.param(
        {"X1": {"decisions": [{"id": "q", "settled": _DAY1}]}},
        {},
        "X1.q",
        "settled",
        id="settled-decision",
    ),
    pytest.param(
        {"X1": {"decisions": [{"id": "q"}]}}, {}, "X1.q", "open", id="open-decision"
    ),
]

PLANNING_HOMES = [
    pytest.param(
        _HOMES_PLAN,
        "### X1: Some title\n\n**X1.a: Slice title.** More.",
        "X1.a",
        "Slice title",
        "x1-some-title",
        "More.",
        id="own-prefix-slice",
    ),
    pytest.param(
        _HOMES_PLAN,
        "### X1: Some title\n\n- **ADD:** Add it.",
        "X1.add",
        None,
        "x1-some-title",
        "Add it.",
        id="exit-bullet",
    ),
    pytest.param(
        _HOMES_PLAN,
        "### X1: Some title\n\n**X1.a: Slice title.** More.\n1) Not more.",
        "X1.a",
        "Slice title",
        "x1-some-title",
        "More.",
        id="paren-list-item-after-lead-in",
    ),
    pytest.param(
        _HOMES_PLAN,
        "### X1: Some title\n\n**X1.a: Slice title.** More.\n| Not | more |",
        "X1.a",
        "Slice title",
        "x1-some-title",
        "More.",
        id="table-row-after-lead-in",
    ),
    pytest.param(
        _LOCAL_PLAN,
        "**S1: Local title.** More.",
        "plan.S1",
        "Local title",
        "",
        "More.",
        id="plan-local-slice",
    ),
    pytest.param(
        _LANE_PLAN,
        "**L1.D1: Ratchet.** More.",
        "L1.D1",
        "Ratchet",
        "",
        "More.",
        id="lane-slice",
    ),
    pytest.param(
        _HOMES_PLAN,
        "### X1: Some title\n\n**X1.a: Builds X2.b and e.g. 1.0 support.** More.",
        "X1.a",
        "Builds X2.b and e.g. 1.0 support",
        "x1-some-title",
        "More.",
        id="dotted-title",
    ),
    pytest.param(
        _HOMES_PLAN,
        "### X1: Some title\n\n**X1.a: Slice title** More.",
        "X1.a",
        "Slice title",
        "x1-some-title",
        "More.",
        id="unclosed-title",
    ),
]

PLANNING_PROBLEMS = [
    pytest.param(
        {"phases": {"X1": {"blocked_by": ["S5"]}}},
        "",
        "X1 names unknown ref S5 in blocked_by",
        id="unknown-ref",
    ),
    pytest.param(
        {"phases": {"X1": {}}, "milestones": {"X1": {}}},
        "",
        "id X1 is declared 2 times",
        id="duplicate-id",
    ),
    pytest.param(
        {"phases": {"X1": {"slices": [{"id": "a"}, {"id": "a"}]}}},
        "",
        "id X1.a is declared more than once",
        id="duplicate-slice",
    ),
    pytest.param(
        {"phases": {"X1": {"blocked_by": ["X2"]}, "X2": {"blocked_by": ["X1"]}}},
        "",
        "refs X1, X2 form a cycle",
        id="cycle",
    ),
    pytest.param(
        {"phases": {"X1": {}, "X2": {"blocked_by": ["X1"], "landed": _DAY1}}},
        "",
        "X2 landed before X1 completed",
        id="landed-before-prerequisite",
    ),
    pytest.param(
        {
            "phases": {
                "X1": {"landed": _DAY2},
                "X2": {"blocked_by": ["X1"], "landed": _DAY1},
            }
        },
        "",
        "X2 landed on 2026-01-01, before X1 landed",
        id="landed-earlier",
    ),
    pytest.param(
        {"phases": {"X1": {"slices": [{"id": "a"}, {"id": "b", "landed": _DAY1}]}}},
        "",
        "X1.b landed before X1.a completed",
        id="landed-before-chain",
    ),
    pytest.param(
        {
            "phases": {"X1": {}},
            "milestones": {"MX": {"blocked_by": ["X1"], "landed": _DAY1}},
        },
        "",
        "MX landed before X1 completed",
        id="milestone-unmet",
    ),
    pytest.param(
        {
            "phases": {
                "X1": {"decisions": [{"id": "q"}]},
                "X2": {"blocked_by": ["X1.q"], "started": _DAY1},
            }
        },
        "",
        "X2 started while X1.q is open",
        id="started-under-open-decision",
    ),
    pytest.param(
        {"phases": {"X1": {"landed": date(2027, 1, 1)}}},
        "",
        "X1 has a future landed date, 2027-01-01",
        id="future-date",
    ),
    pytest.param(
        {"phases": {"X1": {"doc": "plan.md"}}},
        "",
        "planning phase X1 has no Markdown home",
        id="node-without-home",
    ),
    pytest.param(
        {"phases": {"X1": {"doc": "plan.md", "slices": [{"id": "a"}]}}},
        _X1_HEADING,
        "slice X1.a has no Markdown home",
        id="slice-without-home",
    ),
    pytest.param(
        {"phases": {"X1": {"doc": "plan.md", "decisions": [{"id": "q"}]}}},
        _X1_HEADING,
        "decision X1.q has no Markdown home",
        id="decision-without-home",
    ),
    pytest.param(
        {"lanes": {"L1": {"owner": "user"}}},
        "",
        "lane L1 has no Markdown home",
        id="lane-without-home",
    ),
    pytest.param(
        {"phases": {"X1": {"area": "core"}}},
        "",
        "planning phase X1 names unknown area core",
        id="unknown-area",
    ),
    pytest.param(
        {},
        "## X9: Stray\n",
        "heading 'X9' in plan.md names no planning id",
        id="stray-heading",
    ),
    pytest.param(
        {"phases": {"X1": {"doc": "plan.md"}}},
        f"{_X1_HEADING}**X1.z: Nothing.** Text.",
        "lead-in 'X1.z' in plan.md names no planning id",
        id="stray-lead-in",
    ),
    pytest.param(
        {"phases": {"X1": {"doc": "plan.md", "slices": [{"id": "a"}]}}},
        f"{_X1_HEADING}**X1.a: Slice title** Text.",
        "lead-in 'X1.a' in plan.md needs a bold title ending with a period",
        id="unclosed-lead-in",
    ),
    pytest.param(
        {"phases": {"X1": {"doc": "plan.md"}, "X2": {}}},
        f"{_X1_HEADING}**X2: Needs it.** Text.",
        "edge X1 does not have",
        id="reason-without-edge",
    ),
    pytest.param(
        {"phases": {"X1": {"doc": "plan.md"}}},
        "**X1: Stray.** Text.",
        "lead-in 'X1' in plan.md names no planning id",
        id="bare-id-lead-in",
    ),
    pytest.param(
        {"phases": {"X1": {}}}, "", "planning phase X1 unlocks nothing", id="dead-end"
    ),
    pytest.param(
        {"phases": {"X1": {}}},
        None,
        "plan.toml has no sibling Markdown file plan.md",
        id="no-sibling-markdown",
    ),
    pytest.param(
        {"phases": {"X1": {"landed": _DAY1, "flips": ["tests/x.py"]}}},
        "",
        "X1 names malformed test id 'tests/x.py'",
        id="malformed-flip",
    ),
    pytest.param(
        {"phases": {"X1": {"decisions": [{"id": "q"}], "slices": [_Q_RIDER]}}},
        "",
        "X1.a names decision X1.q in lands_with, which never lands",
        id="decision-host",
    ),
]

LIVE_PHASES = [
    pytest.param({"X1": _LANDED}, {}, id="complete"),
    pytest.param(
        {"X1": {}}, {"MX": {"blocked_by": ["X1"], "proposed": True}}, id="proposed"
    ),
]

NEXT_SLICES = [
    pytest.param(
        {"X1": {}, "X2": {}},
        {
            "MA": {"blocked_by": ["X2"]},
            "MB": {"blocked_by": ["X1"], "scheduled_after": ["MA"]},
        },
        ("X2", "X1"),
        id="earlier-milestone-first",
    ),
    pytest.param(
        {"X0": {}, "X1": {}},
        {"MA": {"blocked_by": ["X1"]}},
        ("X1", "X0"),
        id="no-milestone-last",
    ),
]

PLANNING_UNLOCKS = [
    pytest.param(
        {"X1": {"slices": [{"id": "a"}]}, "X2": {"blocked_by": ["X1.a"]}},
        "X1",
        (Unlock("X2", "X1.a", "blocked_by", None),),
        id="slice-upstream",
    ),
    pytest.param(
        {"X1": {}, "X2": {"scheduled_after": ["X1"]}},
        "X1",
        (Unlock("X2", "X1", "scheduled_after", None),),
        id="scheduled-after",
    ),
    pytest.param(
        {"X1": {}, "X2": {"blocked_by": ["X1"]}}, "X2", (), id="prerequisites-excluded"
    ),
]

MISSING_HOMES = [
    pytest.param(
        {"X1": {"doc": "plan.md"}}, "planning phase X1 has no Markdown home", id="phase"
    ),
    pytest.param(
        {"X1": {"area": "core"}}, "planning phase X1 names unknown area core", id="area"
    ),
]


class TestPlanningData:
    """Planning data joined from TOML facts and Markdown homes, and its views."""

    @pytest.mark.parametrize(
        ("phases", "milestones", "ref", "status"), PLANNING_STATUSES
    )
    def test_status_derives_from_its_slices_and_hosts(
        self, phases, milestones, ref, status
    ):
        assert _plan(phases, milestones=milestones).get_status(ref) == status

    def test_rider_lands_with_its_latest_host(self):
        phases = {
            "X1": _LANDED,
            "X2": {"lands_with": ["X1", "X3"]},
            "X3": {"landed": _DAY3},
        }
        assert _plan(phases).get_landed("X2") == _DAY3

    def test_scheduled_after_reorders(self):
        data = _plan({"X1": {"scheduled_after": ["X2"]}, "X2": {}})
        assert data.order == ("X2", "X1")

    def test_ties_use_natural_sort(self):
        assert _plan({"X10": {}, "X4B": {}, "X4A": {}}).order == ("X4A", "X4B", "X10")

    def test_open_decision_skips_a_next_slice(self):
        phases = {
            "X1": {"decisions": [{"id": "q"}]},
            "X2": {"blocked_by": ["X1.q"]},
            "X3": {},
        }
        assert _plan(phases).next_slices == ("X1", "X3")

    @pytest.mark.parametrize(("phases", "milestones", "refs"), NEXT_SLICES)
    def test_next_slices_rank_by_the_milestone_they_feed(
        self, phases, milestones, refs
    ):
        assert _plan(phases, milestones=milestones).next_slices == refs

    def test_unlocks_carry_the_short_reason_and_detail(self):
        plan = {"phases": {"X1": {"doc": "plan.md", "blocked_by": ["X2"]}, "X2": {}}}
        text = "## X1: First\n\n**X2: Needs it.** Badly. Detail.\n"
        data = PlanningData.from_documents({"plan": plan}, {"plan.md": text})
        reason = data.reasons["X1", "X2"]
        assert data.get_unlocks("X2") == (Unlock("X1", "X2", "blocked_by", reason),)
        assert (reason.title, reason.detail) == ("Needs it", "Badly. Detail.")

    @pytest.mark.parametrize(("phases", "ref", "unlocks"), PLANNING_UNLOCKS)
    def test_unlocks_point_downstream(self, phases, ref, unlocks):
        assert _plan(phases).get_unlocks(ref) == unlocks

    @pytest.mark.parametrize(
        ("plan", "text", "key", "title", "anchor", "detail"), PLANNING_HOMES
    )
    def test_markdown_homes_classify_by_section(
        self, plan, text, key, title, anchor, detail
    ):
        data = PlanningData.from_documents({"plan": plan}, {"plan.md": text})
        section = data.sections[key]
        assert (section.title, section.anchor, section.detail) == (
            title,
            anchor,
            detail,
        )

    @pytest.mark.parametrize(("phases", "milestones"), LIVE_PHASES)
    def test_live_phase_is_no_dead_end(self, phases, milestones):
        problems = _plan(phases, milestones=milestones).gen_problems(_TODAY)
        assert "unlocks nothing" not in "\n".join(map(str, problems))

    def test_deferred_slice_leaves_the_chain(self):
        slices = [{"id": "a", "deferred": True}, {"id": "b", **_LANDED}]
        problems = _plan({"X1": {"slices": slices}}).gen_problems(_TODAY)
        assert "landed before" not in "\n".join(map(str, problems))

    @pytest.mark.parametrize(("plan", "text", "problem"), PLANNING_PROBLEMS)
    def test_problems_name_the_offending_id(self, plan, text, problem):
        docs = {} if text is None else {"plan.md": text}
        problems = PlanningData.from_documents({"plan": plan}, docs).gen_problems(
            _TODAY
        )
        assert problem in "\n".join(map(str, problems))

    @pytest.mark.parametrize(("phases", "problem"), MISSING_HOMES)
    def test_missing_homes_have_their_own_kind(self, phases, problem):
        problems = _plan(phases).gen_problems(_TODAY)
        assert Problem(problem, "missing_home") in problems


class TestGenSections:
    """Planning headings, lead-ins, and exit bullets parsed from Markdown."""

    def test_fenced_headings_and_repeated_anchors(self):
        text = "## X1: A\n\n```\n## X2: B\n```\n\n## X1: A\n"
        anchors = [section.anchor for section in gen_sections("plan.md", text)]
        assert anchors == ["x1-a", "x1-a-1"]


PLAN_FILE_ERRORS = [
    pytest.param(
        {"X1": {"landed": _DAY1, "deferred": True}},
        "exclude each other",
        id="exclusive-landing",
    ),
    pytest.param(
        {"X1": {"started": _DAY2, "landed": _DAY1}},
        "dates must run",
        id="misordered-dates",
    ),
    pytest.param(
        {"X1": {"started": _DAY1, "elapsed_days": 2}},
        "timing fields need",
        id="timing-unlanded",
    ),
    pytest.param(
        {"X1": {"landed": True}},
        "'landed' must be a date, not bool",
        id="undated-landing",
    ),
    pytest.param(
        {"X1": {"slices": [], "landed": _DAY1}},
        "['landed'] belong on them",
        id="container-slice-keys",
    ),
    pytest.param(
        {"X1": {"priority": 1}},
        "unknown plan.toml phases.X1 key(s): ['priority']",
        id="unknown-key",
    ),
    pytest.param(
        {"X1": {"title": "First"}}, "plan.toml phases.X1 has ['title']", id="title-key"
    ),
]


class TestPlanFile:
    """Planning TOML files whose shape breaks the schema."""

    @pytest.mark.parametrize(("phases", "message"), PLAN_FILE_ERRORS)
    def test_malformed_shape_raises(self, phases, message):
        with pytest.raises(PlanningError, match=re.escape(message)):
            PlanFile.from_toml("plan", {"phases": phases})


PLANNING_BLOCKS = [
    pytest.param(
        "track-r",
        "plan.md",
        "| [R20 · First phase](#r20-first-phase) | In progress |  | "
        "R21 (needs the base) |",
        id="track-row",
    ),
    pytest.param(
        "track-r",
        "plan.md",
        "| [R21 · Second phase](#r21-second-phase) | Planned |  | M20, before P20 |",
        id="track-scheduled-after",
    ),
    pytest.param(
        "track-r",
        "plan.md",
        "| [M20 · Preview](#m20-preview) (proposed) | Planned |  |  |",
        id="track-proposed-milestone",
    ),
    pytest.param(
        "track-p",
        "plan.md",
        "| [P20 · Track item](../tracker.md#p20-track-item) | Planned |  |  |",
        id="track-relative-link",
    ),
    pytest.param(
        "graph", "plan.md", '    subgraph a_core["Core work"]', id="graph-area"
    ),
    pytest.param("graph", "plan.md", "    n_R20 --> n_R21", id="graph-blocked-by"),
    pytest.param(
        "graph", "plan.md", "    n_R21 -.-> n_P20", id="graph-scheduled-after"
    ),
    pytest.param(
        "graph", "plan.md", "    class n_M20 proposed", id="graph-proposed-class"
    ),
    pytest.param(
        "next",
        "plan.md",
        "| R20.b | [R20 · First phase](#r20-first-phase) | Planned |  |",
        id="next",
    ),
    pytest.param(
        "lanes",
        "plan.md",
        "| [tidy · Tidy lane](#lanes) | user | weekly | R21 | Planned |",
        id="lanes",
    ),
    pytest.param(
        "decisions",
        "plan.md",
        "| [R20.q · A question](#r20-first-phase) | "
        "[R20 · First phase](#r20-first-phase) | Open |  |",
        id="decisions",
    ),
    pytest.param(
        "slices", "stream.md", "| S1 · Local slice | R21 | Planned |", id="slices"
    ),
]


class TestGeneratePlanningBlocks:
    """Planning tables and graph generated from the planning data."""

    @pytest.mark.parametrize(("key", "doc", "row"), PLANNING_BLOCKS)
    def test_block_renders_its_row_and_is_idempotent(self, key, doc, row):
        data = PlanningData.from_documents(_RENDER_PLANS, _RENDER_DOCS)
        text = f"<!-- planning-{key} -->\n<!-- /planning-{key} -->\n"
        generated = generate_planning_blocks(text, data, doc)
        assert row in generated.splitlines()
        assert generate_planning_blocks(generated, data, doc) == generated


class TestBuildExport:
    """The JSON export of the planning model."""

    def test_export_links_each_home_at_the_commit(self):
        data = PlanningData.from_documents(_RENDER_PLANS, _RENDER_DOCS)
        exported = json.loads(json.dumps(build_export(data, _SNAPSHOT)))
        keys = ["snapshot", "order", "next", "areas", "nodes", "slices", "decisions"]
        assert list(exported) == [*keys, "lanes"]
        node = next(node for node in exported["nodes"] if node["ref"] == "P20")
        docs = GAMEPLANS_DIR.parent.relative_to(ROOT_DIR).as_posix()
        url = f"https://example.com/repo/blob/abc123/{docs}/tracker.md#p20-track-item"
        assert node["plan_url"] == url
        assert exported["snapshot"]["commit"] == "abc123"

    def test_export_pins_a_lead_in_to_its_line(self):
        data = PlanningData.from_documents(_TRACK_PLANS, _TRACK_DOCS)
        exported = build_export(data, _SNAPSHOT)
        found = exported["slices"]
        assert isinstance(found, list)
        item = next(item for item in found if item["ref"] == "R91.a")
        docs = GAMEPLANS_DIR.relative_to(ROOT_DIR).as_posix()
        url = f"https://example.com/repo/blob/abc123/{docs}/plan.md?plain=1#L17"
        location = (item["doc"], item["section"], item["line"], item["plan_url"])
        assert location == ("plan.md", "R91: Split", 17, url)


FORWARD_TRACK_FIELDS = [
    pytest.param(("focus", "phase"), "R91", id="focus-phase"),
    pytest.param(("focus", "milestone"), "M90", id="focus-milestone"),
    pytest.param(
        ("focus", "decision"),
        {"heading": "Split question", "body": "Why split."},
        id="focus-own-decision",
    ),
    pytest.param(("phases", "R90", "status"), "landed", id="phase-landed"),
    pytest.param(("phases", "R91", "status"), "next_up", id="phase-next-up"),
    pytest.param(("phases", "R92", "status"), "pending", id="phase-pending"),
    pytest.param(
        ("phases", "R90", "work", "add", "status"), "complete", id="work-complete"
    ),
    pytest.param(
        ("phases", "R91", "work", "a", "status"), "next_up", id="work-next-up"
    ),
    pytest.param(
        ("phases", "R94", "work", "add", "status"), "in_progress", id="work-in-design"
    ),
    pytest.param(
        ("phases", "R93", "work", "add", "status"), "planned", id="work-planned"
    ),
    pytest.param(("phases", "R91", "workKind"), "slices", id="work-kind-slices"),
    pytest.param(("phases", "R92", "workKind"), "implementation", id="work-kind-exits"),
    pytest.param(("phases", "R92", "work", "add", "title"), "R92 · ADD", id="exit"),
    pytest.param(
        ("phases", "R91", "work", "a", "title"), "R91.a · First slice", id="work-label"
    ),
    pytest.param(
        ("phases", "R91", "work", "stream-s90", "title"),
        "R91.a · Riding slice",
        id="rider-label",
    ),
    pytest.param(
        ("phases", "R91", "work", "a", "location"),
        "plan.md › R91 › R91.a",
        id="work-location",
    ),
    pytest.param(
        ("phases", "R91", "work", "stream-s90", "location"),
        "stream.md › S90",
        id="rider-location",
    ),
    pytest.param(
        ("phases", "R91", "work", "ids"),
        ["a", "stream-s90", "b"],
        id="plan-slice-after-its-host",
    ),
    pytest.param(
        ("phases", "R91", "work", "stream-s90", "tag"), "S90", id="plan-slice-tag"
    ),
    pytest.param(
        ("phases", "R90", "dependency"),
        {
            "kind": "unlocks",
            "badge": "Unlocks R91",
            "detail": "needs the base",
            "targets": ["R91", "R92"],
        },
        id="dependency-unlocks",
    ),
    pytest.param(
        ("phases", "R94", "dependency"),
        {
            "kind": "scheduled_before",
            "badge": "Before R93",
            "detail": "Later",
            "targets": ["R93"],
        },
        id="dependency-scheduled",
    ),
    pytest.param(
        ("phases", "R93", "dependency"),
        {
            "kind": "proposed",
            "badge": "Unlocks M93",
            "detail": "Preview",
            "targets": ["m93"],
        },
        id="dependency-proposed",
    ),
    pytest.param(
        ("schedule", "stages", "m90", "lanes", 0, "steps", "ids"),
        ["r90", "r91-a", "m90"],
        id="split-first-leg",
    ),
    pytest.param(
        ("schedule", "stages", "m91", "lanes", 0, "steps", "r91-b", "label"),
        "Second slice",
        id="split-later-leg",
    ),
    pytest.param(
        ("schedule", "bridges"),
        [
            {
                "afterStage": "m90",
                "inputs": [{"step": "r90", "label": "needs the base"}],
                "output": {"step": "r92", "label": "R92"},
            }
        ],
        id="bridge-across-lanes",
    ),
    pytest.param(
        ("schedule", "outcomes", "m93"),
        {
            "id": "m93",
            "afterStep": "r93",
            "title": "Preview",
            "detail": "Maybe ship.",
            "proposed": True,
        },
        id="proposed-outcome",
    ),
    pytest.param(
        ("schedule", "outcomes", "m91", "proposed"), False, id="final-outcome"
    ),
    pytest.param(("history", 0, "when"), "1 Jan 2026", id="history-day"),
]


def _build_track() -> dict[str, object]:
    """Builds the forward-track view of the synthetic plans."""
    data = PlanningData.from_documents(_TRACK_PLANS, _TRACK_DOCS)
    return build_forward_track(data, _TRACK_SNAPSHOT, _TRACK_PAGE, _TRACK_RELEASES)


def _find(value: object, *path: str | int) -> object:
    """Finds a view value by key, list index, or record id; ``ids`` lists the ids."""
    for key in path:
        if key == "ids" and isinstance(value, list):
            value = [item["id"] for item in value]
        elif isinstance(value, list) and isinstance(key, str):
            value = next(item for item in value if item["id"] == key)
        elif isinstance(value, list):
            value = value[int(key)]
        elif isinstance(value, dict):
            value = value[key]

    return value


class TestBuildForwardTrack:
    """The forward-track view of the planning data and its cross-reference checks."""

    def test_track_validates_against_the_committed_schema(self):
        track = _build_track()
        assert load_validator()(track) == track
        assert list(gen_forward_track_problems(track)) == []

    @pytest.mark.parametrize(("path", "expected"), FORWARD_TRACK_FIELDS)
    def test_field_maps_from_the_planning_data(self, path, expected):
        track = _build_track()
        assert _find(track, *path) == expected

    def test_doubled_next_up_is_a_problem(self):
        track = _build_track()
        found = track["phases"]
        assert isinstance(found, list)
        phases = [
            {**phase, "status": "next_up"} if phase["id"] == "R92" else phase
            for phase in found
        ]
        problems = gen_forward_track_problems({**track, "phases": phases})
        assert list(problems) == [
            "next-up phases ['R91', 'R92'] are not the focus phase R91 alone"
        ]
