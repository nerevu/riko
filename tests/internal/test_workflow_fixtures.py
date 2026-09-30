# vim: sw=4:ts=4:expandtab
"""
Tests the committed pipeline fixtures against the canonical workflow runtime.

Every ``pipe_*.json`` under ``tests/pipelines`` and ``examples/pipelines`` is a
canonical Workflow v2 document. One test keeps those documents parseable, valid,
and byte-identical to their canonical rendering; the other keeps the hand-written
Python probes beside them producing the same items as the documents they mirror.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

import pytest

from riko.execution._execution import SyncExecution
from riko.execution.context import Context
from riko.runtime._execution_plan import build_execution_plan
from riko.runtime._serialize import parse_workflow, serialize_workflow
from tests import TESTS_DIR

if TYPE_CHECKING:
    from pathlib import Path

    from riko.definitions._workflow import WorkflowSpec
    from riko.types._streams import Item

EXAMPLES_DIR = TESTS_DIR.parent / "examples"
FIXTURE_DIRS = (TESTS_DIR / "pipelines", EXAMPLES_DIR / "pipelines")
PROBE_PACKAGES = {
    TESTS_DIR / "pypipelines": "tests.pypipelines",
    EXAMPLES_DIR / "pypipelines": "examples.pypipelines",
}

# A sub-pipeline fixture: it is only meaningful when another pipeline embeds it.
SUBPIPE_ONLY = frozenset({"pipe_bd0834cfe6cdacb0bea5569505d330b8"})

SPLIT_PENDING = pytest.mark.xfail(
    strict=True,
    reason="the execution refuses split nodes until streaming fan-out lands",
)

PROBE_MARKS = {"pipe_zKJifuNS3BGLRQK_GsevXg": (SPLIT_PENDING,)}


def _render(spec: WorkflowSpec) -> str:
    """Renders a spec as the indented canonical JSON the fixtures are stored in."""
    return serialize_workflow(spec).decode("utf-8")


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
            document = directory.parent / "pipelines" / f"{path.stem}.json"

            if not document.exists() or path.stem in SUBPIPE_ONLY:
                continue

            marks = PROBE_MARKS.get(path.stem, ())
            param = pytest.param(package, document, id=path.stem, marks=marks)
            params.append(param)

    return params


def _run_document(path: Path) -> list[Item]:
    spec = parse_workflow(path.read_text())
    items: list[Item] = []

    with SyncExecution(context=Context(test=True)) as execution:
        items = list(execution.run(build_execution_plan(spec)))

    return items


def _run_probe(package: str, name: str) -> list[object]:
    module = import_module(f"{package}.{name}")

    if package.startswith("examples"):
        stream = module.pipe(test=True)
    else:
        stream = module.pipe(context=Context(test=True))

    return list(stream)


@pytest.mark.parametrize("path", _fixtures())
def test_fixture_is_canonical(path: Path):
    """Every committed fixture parses, validates, and is stored canonically."""
    spec = parse_workflow(path.read_text())
    spec.validate()
    assert path.read_text() == _render(spec)


@pytest.mark.parametrize(("package", "path"), _probes())
def test_probe_matches_document(package: str, path: Path):
    """Each Python probe yields the items its canonical document yields."""
    expected = _run_probe(package, path.stem)
    assert _run_document(path) == expected
