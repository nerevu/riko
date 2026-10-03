# vim: sw=4:ts=4:expandtab
"""
Tests the Python modules generated from canonical workflow documents.

A generated module rebuilds its workflow from typed configuration classes and runs
it through the canonical execution, so it has to produce exactly what running the
document produces. These tests hold that equivalence over every committed fixture,
in both the synchronous and asynchronous interface, and keep the generated source
importable. Type coverage of generated modules is held by the committed typed
probes under the ``pypipelines`` trees, which the standard type check includes.
"""

from __future__ import annotations

import ast
import importlib.util
from keyword import iskeyword
from typing import TYPE_CHECKING, Any

import pytest

from riko.base._strutils import pythonise
from riko.base.exceptions import InvalidPipelineError
from riko.definitions._workflow import ModuleNode, Pipeline, Workflow, WriteNode
from riko.execution._execution import AsyncExecution, SyncExecution
from riko.execution.context import Context
from riko.runtime._codegen import compile_pipe, compile_workflow
from riko.runtime._execution_plan import build_execution_plan
from riko.runtime._normalize import normalize_workflow
from riko.runtime._serialize import parse_document
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

if TYPE_CHECKING:
    from pathlib import Path
    from types import ModuleType

    from riko.types._streams import Item

EXAMPLES_DIR = TESTS_DIR.parent / "examples"
FIXTURE_DIRS = (TESTS_DIR / "pipelines", EXAMPLES_DIR / "pipelines")

# These documents cannot run on their own: two name modules riko does not
# implement, and the third is a sub-pipeline that is only meaningful when another
# pipeline embeds it. Their generated modules are held to the same failure.
UNRUNNABLE = frozenset(
    {
        "pipe_93abb8500bd41d56a37e8885094c8d10",
        "pipe_b3d43c00f9e1145ff522fb71ea743e99",
        "pipe_bd0834cfe6cdacb0bea5569505d330b8",
    }
)

SPLIT_PENDING = pytest.mark.xfail(
    strict=True,
    reason="the execution refuses split nodes until streaming fan-out lands",
)

FIXTURE_MARKS = {
    "pipe_QMrlL_FS3BGlpwryODY80A": (SPLIT_PENDING,),
    "pipe_zKJifuNS3BGLRQK_GsevXg": (SPLIT_PENDING,),
}

ASYNC_FIXTURES = ("pipe_gigs", "pipe_loop_assign", "pipe_loop_subpipe")

RENAME_CONF = RenameRawConf(
    {
        "rule": RenameRawRule(
            field=ConfArg(type="text", value="content"),
            newval=ConfArg(type="text", value="greeting"),
        )
    }
)

SORT_CONF = SortRawConf(
    {"rule": SortRawRule(field=ConfArg(type="text", value="title"))}
)


def _fixtures(unrunnable: bool = False) -> list[Any]:
    params = []

    for directory in FIXTURE_DIRS:
        for path in sorted(directory.glob("pipe_*.json")):
            if (path.stem in UNRUNNABLE) != unrunnable:
                continue

            marks = FIXTURE_MARKS.get(path.stem, ())
            params.append(pytest.param(path, id=path.stem, marks=marks))

    return params


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


def _build(workflow: Workflow, name: str, directory: Path, **kwargs) -> ModuleType:
    """Generates and imports the module for ``workflow``."""
    return _load(compile_workflow(workflow, name, **kwargs), name, directory)


def _run_workflow(workflow: Workflow) -> list[Item]:
    items: list[Item] = []

    with SyncExecution(context=Context(test=True)) as execution:
        items = list(execution.run(build_execution_plan(workflow)))

    return items


async def _arun_document(workflow: Workflow) -> list[Item]:
    items: list[Item] = []

    async with AsyncExecution(context=Context(test=True)) as execution:
        stream = await execution.run(build_execution_plan(workflow))
        items = [item async for item in stream]

    return items


