# vim: sw=4:ts=4:expandtab
"""Provides shared workflow fixture paths, documents, and runners for tests."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from riko.definitions._context import Context
from riko.definitions._workflow import Workflow
from riko.execution._prepared import ExecutionPlan
from riko.execution._sync_execution import SyncExecution
from riko.runtime._resolver import dispatcher
from tests import TESTS_DIR

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from riko.types._streams import Item

EXAMPLES_DIR = TESTS_DIR.parent / "examples"
FIXTURE_DIRS = (TESTS_DIR / "workflows", EXAMPLES_DIR / "workflows")

SPLIT_PENDING = pytest.mark.xfail(
    strict=True,
    reason="the execution refuses split nodes until streaming fan-out lands",
)

DAG_PATH = TESTS_DIR / "dags" / "pipe_forever.json"
DAG = json.loads(DAG_PATH.read_text(encoding="utf-8"))
PIPE_DEF = {
    "modules": [
        {"id": "sw-1", "type": "forever", "conf": {}},
        {"id": "_OUTPUT", "type": "output", "conf": {}},
    ],
    "wires": [
        {
            "id": "_w1",
            "src": {"id": "_OUTPUT", "moduleid": "sw-1"},
            "tgt": {"id": "_INPUT", "moduleid": "_OUTPUT"},
        }
    ],
}


def gen_fixture_paths() -> Iterator[Path]:
    """Finds every committed ``pipe_*.json`` workflow document, sorted per directory."""
    for directory in FIXTURE_DIRS:
        yield from sorted(directory.glob("pipe_*.json"))


def run_workflow(flow: Workflow) -> list[Item]:
    """Runs ``flow`` through a synchronous test execution."""
    items: list[Item] = []

    with SyncExecution(context=Context(test=True)) as execution:
        items = list(execution.run(ExecutionPlan.from_workflow(flow, dispatcher)))

    return items


def run_document(path: Path) -> list[Item]:
    """Parses the workflow document at ``path`` and runs it."""
    return run_workflow(Workflow.parse(path.read_text()))
