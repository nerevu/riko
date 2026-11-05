# vim: sw=4:ts=4:expandtab
"""Provides internal tests for codegen of workflows, names, ids, and configs."""

from __future__ import annotations

import ast
import dataclasses
import importlib.util
from importlib import import_module
from keyword import iskeyword
from typing import TYPE_CHECKING, Any

import pytest

from riko.base._exceptions import InvalidPipelineError
from riko.base._paths import PACKAGE_DIR
from riko.base._strutils import pythonise
from riko.cli._gen_config import objconf_structure, render
from riko.definitions._context import Context
from riko.definitions._nodes import ModuleNode, WriteNode
from riko.definitions._workflow_definition import Workflow, normalize_workflow
from riko.execution._async_execution import AsyncExecution
from riko.execution._prepared import ExecutionPlan
from riko.ext.codegen import (
    NameEntry,
    enum_member_name,
    gen_catalog_entries,
    generate_module_ids,
    generate_module_names,
)
from riko.modules._metadata import gen_module_catalog, get_module_category, list_modules
from riko.runtime._compile import compile_workflow
from riko.runtime._pipeline import Pipeline
from riko.runtime._resolver import dispatcher
from riko.runtime._workflow_resolver import _build_resolved_workflow
from riko.types._enums import ExecutionMode
from riko.types._workflow import Endpoint
from riko.types.modules import (
    ConfArg,
    RenameRawConf,
    RenameRawRule,
    SortRawConf,
    SortRawRule,
)
from tests import TESTS_DIR, async_test
from tests._workflows import (
    EXAMPLES_DIR,
    SPLIT_PENDING,
    gen_fixture_paths,
    run_document,
    run_workflow,
)

if TYPE_CHECKING:
    from pathlib import Path
    from types import ModuleType

    from riko.types._streams import Item
    from riko.types.modules import ModuleCategory

RENAME_CONF = RenameRawConf(
    {
        "rule": RenameRawRule(
            field=ConfArg(type="text", value="content"),
            newval=ConfArg(type="text", value="greeting"),
        )
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


class TestWorkflowModule:
    """
    A workflow module produces exactly what running its workflow document produces.

    The equivalence holds over every committed fixture in both the sync and async
    interface.
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
        module = _build(flow, path.stem, tmp_path)
        generated = _failure(lambda: list(module.pipe(context=Context(test=True))))
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

    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            pytest.param({"content": "hello"}, [{"greeting": "hello"}], id="one-item"),
            pytest.param(
                [{"content": "hello"}, {"content": "bye"}],
                [{"greeting": "hello"}, {"greeting": "bye"}],
                id="stream",
            ),
        ],
    )
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


DESCRIBED_INPUTS = {"limit": {"type": "integer"}}
DESCRIBE_INPUT_CASES = [
    pytest.param(ExecutionMode.DESCRIBE_INPUTS, DESCRIBED_INPUTS, id="inputs"),
    pytest.param(
        ExecutionMode.DESCRIBE,
        {"inputs": DESCRIBED_INPUTS, "dependencies": ["rename"]},
        id="inputs-and-dependencies",
    ),
]


def _inputs_workflow() -> Workflow:
    """Builds a one-node workflow that declares an input."""
    node = ModuleNode(id="rename-1", name="rename", conf=RENAME_CONF)
    outputs = {"default": Endpoint(node.id, "out")}
    return Workflow(nodes=[node], outputs=outputs, inputs=DESCRIBED_INPUTS)


class TestWorkflowModuleDescribe:
    def test_generated_pipe_describes_dependencies(self, tmp_path: Path):
        """Describing dependencies reports the workflow's module names, sorted."""
        pipeline = Pipeline.from_module("itembuilder").pipe("rename", conf=RENAME_CONF)
        module = _build(pipeline.workflow, "pipe_described", tmp_path)
        context = Context(mode=ExecutionMode.DESCRIBE_DEPENDENCIES)
        assert list(module.pipe(context=context)) == ["itembuilder", "rename"]

    @async_test
    async def test_generated_async_pipe_describes_dependencies(self, tmp_path: Path):
        pipeline = Pipeline.from_module("itembuilder").pipe("rename", conf=RENAME_CONF)
        module = _build(pipeline.workflow, "pipe_adescribed", tmp_path, is_async=True)
        stream = module.async_pipe(
            context=Context(mode=ExecutionMode.DESCRIBE_DEPENDENCIES)
        )
        assert [item async for item in stream] == ["itembuilder", "rename"]

    @pytest.mark.parametrize(("mode", "expected"), DESCRIBE_INPUT_CASES)
    def test_generated_pipe_describes_inputs(self, mode, expected, tmp_path: Path):
        """Describing inputs reports the declared schemas, alone or with more."""
        module = _build(_inputs_workflow(), "pipe_inputs", tmp_path)
        assert module.pipe(context=Context(mode=mode)) == expected

    @pytest.mark.parametrize(("mode", "expected"), DESCRIBE_INPUT_CASES)
    @async_test
    async def test_generated_async_pipe_describes_inputs(
        self, mode, expected, tmp_path: Path
    ):
        """The async interface yields the same description as one item."""
        module = _build(_inputs_workflow(), "pipe_ainputs", tmp_path, is_async=True)
        stream = module.async_pipe(context=Context(mode=mode))
        assert [item async for item in stream] == [expected]


SORT_CONF = SortRawConf(
    {"rule": SortRawRule(field=ConfArg(type="text", value="title"))}
)


def _loop_workflow() -> Workflow:
    """Parses the committed loop fixture whose embed carries a typed config."""
    data = (TESTS_DIR / "workflows" / "pipe_loop_assign.json").read_text()
    return Workflow.parse(data)


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
        flow = normalize_workflow({"nodes": [{"name": "itembuilder", "conf": conf}]})
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

    def test_loop_embed_is_rendered_as_a_node_field(self):
        """A loop node's embedded module is rebuilt from the typed ``Embed``."""
        source = compile_workflow(_loop_workflow(), "pipe_x")
        assert "embed=Embed(" in source
        assert "LoopConf" not in source

    def test_write_node_is_refused(self):
        """A workflow with a node family that has no generated form is refused."""
        node = WriteNode(id="write-1", name="write", backend="file", dest="out.csv")
        flow = Workflow(nodes=[node], outputs={"default": Endpoint(node.id, "out")})

        with pytest.raises(InvalidPipelineError, match="write node code generation"):
            compile_workflow(flow, "pipe_written")

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "a public import path for generated workflow modules is not yet implemented"
        ),
    )
    def test_generated_source_imports_no_private_module(self):
        """A generated workflow module imports only supported riko paths."""
        flow = Pipeline.from_module("itembuilder").workflow
        assert "from riko.runtime._" not in compile_workflow(flow, "pipe_public")


