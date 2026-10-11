# vim: sw=4:ts=4:expandtab
"""
Tests the committed workflow fixtures against the workflow runtime.

Every ``pipe_*.json`` under ``tests/workflows`` and ``examples/workflows`` is a
``WorkflowDocument``. One test keeps those documents parseable, valid,
and byte-identical to their serialized form; the other keeps the hand-written
Python probes beside them producing the same items as the documents they mirror.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

import pytest

from riko.definitions._context import Context
from riko.execution._execution import SyncExecution
from riko.runtime._execution_plan import build_execution_plan
from riko.runtime._resolver import dispatcher
from riko.runtime._serialize import parse_document, serialize_workflow
from riko.runtime._workflows import _build_resolved_workflow
from riko.types._enums import ExecutionMode
from tests import TESTS_DIR, async_test

if TYPE_CHECKING:
    from pathlib import Path

    from riko.definitions._workflow import Workflow
    from riko.types._streams import Item

EXAMPLES_DIR = TESTS_DIR.parent / "examples"
FIXTURE_DIRS = (TESTS_DIR / "workflows", EXAMPLES_DIR / "workflows")
PROBE_PACKAGES = {
    TESTS_DIR / "pyworkflows": "tests.pyworkflows",
    EXAMPLES_DIR / "pyworkflows": "examples.pyworkflows",
}

# A stored-workflow fixture: it is only meaningful when another workflow embeds it.
SUBPIPE_ONLY = frozenset({"pipe_bd0834cfe6cdacb0bea5569505d330b8"})

SPLIT_PENDING = pytest.mark.xfail(
    strict=True,
    reason="the execution refuses split nodes until streaming fan-out lands",
)

PROBE_MARKS = {"pipe_zKJifuNS3BGLRQK_GsevXg": (SPLIT_PENDING,)}


def _render(workflow: Workflow) -> str:
    """Renders a workflow as the indented document the fixtures are stored in."""
    return serialize_workflow(workflow).decode("utf-8")


def _fixtures() -> list[Any]:
    return [
        pytest.param(path, id=path.stem)
        for directory in FIXTURE_DIRS
        for path in sorted(directory.glob("pipe_*.json"))
    ]


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


def _run_document(path: Path) -> list[Item]:
    workflow = parse_document(path.read_text())
    items: list[Item] = []

    with SyncExecution(context=Context(test=True)) as execution:
        items = list(execution.run(build_execution_plan(workflow, dispatcher)))

    return items


def _run_probe(package: str, name: str) -> list[object]:
    module = import_module(f"{package}.{name}")

    if package.startswith("examples"):
        stream = module.pipe(test=True)
    else:
        stream = module.pipe(context=Context(test=True))

    return list(stream)


@pytest.mark.parametrize("path", _fixtures())
def test_fixture_round_trips(path: Path):
    """Every committed fixture parses, validates, and is stored in serialized form."""
    workflow = parse_document(path.read_text())
    workflow.validate()
    assert path.read_text() == _render(workflow)


@pytest.mark.parametrize(("package", "path"), _probes())
def test_probe_matches_document(package: str, path: Path):
    """Each Python probe yields the items its workflow document yields."""
    expected = _run_probe(package, path.stem)
    assert _run_document(path) == expected


@pytest.mark.xfail(
    strict=True,
    reason="a hand-written probe still reports the inputs its input node scans, not "
    "the declared inputs the pipe built from its document reports, until workflows "
    "declare their inputs",
)
def test_probe_describes_the_inputs_its_document_declares():
    """A probe's describe-inputs output matches the pipe built from its document."""
    name = "pipe_975789b47f17690a21e89b10a702bcbd"
    workflow = parse_document((TESTS_DIR / "workflows" / f"{name}.json").read_text())
    generated = _build_resolved_workflow(name, workflow, dispatcher)
    probe = import_module(f"tests.pyworkflows.{name}")
    context = Context(mode=ExecutionMode.DESCRIBE_INPUTS)
    assert probe.pipe(context=context) == generated.pipe(context=context)


@pytest.mark.parametrize("name", _describing_probes("def pipe("))
def test_probe_describes_inputs_and_dependencies(name: str):
    """Describing everything reports what each describe mode reports on its own."""
    probe = import_module(name)
    inputs = probe.pipe(context=Context(mode=ExecutionMode.DESCRIBE_INPUTS))
    mode = ExecutionMode.DESCRIBE_DEPENDENCIES
    dependencies = list(probe.pipe(context=Context(mode=mode)))
    expected = {"inputs": inputs, "dependencies": dependencies}
    assert probe.pipe(context=Context(mode=ExecutionMode.DESCRIBE)) == expected


@pytest.mark.parametrize("name", _describing_probes("def async_pipe("))
@async_test
async def test_async_probe_describes_inputs_and_dependencies(name: str):
    """The async interface yields the full description as one item."""
    probe = import_module(name)
    mode = ExecutionMode.DESCRIBE_DEPENDENCIES
    dependencies = [item async for item in probe.async_pipe(context=Context(mode=mode))]
    expected = {"inputs": probe.INPUTS, "dependencies": dependencies}
    context = Context(mode=ExecutionMode.DESCRIBE)
    assert [item async for item in probe.async_pipe(context=context)] == [expected]