def _failure(call) -> tuple[str, str]:
    """Reports the type and message of the error ``call`` raises."""
    with pytest.raises(Exception) as info:  # noqa: PT011, B017
        call()

    return type(info.value).__name__, str(info.value)


@pytest.mark.parametrize("path", _fixtures())
def test_generated_matches_document(path: Path, tmp_path: Path):
    """Each generated module yields the items its canonical document yields."""
    workflow = parse_document(path.read_text())
    module = _build(workflow, path.stem, tmp_path)
    assert list(module.pipe(context=Context(test=True))) == _run_workflow(workflow)


@pytest.mark.parametrize("path", _fixtures(unrunnable=True))
def test_generated_matches_document_failure(path: Path, tmp_path: Path):
    """A document that cannot run standalone fails the same way once generated."""
    workflow = parse_document(path.read_text())
    module = _build(workflow, path.stem, tmp_path)
    generated = _failure(lambda: list(module.pipe(context=Context(test=True))))
    assert generated == _failure(lambda: _run_workflow(workflow))


@pytest.mark.parametrize("stem", ASYNC_FIXTURES)
@async_test
async def test_async_generated_matches_document(stem: str, tmp_path: Path):
    """Each generated async module yields the items its document yields."""
    path = TESTS_DIR / "pipelines" / f"{stem}.json"
    workflow = parse_document(path.read_text())
    module = _build(workflow, stem, tmp_path, is_async=True)
    stream = module.async_pipe(context=Context(test=True))
    assert [item async for item in stream] == await _arun_document(workflow)


def test_generated_pipe_accepts_one_item(tmp_path: Path):
    """A generated transformer maps a single item handed to it directly."""
    workflow = Pipeline.from_module("rename", conf=RENAME_CONF).workflow
    module = _build(workflow, "pipe_rename", tmp_path)
    assert list(module.pipe({"content": "hello"})) == [{"greeting": "hello"}]


def test_generated_pipe_accepts_a_stream(tmp_path: Path):
    """A generated transformer maps every item of a stream handed to it."""
    workflow = Pipeline.from_module("rename", conf=RENAME_CONF).workflow
    module = _build(workflow, "pipe_rename", tmp_path)
    items = [{"content": "hello"}, {"content": "bye"}]
    expected = [{"greeting": "hello"}, {"greeting": "bye"}]
    assert list(module.pipe(items)) == expected


@async_test
async def test_generated_async_pipe_accepts_an_async_stream(tmp_path: Path):
    """A generated async transformer maps every item of an async stream."""
    workflow = Pipeline.from_module("rename", conf=RENAME_CONF).workflow
    module = _build(workflow, "pipe_arename", tmp_path, is_async=True)

    async def source():
        yield {"content": "hello"}
        yield {"content": "bye"}

    expected = [{"greeting": "hello"}, {"greeting": "bye"}]
    assert [item async for item in module.async_pipe(source())] == expected


def test_generated_pipe_describes_dependencies(tmp_path: Path):
    """Describing dependencies reports the workflow's module names, sorted."""
    pipeline = Pipeline.from_module("itembuilder").pipe("rename", conf=RENAME_CONF)
    module = _build(pipeline.workflow, "pipe_described", tmp_path)
    context = Context(mode=ExecutionMode.DESCRIBE_DEPENDENCIES)
    assert list(module.pipe(context=context)) == ["itembuilder", "rename"]


def test_generated_pipe_describes_inputs(tmp_path: Path):
    """Describing inputs reports the workflow's declared input schemas."""
    node = ModuleNode(id="rename-1", name="rename", conf=RENAME_CONF)
    inputs = {"limit": {"type": "integer"}}
    workflow = Workflow(
        nodes={node.id: node},
        outputs={"default": Endpoint(node.id, "out")},
        inputs=inputs,
    )
    module = _build(workflow, "pipe_inputs", tmp_path)
    context = Context(mode=ExecutionMode.DESCRIBE_INPUTS)
    assert module.pipe(context=context) == inputs


