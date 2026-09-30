# vim: sw=4:ts=4:expandtab
"""Tests bare-bones DAG expansion into canonical Workflow v2 specs."""

from __future__ import annotations

from json import loads
from typing import TYPE_CHECKING

import pytest

from riko.base.exceptions import InvalidPipelineError
from riko.definitions._workflow import ModuleNode, Pipeline
from riko.runtime._migrate import build_workflow
from riko.types._workflow import Endpoint
from tests import TESTS_DIR

if TYPE_CHECKING:
    from collections.abc import Sequence

    from riko.definitions._workflow import WorkflowSpec
    from riko.types._compiler import DagModule, PipeDag

DAG_DIR = TESTS_DIR / "dags"

MODULES: list[DagModule] = [
    {"id": "sw-1", "type": "forever"},
    {
        "id": "sw-2",
        "type": "truncate",
        "conf": {"count": {"type": "int", "value": "3"}},
    },
]

FAN_IN_MODULES: list[DagModule] = [
    {"id": "a", "type": "fetch"},
    {"id": "b", "type": "fetch"},
    {"id": "u", "type": "union"},
]

FAN_IN_WIRES: Sequence[Sequence[str]] = [["a", "u"], ["b", "u", "in:1"]]


def _dag(name: str) -> PipeDag:
    """Loads a committed bare-bones DAG fixture."""
    return loads((DAG_DIR / f"{name}.json").read_text())


def _edges(spec: WorkflowSpec) -> list[tuple[str, str]]:
    """Projects a spec's edges onto their source and target node ids."""
    return [(edge.source.node, edge.target.node) for edge in spec.edges]


def _module_node(spec: WorkflowSpec, node_id: str) -> ModuleNode:
    """Narrows one of a spec's nodes to a module node."""
    node = spec.nodes[node_id]
    assert isinstance(node, ModuleNode)
    return node


def test_omitted_wires_chain_in_listing_order():
    linear = build_workflow({"modules": MODULES})
    wired = build_workflow({"modules": MODULES, "wires": [["sw-1", "sw-2"]]})
    assert linear == wired
    assert _edges(linear) == [("sw-1", "sw-2")]


def test_ids_are_minted_when_omitted():
    modules: list[DagModule] = [{"type": "forever"}, {"type": "truncate"}]
    spec = build_workflow({"modules": modules})
    assert list(spec.nodes) == ["sw-1", "sw-2"]


def test_wires_override_listing_order():
    spec = build_workflow(_dag("pipe_reordered"))
    assert _edges(spec) == [("gen", "trunc")]
    assert spec.outputs["default"] == Endpoint("trunc", "out")


def test_third_wire_entry_sets_the_target_port():
    spec = build_workflow({"modules": FAN_IN_MODULES, "wires": FAN_IN_WIRES})
    ports = [(edge.source.port, edge.target.port) for edge in spec.edges]
    assert ports == [("out", "in"), ("out", "in:1")]
    assert spec.outputs["default"] == Endpoint("u", "out")


def test_conf_survives_verbatim():
    spec = build_workflow({"modules": MODULES})
    assert dict(_module_node(spec, "sw-2").conf) == {
        "count": {"type": "int", "value": "3"}
    }


def test_options_pass_through():
    modules: list[DagModule] = [
        {"id": "t", "type": "tokenizer", "options": {"emit": True}}
    ]
    spec = build_workflow({"modules": modules})
    assert dict(_module_node(spec, "t").options) == {"emit": True}


def test_empty_modules_raise_invalid_pipeline():
    with pytest.raises(InvalidPipelineError, match="no nodes"):
        build_workflow({"modules": []})


@pytest.mark.parametrize("wire", [["a"], ["a", "u", "in:1", "extra"]])
def test_bad_wire_length_raises_invalid_pipeline(wire: list[str]):
    with pytest.raises(InvalidPipelineError, match="wire"):
        build_workflow({"modules": FAN_IN_MODULES, "wires": [wire]})


def test_expanded_dag_runs_like_its_document():
    spec = build_workflow(_dag("pipe_forever"))
    assert list(Pipeline(spec)) == [{"forever": True}] * 3


def test_reordered_dag_runs_in_wired_order():
    spec = build_workflow(_dag("pipe_reordered"))
    assert list(Pipeline(spec)) == [{"forever": True}] * 2