class TestPythonise:
    @pytest.mark.xfail(
        reason="pythonise does not sanitize ids into valid identifiers yet", strict=True
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


@pytest.fixture
def categories() -> dict[str, ModuleCategory]:
    return {md.name: get_module_category(md) for md in gen_module_catalog()}


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
        assert get_module_category(renamed) == "sink"

    @pytest.mark.xfail(
        strict=True,
        reason="replacing the write module with write nodes is not yet implemented",
    )
    def test_no_module_is_a_sink(self):
        """Writes run through targets, so no module is categorized as a sink."""
        assert list_modules(category="sink") == []


class TestEnumMemberName:
    @pytest.mark.parametrize(
        ("name", "override", "expected"),
        [
            ("fetch", None, "FETCH"),
            ("fetch-page", None, "FETCH_PAGE"),
            ("microsoft.autopilot.ensure", None, "MICROSOFT_AUTOPILOT_ENSURE"),
            ("a--b..c", None, "A_B_C"),
            ("3m", None, "_3M"),
            ("fetch", "grab", "GRAB"),
        ],
    )
    def test_enum_member_name(self, name, override, expected):
        assert enum_member_name(name, override=override) == expected


_NAMES = PACKAGE_DIR / "modules" / "_names.py"
MEMBER_COLLISIONS = (
    pytest.param("my_mod", "my-mod", id="builtin"),
    pytest.param("example.my_mod", "example.my-mod", id="provider"),
)


def _exec_generated_names(*entries: NameEntry) -> dict:
    namespace: dict = {}
    exec(generate_module_names(*entries), namespace)
    return namespace


class TestGenerateModuleNames:
    def test_generated_names_match(self):
        entries = gen_catalog_entries()
        name_lines = _NAMES.read_text().splitlines()
        generated_lines = generate_module_names(*entries).splitlines()

        for actual, expected in zip(name_lines, generated_lines, strict=True):
            assert actual == expected

    def test_generation_is_order_independent(self):
        entries = list(gen_catalog_entries())
        assert generate_module_names(*entries) == generate_module_names(
            *reversed(entries)
        )

    def test_enum_name_override_resolves_collision(self):
        entries = [
            NameEntry(name="my_mod", category="transform"),
            NameEntry(name="my-mod", category="transform", enum_name="my_mod_alt"),
        ]
        transforms = _exec_generated_names(*entries)["Transforms"]

        assert transforms.MY_MOD_ALT.value == "my-mod"
        assert transforms.MY_MOD.value == "my_mod"

    def test_provider_namespace_flattens(self):
        builtin = NameEntry(name="fetch", category="source")
        entry = NameEntry(name="microsoft.autopilot.ensure", category="transform")
        namespace = _exec_generated_names(builtin, entry)
        provider = namespace["Microsoft"]
        modules = namespace["Modules"]

        assert entry.provider == "microsoft"
        assert entry.class_name == "Microsoft"
        assert entry.member == "AUTOPILOT_ENSURE"
        assert entry.alias == "MICROSOFT_AUTOPILOT_ENSURE"
        assert provider.AUTOPILOT_ENSURE.value == "microsoft.autopilot.ensure"
        assert modules.MICROSOFT_AUTOPILOT_ENSURE is provider.AUTOPILOT_ENSURE
        assert "AUTOPILOT_ENSURE" not in namespace["Transforms"].__members__

    @pytest.mark.parametrize(("first", "second"), MEMBER_COLLISIONS)
    def test_member_collision_fails_with_diagnostic(self, first, second):
        entries = [
            NameEntry(name=first, category="transform"),
            NameEntry(name=second, category="transform"),
        ]

        with pytest.raises(ValueError, match="enum_name") as excinfo:
            generate_module_names(*entries)

        assert repr(first) in str(excinfo.value)
        assert repr(second) in str(excinfo.value)


_MODULE_IDS = PACKAGE_DIR / "types" / "_module_ids.py"


class TestGenerateModuleIds:
    def test_generated_module_ids_match(self):
        assert _MODULE_IDS.read_text() == generate_module_ids()


_CONFIGS = PACKAGE_DIR / "coercion" / "_configs.py"


class TestConfigCodegen:
    """Run ``manage codegen --config`` to update generated configs."""

    def test_configs_match_generated(self):
        assert _CONFIGS.read_text() == render()

    def test_fetchtable_inherits_csv(self):
        assert objconf_structure()["FetchTableObjconf"][0] == "CsvObjconf"


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


PROBE_PACKAGES = {
    TESTS_DIR / "pyworkflows": "tests.pyworkflows",
    EXAMPLES_DIR / "pyworkflows": "examples.pyworkflows",
}

# A stored-workflow fixture: it is only meaningful when another workflow embeds it.
SUBPIPE_ONLY = frozenset({"pipe_bd0834cfe6cdacb0bea5569505d330b8"})

PROBE_MARKS = {"pipe_zKJifuNS3BGLRQK_GsevXg": (SPLIT_PENDING,)}


def _probes() -> list[Any]:
    params = []

    for directory, package in PROBE_PACKAGES.items():
        for path in sorted(directory.glob("pipe_*.py")):
            document = directory.parent / "workflows" / f"{path.stem}.json"

            if not document.exists() or path.stem in SUBPIPE_ONLY:
                continue

            marks = PROBE_MARKS.get(path.stem, ())
            param = pytest.param(package, document, id=path.stem, marks=marks)
            params.append(param)

    return params


def _describing_probes(attr: str) -> list[Any]:
    return [
        pytest.param(f"{package}.{path.stem}", id=path.stem)
        for directory, package in PROBE_PACKAGES.items()
        for path in sorted(directory.glob("pipe_*.py"))
        if attr in path.read_text() and "describe_input" in path.read_text()
    ]


def _run_probe(package: str, name: str) -> list[object]:
    module = import_module(f"{package}.{name}")

    if package.startswith("examples"):
        stream = module.pipe(test=True)
    else:
        stream = module.pipe(context=Context(test=True))

    return list(stream)


class TestWorkflowProbes:
    @pytest.mark.parametrize(("package", "path"), _probes())
    def test_probe_matches_document(self, package: str, path: Path):
        """Each Python probe yields the items its workflow document yields."""
        expected = _run_probe(package, path.stem)
        assert run_document(path) == expected

    @pytest.mark.parametrize("name", _describing_probes("def pipe("))
    def test_probe_describes_inputs_and_dependencies(self, name: str):
        """Describing everything reports what each describe mode reports on its own."""
        probe = import_module(name)
        inputs = probe.pipe(context=Context(mode=ExecutionMode.DESCRIBE_INPUTS))
        mode = ExecutionMode.DESCRIBE_DEPENDENCIES
        dependencies = list(probe.pipe(context=Context(mode=mode)))
        expected = {"inputs": inputs, "dependencies": dependencies}
        assert probe.pipe(context=Context(mode=ExecutionMode.DESCRIBE)) == expected

    @pytest.mark.parametrize("name", _describing_probes("def async_pipe("))
    @async_test
    async def test_async_probe_describes_inputs_and_dependencies(self, name: str):
        """The async interface yields the full description as one item."""
        probe = import_module(name)
        mode = ExecutionMode.DESCRIBE_DEPENDENCIES
        dependencies = [
            item async for item in probe.async_pipe(context=Context(mode=mode))
        ]
        expected = {"inputs": probe.INPUTS, "dependencies": dependencies}
        context = Context(mode=ExecutionMode.DESCRIBE)
        assert [item async for item in probe.async_pipe(context=context)] == [expected]

    @pytest.mark.xfail(
        strict=True,
        reason="a hand-written probe still reports the inputs its input node scans, "
        "not the declared inputs the pipe built from its document reports, until "
        "workflows declare their inputs",
    )
    def test_probe_describes_the_inputs_its_document_declares(self):
        """A probe's describe-inputs output matches the pipe built from its document."""
        name = "pipe_975789b47f17690a21e89b10a702bcbd"
        flow = Workflow.parse((TESTS_DIR / "workflows" / f"{name}.json").read_text())
        generated = _build_resolved_workflow(name, flow, dispatcher)
        probe = import_module(f"tests.pyworkflows.{name}")
        context = Context(mode=ExecutionMode.DESCRIBE_INPUTS)
        assert probe.pipe(context=context) == generated.pipe(context=context)
