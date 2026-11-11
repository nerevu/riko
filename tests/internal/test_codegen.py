# vim: sw=4:ts=4:expandtab
"""Provides internal tests for codegen of workflows, names, ids, configs, and docs."""

from __future__ import annotations

import ast
import dataclasses
import importlib.util
import json
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
    MODULE_IDS_PATH,
    MODULE_NAMES_PATH,
    USER_AGENTS_PATH,
)
from riko.base._strutils import get_codegen_note, pythonise
from riko.cli._gen_api_surface import generate_api_surface
from riko.cli._gen_config import objconf_structure, render
from riko.cli._gen_user_agents import (
    USER_AGENT_COUNT,
    generate_user_agents,
    get_top_agents,
    load_user_agents,
)
from riko.cli._gen_verbs import TableFormat, generate_verb_tables
from riko.definitions._context import Context
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
from riko.types._workflow import Endpoint
from riko.types._wrappers import WrapperMeta, require_wrapper_meta
from riko.types.modules import (
    ConfArg,
    RenameRawConf,
    RenameRawRule,
    SortRawConf,
    SortRawRule,
)
from tests import TESTS_DIR, async_test, is_installed
from tests._workflows import EXAMPLES_DIR, SPLIT_PENDING, run_document, run_workflow

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

FIXTURE_MARKS = {
    "pipe_QMrlL_FS3BGlpwryODY80A": (SPLIT_PENDING,),
    "pipe_zKJifuNS3BGLRQK_GsevXg": (SPLIT_PENDING,),
}

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
PROBE_MARKS = {"pipe_zKJifuNS3BGLRQK_GsevXg": (SPLIT_PENDING,)}

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

    async with AsyncExecution(context=Context(test=True)) as execution:
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
        assert list(module.pipe(context=Context(test=True))) == run_workflow(flow)

    @pytest.mark.parametrize("path", _compile_fixtures(unrunnable=True))
    def test_generated_matches_document_failure(self, path: Path, tmp_path: Path):
        """A document that cannot run standalone fails the same way once generated."""
        flow = Workflow.parse(path.read_text())

        def run_generated() -> list[object]:
            module = _build(flow, path.stem, tmp_path)
            return list(module.pipe(context=Context(test=True)))

        generated = _failure(run_generated)
        assert generated == _failure(lambda: run_workflow(flow))

    @pytest.mark.parametrize("stem", ASYNC_FIXTURES)
    @async_test
    async def test_async_generated_matches_document(self, stem: str, tmp_path: Path):
        """Each generated async module yields the items its document yields."""
        path = TESTS_DIR / "workflows" / f"{stem}.json"
        flow = Workflow.parse(path.read_text())
        module = _build(flow, stem, tmp_path, is_async=True)
        stream = module.async_pipe(context=Context(test=True))
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
        assert list(module.pipe(context=Context(test=True))) == run_workflow(flow)

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

    def test_empty_fields_are_left_out(self, tmp_path: Path):
        """A workflow without edges or input schemas generates neither keyword."""
        flow = Pipeline.from_module("hash").workflow
        source = compile_workflow(flow, "pipe_bare")
        assert "edges=" not in source
        assert "input_schemas=" not in source
        assert _load(source, "pipe_bare", tmp_path).flow == flow

    def test_generated_source_parses(self, tmp_path: Path):
        """The generated source is valid Python and imports without running."""
        flow = (
            Pipeline.from_module("itembuilder")
            .pipe("rename", conf=RENAME_CONF)
            .workflow
        )
        source = compile_workflow(flow, "pipe_parsed")
        ast.parse(source)
        module = _load(source, "pipe_parsed", tmp_path)
        assert module.flow.outputs["default"] == Endpoint("rename-1", "out")


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


class TestGeneratedNamesDrift:
    def test_generated_names_match(self):
        entries = gen_catalog_entries()
        name_lines = MODULE_NAMES_PATH.read_text().splitlines()
        generated_lines = generate_module_names(*entries).splitlines()

        for actual, expected in zip(name_lines, generated_lines, strict=True):
            assert actual == expected


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
class TestUserAgentCodegen:
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
        stream = module.pipe(context=Context(test=True))

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