def test_write_node_is_refused():
    """A workflow with a node family that has no generated form is refused."""
    node = WriteNode(id="write-1", name="write", backend="file", dest="out.csv")
    workflow = Workflow(
        nodes={node.id: node}, outputs={"default": Endpoint(node.id, "out")}
    )

    with pytest.raises(InvalidPipelineError, match="only registered module nodes"):
        compile_workflow(workflow, "pipe_written")


def test_conf_is_typed_by_its_module():
    """A configured node is rendered through its module's raw config class."""
    workflow = Pipeline.from_module("sort", conf=SORT_CONF).workflow
    assert "SortRawConf(" in compile_workflow(workflow, "pipe_sorted")


def test_generated_conf_keeps_its_keys_verbatim(tmp_path: Path):
    """A generated module spells a configuration key exactly as the document does."""
    attrs = {
        "key": ConfArg(type="text", value="title"),
        "value": ConfArg(type="text", value="riko"),
    }
    conf = {"attrs": [attrs], "EXTRA": ConfArg(type="text", value="x")}
    workflow = normalize_workflow({"nodes": [{"name": "itembuilder", "conf": conf}]})
    module = _build(workflow, "pipe_verbatim", tmp_path)
    assert module.workflow == workflow
    assert list(module.pipe(context=Context(test=True))) == _run_workflow(workflow)


def test_generation_is_deterministic():
    """Generating the same workflow twice produces identical source."""
    workflow = (
        Pipeline.from_module("itembuilder").pipe("rename", conf=RENAME_CONF).workflow
    )
    assert compile_workflow(workflow, "pipe_twice") == compile_workflow(
        workflow, "pipe_twice"
    )


def test_compile_pipe_accepts_an_authoring_mapping():
    """An RawWorkflow is normalized before it is generated."""
    authoring = {
        "nodes": [{"name": "itembuilder"}, {"name": "sort"}],
        "edges": [{"source": {"node": "itembuilder-1"}, "target": {"node": "sort-1"}}],
    }
    source = compile_pipe(authoring, "pipe_authored")
    assert 'DEPENDENCIES: list[str] = ["itembuilder", "sort"]' in source


def test_generated_source_parses(tmp_path: Path):
    """The generated source is valid Python and imports without running."""
    workflow = (
        Pipeline.from_module("itembuilder").pipe("rename", conf=RENAME_CONF).workflow
    )
    source = compile_workflow(workflow, "pipe_parsed")
    ast.parse(source)
    module = _load(source, "pipe_parsed", tmp_path)
    assert module.workflow.outputs["default"] == Endpoint("rename-1", "out")


def _loop_spec() -> Workflow:
    """Parses the committed loop fixture whose embed carries a typed config."""
    data = (TESTS_DIR / "pipelines" / "pipe_loop_assign.json").read_text()
    return parse_document(data)


def test_loop_embed_is_rendered_as_a_node_field():
    """A loop node's embedded module is rebuilt from the typed ``Embed``."""
    source = compile_workflow(_loop_spec(), "pipe_x")
    assert "embed=Embed(" in source
    assert "LoopConf" not in source


@pytest.mark.xfail(
    reason="pythonise does not sanitize ids into valid identifiers yet", strict=True
)
def test_pythonise_yields_valid_identifiers():
    """
    Every generated id must be a legal, non-keyword Python identifier.

    ``pythonise`` only replaces four characters and ASCII-``replace``-encodes, so
    ``"class"``/``"foo bar"``/``"foo.bar"``/``"café"`` survive into generated source
    as invalid identifiers (``"1st"`` already becomes ``"_1st"``).
    ``ext/codegen.py::enum_member_name`` already sanitizes properly.
    """
    results = [pythonise(raw) for raw in ("class", "foo bar", "foo.bar", "1st", "café")]
    assert all(r.isidentifier() and not iskeyword(r) for r in results)
