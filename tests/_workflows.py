# vim: sw=4:ts=4:expandtab
"""Provides shared workflow fixture paths, documents, and runners for tests."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from riko.base._config import INPUT_PORT, OUTPUT_PORT
from riko.base._paths import ROOT_DIR
from riko.definitions._context import Context
from riko.definitions._nodes import (
    CallableNode,
    ModuleNode,
    PublishEdge,
    StreamEdge,
    SubscribeNode,
)
from riko.definitions._workflow_definition import Workflow
from riko.execution._prepared import ExecutionPlan
from riko.execution._sync_execution import SyncExecution
from riko.runtime._pipeline import Pipeline
from riko.runtime._resolver import dispatcher
from riko.runtime._workflow_resolver import register_workflow_store
from riko.types.modules import StrconcatRawConf
from tests import OUT_MODULE, TESTS_DIR
from tests._execution import SORT_NODE

if TYPE_CHECKING:
    from pathlib import Path

    from riko.types._streams import Item
    from riko.types._workflow import NodeId


EXAMPLES_DIR = ROOT_DIR / "examples"

DAG_DIR = TESTS_DIR / "dags"
DAG_PATH = DAG_DIR / "pipe_forever.json"
DAG = json.loads(DAG_PATH.read_text(encoding="utf-8"))
DOCUMENT = json.loads(Workflow.parse(DAG).serialize())


def build_wire(
    wid: str,
    src_mod: str,
    tgt_mod: str,
    src_port: str | None = OUTPUT_PORT,
    tgt_port: str | None = INPUT_PORT,
) -> dict[str, object]:
    """Builds a serialized ``PipeDef`` wire from ``src_mod``'s port to ``tgt_mod``'s."""
    return {
        "id": wid,
        "src": {"id": src_port, "moduleid": src_mod},
        "tgt": {"id": tgt_port, "moduleid": tgt_mod},
    }


PIPE_DEF = {
    "modules": [{"id": "sw-1", "type": "forever", "conf": {}}, OUT_MODULE],
    "wires": [build_wire("_w1", "sw-1", "_OUTPUT")],
}

RAW_WORKFLOW = {"nodes": [{"name": "forever"}]}
CALLABLE_MATCH = r"callable node\(s\) \['len-1'\]"
CALLABLE_FLOW = Workflow().with_nodes(CallableNode(id="len-1", name="len", fn=len))
TEST_CONTEXT = Context(test=True)


def build_edge(source: str, target: str, **extra: object) -> dict[str, object]:
    """Builds a raw edge from node ``source`` to node ``target`` with ``extra`` keys."""
    return {"source": {"node": source}, "target": {"node": target}, **extra}


def require_module_node(flow: Workflow, node_id: NodeId) -> ModuleNode:
    """Requires the workflow's node ``node_id`` to be a module node."""
    node = flow.nodes[node_id]
    assert isinstance(node, ModuleNode)
    return node


def run_workflow(flow: Workflow, *, context: Context | None = None) -> list[Item]:
    """Runs ``flow`` through a synchronous execution (default: a test ``Context``)."""
    items: list[Item] = []
    _context = TEST_CONTEXT if context is None else context

    with SyncExecution(context=_context) as execution:
        items = list(execution.run(ExecutionPlan.from_workflow(flow, dispatcher)))

    return items


def run_document(path: Path) -> list[Item]:
    """Parses the workflow document at ``path`` and runs it."""
    return run_workflow(Workflow.parse(path.read_text()))


EDGE_FAMILY_MISMATCHES = [
    pytest.param(PublishEdge, SORT_NODE, id="publish-to-module"),
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
