# vim: sw=4:ts=4:expandtab
"""Tests ``PipeDag`` expansion into a ``Workflow``."""

from __future__ import annotations

from json import loads
from typing import TYPE_CHECKING

import pytest

from riko.base.exceptions import InvalidPipelineError
from riko.definitions._workflow import ModuleNode
from riko.runtime._migrate import parse_dag
from riko.runtime._pipeline import Pipeline
from riko.types._compiler import Embed
from riko.types._workflow import Endpoint
from riko.types.modules import TruncateRawConf
from tests import TESTS_DIR

if TYPE_CHECKING:
    from collections.abc import Sequence

    from riko.definitions._workflow import Workflow
    from riko.types._compiler import DagModule, PipeDag

DAG_DIR = TESTS_DIR / "dags"

MODULES: list[DagModule] = [
    {"id": "sw-1", "name": "forever"},
    {
        "id": "sw-2",
        "name": "truncate",
        "conf": TruncateRawConf({"count": {"type": "int", "value": "3"}}),
    },
]

FAN_IN_MODULES: list[DagModule] = [
    {"id": "a", "name": "fetch"},
    {"id": "b", "name": "fetch"},
    {"id": "u", "name": "union"},
]

FAN_IN_WIRES: Sequence[Sequence[str]] = [["a", "u"], ["b", "u", "in:1"]]


def _dag(name: str) -> PipeDag:
    """Loads a committed fixture holding a serialized ``PipeDag``."""
    return loads((DAG_DIR / f"{name}.json").read_text())


def _edges(workflow: Workflow) -> list[tuple[str, str]]:
    """Projects a workflow's edges onto their source and target node ids."""
    return [(edge.source.node, edge.target.node) for edge in workflow.edges]


def _module_node(workflow: Workflow, node_id: str) -> ModuleNode:
    """Narrows one of a workflow's nodes to a module node."""
    node = workflow.nodes[node_id]
    assert isinstance(node, ModuleNode)
    return node


def test_omitted_wires_chain_in_listing_order():
    linear = parse_dag({"modules": MODULES})
    wired = parse_dag({"modules": MODULES, "wires": [["sw-1", "sw-2"]]})
    assert linear == wired
    assert _edges(linear) == [("sw-1", "sw-2")]


def test_ids_are_minted_when_omitted():
    modules: list[DagModule] = [{"type": "forever"}, {"type": "truncate"}]
    workflow = parse_dag({"modules": modules})
    assert list(workflow.nodes) == ["sw-1", "sw-2"]


def test_wires_override_listing_order():
    workflow = parse_dag(_dag("pipe_reordered"))
    assert _edges(workflow) == [("gen", "trunc")]
    assert workflow.outputs["default"] == Endpoint("trunc", "out")


def test_third_wire_entry_sets_the_target_port():
    workflow = parse_dag({"modules": FAN_IN_MODULES, "wires": FAN_IN_WIRES})
    ports = [(edge.source.port, edge.target.port) for edge in workflow.edges]
    assert ports == [("out", "in"), ("out", "in:1")]
    assert workflow.outputs["default"] == Endpoint("u", "out")


def test_conf_survives_verbatim():
    workflow = parse_dag({"modules": MODULES})
    assert dict(_module_node(workflow, "sw-2").conf) == {
        "count": {"type": "int", "value": "3"}
    }


def test_options_pass_through():
    modules: list[DagModule] = [
        {"id": "t", "type": "tokenizer", "options": {"emit": True}}
    ]
    workflow = parse_dag({"modules": modules})
    assert dict(_module_node(workflow, "t").options) == {"emit": True}


def test_empty_modules_raise_invalid_pipeline():
    with pytest.raises(InvalidPipelineError, match="no nodes"):
        parse_dag({"modules": []})


@pytest.mark.parametrize("wire", [["a"], ["a", "u", "in:1", "extra"]])
def test_bad_wire_length_raises_invalid_pipeline(wire: list[str]):
    with pytest.raises(InvalidPipelineError, match="wire"):
        parse_dag({"modules": FAN_IN_MODULES, "wires": [wire]})


@pytest.mark.parametrize(
    ("module", "message"),
    [
        pytest.param({"name": "forever", "bogus": 1}, "bogus", id="unknown-key"),
        pytest.param(
            {"type": "forever", "name": "sort"}, "conflicting", id="name-type-conflict"
        ),
        pytest.param({"id": "x"}, "needs a 'name'", id="missing-name"),
        pytest.param(
            {"name": "forever", "family": "module"}, "family", id="node-family-key"
        ),
    ],
)
def test_pipe_dag_reports_unknown_module_keys(module, message):
    with pytest.raises(InvalidPipelineError, match=message):
        parse_dag({"modules": [module]})


def test_pipe_dag_accepts_the_older_type_spelling_of_name():
    named = parse_dag({"modules": [{"name": "forever"}]})
    typed = parse_dag({"modules": [{"type": "forever"}]})
    agreeing = parse_dag({"modules": [{"name": "forever", "type": "forever"}]})
    assert named == typed == agreeing
    assert _module_node(typed, "sw-1").name == "forever"


def test_pipe_dag_offers_known_node_fields_to_the_node():
    embed = Embed({"name": "fetch", "conf": {}})
    workflow = parse_dag({"modules": [{"name": "loop", "embed": embed}]})
    module = _module_node(workflow, "sw-1")
    assert module.embed is not None
    assert module.embed["name"] == "fetch"


def test_expanded_dag_runs():
    workflow = parse_dag(_dag("pipe_forever"))
    assert list(Pipeline(workflow)) == [{"forever": True}] * 3


def test_reordered_dag_runs_in_wired_order():
    workflow = parse_dag(_dag("pipe_reordered"))
    assert list(Pipeline(workflow)) == [{"forever": True}] * 2
