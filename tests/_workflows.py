# vim: sw=4:ts=4:expandtab
"""Provides shared workflow fixture paths, documents, and runners for tests."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from riko.base._paths import ROOT_DIR
from riko.definitions._context import Context
from riko.definitions._nodes import ModuleNode, PublishEdge, StreamEdge, SubscribeNode
from riko.definitions._workflow_definition import Workflow
from riko.execution._prepared import ExecutionPlan
from riko.execution._sync_execution import SyncExecution
from riko.runtime._pipeline import Pipeline
from riko.runtime._resolver import dispatcher
from riko.runtime._workflow_resolver import register_workflow_store
from riko.types.modules import StrconcatRawConf
from tests import TESTS_DIR

if TYPE_CHECKING:
    from pathlib import Path

    from riko.types._streams import Item


EXAMPLES_DIR = ROOT_DIR / "examples"

SPLIT_PENDING = pytest.mark.xfail(
    strict=True,
    reason="the execution refuses split nodes until streaming fan-out lands",
)

SPLIT_METHOD_PENDING = pytest.mark.xfail(
    strict=True, reason="Pipeline.split() is not available yet"
)

DAG_DIR = TESTS_DIR / "dags"
DAG_PATH = DAG_DIR / "pipe_forever.json"
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

RAW_WORKFLOW = {"nodes": [{"name": "forever"}]}
PARENT = [{"title": "hi"}]
EXCLAIMED = [{"title": "hi", "strconcat": "hi!"}]


def run_workflow(flow: Workflow, *, context: Context | None = None) -> list[Item]:
    """Runs ``flow`` through a synchronous execution (default: a test ``Context``)."""
    items: list[Item] = []
    resolved = Context(test=True) if context is None else context

    with SyncExecution(context=resolved) as execution:
        items = list(execution.run(ExecutionPlan.from_workflow(flow, dispatcher)))

    return items


def run_document(path: Path) -> list[Item]:
    """Parses the workflow document at ``path`` and runs it."""
    return run_workflow(Workflow.parse(path.read_text()))


EDGE_FAMILY_MISMATCHES = [
    pytest.param(PublishEdge, ModuleNode(id="b", name="sort"), id="publish-to-module"),
    pytest.param(
        StreamEdge, SubscribeNode(id="b", name="sub"), id="stream-to-subscribe"
    ),
]


def _write_document(directory: Path, name: str, suffix: str) -> None:
    """Write a strconcat workflow document that appends *suffix* to each title."""
    conf = StrconcatRawConf(
        {
            "part": [
                {"subkey": "title", "type": "text"},
                {"type": "text", "value": suffix},
            ]
        }
    )
    pipeline = Pipeline.from_module("strconcat", conf=conf)
    path = directory / f"{name}.json"
    path.write_bytes(pipeline.workflow.serialize())


def register_documents(directory: Path) -> None:
    """Write the ``pipe_exclaim``/``pipe_shout`` documents and register their store."""
    _write_document(directory, "pipe_exclaim", "!")
    _write_document(directory, "pipe_shout", "?")
    register_workflow_store(directory=directory, replace=True)
