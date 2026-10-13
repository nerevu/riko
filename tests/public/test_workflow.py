# vim: sw=4:ts=4:expandtab
"""
Structural tests for the ``Workflow`` graph.

These exercise the closed node/edge families, the immutable ``Workflow`` envelope,
the ``Pipeline`` wrapper, and the port grammar. They cover structure only; running
the graph is tested elsewhere.
"""

import json
from functools import partial

import pytest

from riko import Pipeline
from riko.base.exceptions import InvalidPipelineError
from riko.definitions._context import Context
from riko.definitions._workflow import Workflow, migrate_v1_to_v2, normalize_workflow
from riko.definitions._write import WriteMode
from riko.ext import (
    ActionNode,
    CacheNode,
    ModuleNode,
    PublishEdge,
    ReadNode,
    StreamEdge,
    SubscribeNode,
    WriteNode,
)
from riko.types._collections import FrozenDict
from riko.types._enums import Backends, DocumentShape
from riko.types._workflow import Endpoint, ParsedPort, parse_port
from tests import TESTS_DIR

NODE_FAMILIES = (
    (ModuleNode(id="fetch-1", name="fetch"), "module"),
    (ReadNode(id="read-1", name="read", backend=Backends.FILE), "read"),
    (WriteNode(id="write-1", name="write", backend=Backends.FILE), "write"),
    (CacheNode(id="cache-1", name="cache"), "cache"),
    (ActionNode(id="act-1", name="act", backend=Backends.HTTP), "action"),
    (SubscribeNode(id="sub-1", name="sub"), "subscribe"),
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
RAW_WORKFLOW = {"nodes": [{"name": "forever"}]}
DOCUMENT = json.loads(Workflow.parse(DAG).serialize())
DOCUMENTS = [
    pytest.param(
        DAG, DocumentShape.DAG, partial(Workflow.parse, shape="dag"), id="dag"
    ),
    pytest.param(PIPE_DEF, DocumentShape.V1, migrate_v1_to_v2, id="v1"),
    pytest.param(RAW_WORKFLOW, DocumentShape.V2, normalize_workflow, id="v2"),
    pytest.param(DOCUMENT, DocumentShape.V2, normalize_workflow, id="workflow"),
]


def _workflow():
    node = ModuleNode(id="fetch-1", name="fetch")
    return Workflow(
        nodes=[node], edges=(), outputs={"default": Endpoint(node.id, "out")}, inputs={}
    )


@pytest.mark.parametrize(("node", "family"), NODE_FAMILIES, ids=str)
def test_node_family_discriminant(node, family):
    assert node.family == family


def test_edge_family_discriminants():
    endpoint = Endpoint("fetch-1", "out")
    assert StreamEdge(endpoint, endpoint).family == "stream"
    assert PublishEdge(endpoint, endpoint).family == "publish"


def test_write_node_defaults():
    node = WriteNode(id="write-1", name="write", backend=Backends.FILE)
    assert node.fmt is None
    assert node.mode is WriteMode.REPLACE
    assert node.keys == ()


def test_node_is_frozen():
    node = ModuleNode(id="fetch-1", name="fetch")
    with pytest.raises(AttributeError):
        node.name = "other"  # type: ignore[misc]


def test_workflow_mappings_are_read_only():
    workflow = _workflow()
    assert isinstance(workflow.nodes, FrozenDict)
    with pytest.raises(TypeError):
        workflow.outputs["extra"] = Endpoint("fetch-1", "out")  # type: ignore[index]


def test_workflow_version_defaults_to_2():
    assert _workflow().version == "2"


def test_pipeline_wraps_workflow():
    workflow = _workflow()
    pipeline = Pipeline(workflow)
    assert pipeline.workflow is workflow
    assert pipeline.workflow.outputs["default"] == Endpoint("fetch-1", "out")


@pytest.mark.parametrize(
    ("port", "expected"),
    [
        ("in", ParsedPort("in", None, None)),
        ("out", ParsedPort("out", None, None)),
        ("in:1", ParsedPort("in", 1, None)),
        ("out:2", ParsedPort("out", 2, None)),
        ("out:matched", ParsedPort("out", None, "matched")),
        ("in:count", ParsedPort("in", None, "count")),
    ],
)
def test_parse_port_grammar(port, expected):
    assert parse_port(port) == expected


@pytest.mark.parametrize("port", ["sideways", "up:1", ""])
def test_parse_port_rejects_bad_direction(port):
    with pytest.raises(ValueError, match="invalid port direction"):
        parse_port(port)


@pytest.mark.parametrize(
    "port", ["out:-1", "out:", "out:a b", "in:", "in:-1", "in:a b"]
)
def test_parse_port_rejects_bad_qualifier(port):
    with pytest.raises(ValueError, match="invalid port"):
        parse_port(port)


@pytest.mark.parametrize("port", ["in:0", "out:0"])
def test_parse_port_rejects_zero_position(port):
    with pytest.raises(ValueError, match="invalid port"):
        parse_port(port)


@pytest.mark.parametrize(("document", "shape", "loader"), DOCUMENTS)
def test_parse_detects_each_document_shape(document, shape, loader):
    """Each readable document shape is recognized and read as its loader reads it."""
    assert Workflow.parse(document) == loader(document)


@pytest.mark.parametrize(("document", "shape", "loader"), DOCUMENTS)
def test_parse_honors_a_declared_shape(document, shape, loader):
    expected = loader(document)
    assert Workflow.parse(document, shape=shape) == expected
    assert Workflow.parse(document, shape=shape.value) == expected


def test_parse_rejects_an_unknown_shape():
    with pytest.raises(InvalidPipelineError, match="'nodes' or 'modules'"):
        Workflow.parse({"pipeline": []})


def test_parse_rejects_an_unknown_declared_shape():
    with pytest.raises(InvalidPipelineError, match="Invalid shape"):
        Workflow.parse(RAW_WORKFLOW, shape="v3")


@pytest.mark.parametrize(
    ("document", "shape"),
    [
        pytest.param(DAG, DocumentShape.V2, id="dag-as-v2"),
        pytest.param(DAG, DocumentShape.V1, id="dag-as-v1"),
        pytest.param(PIPE_DEF, DocumentShape.DAG, id="v1-as-dag"),
        pytest.param(PIPE_DEF, DocumentShape.V2, id="v1-as-v2"),
        pytest.param(RAW_WORKFLOW, DocumentShape.DAG, id="v2-as-dag"),
        pytest.param(RAW_WORKFLOW, DocumentShape.V1, id="v2-as-v1"),
    ],
)
def test_parse_rejects_a_document_read_as_another_shape(document, shape):
    """A document read as a shape it is not written in is rejected, not guessed."""
    with pytest.raises(InvalidPipelineError):
        Workflow.parse(document, shape=shape)


@pytest.mark.parametrize(
    ("document", "message"),
    [
        pytest.param({"modules": []}, "no nodes", id="empty-dag"),
        pytest.param({"modules": None}, "must be a list", id="null-modules"),
        pytest.param(
            {"modules": [{"type": "forever"}], "wires": 5},
            "must be a list",
            id="scalar-wires",
        ),
    ],
)
def test_parse_rejects_invalid_pipe_dags(document, message):
    with pytest.raises(InvalidPipelineError, match=message):
        Workflow.parse(document)


def test_parse_reads_a_workflow_only_as_v2():
    flow = Workflow.parse(DAG)
    assert Workflow.parse(flow, shape=DocumentShape.V2) == flow

    with pytest.raises(InvalidPipelineError, match="only be read as shape 'v2'"):
        Workflow.parse(flow, shape=DocumentShape.DAG)

    with pytest.raises(InvalidPipelineError, match="Invalid shape"):
        Workflow.parse(flow, shape="v3")


@pytest.mark.parametrize(
    ("edge", "target"),
    [
        pytest.param(
            PublishEdge, ModuleNode(id="b", name="sort"), id="publish-to-module"
        ),
        pytest.param(
            StreamEdge, SubscribeNode(id="b", name="sub"), id="stream-to-subscribe"
        ),
    ],
)
def test_renormalizing_keeps_an_edge_family(edge, target):
    """A mismatched edge family is kept and rejected, not inferred from its target."""
    flow = Workflow(
        nodes=[ModuleNode(id="a", name="fetch"), target],
        edges=[edge(Endpoint("a", "out"), Endpoint("b", "in"))],
        outputs={"default": Endpoint("a", "out")},
    )
    assert normalize_workflow(flow) == flow

    with pytest.raises(InvalidPipelineError, match="edge family disagrees"):
        Workflow.parse(flow)


def test_parse_chains_null_wires_in_listing_order():
    document = {"modules": DAG["modules"], "wires": None}
    assert Workflow.parse(document) == Workflow.parse(DAG)


@pytest.mark.parametrize(("document", "shape", "loader"), DOCUMENTS)
def test_parse_is_idempotent(document, shape, loader):
    flow = Workflow.parse(document)
    assert Workflow.parse(flow) == flow


def test_parse_reads_pipe_dag_text():
    assert Workflow.parse(json.dumps(DAG)) == Workflow.parse(DAG)


@pytest.mark.parametrize("document", ["{bad json", "[]"])
def test_parse_rejects_malformed_text(document):
    with pytest.raises(InvalidPipelineError):
        Workflow.parse(document)


def test_parse_validates():
    with pytest.raises(InvalidPipelineError, match="no nodes"):
        Workflow.parse({"nodes": []})


def test_repr_shows_a_chain():
    assert repr(_workflow()) == "Workflow(fetch-1; outputs: default)"
    chained = Workflow.parse({"modules": [{"name": "fetch"}, {"name": "sort"}]})
    assert repr(chained) == "Workflow(sw-1 -> sw-2; outputs: default)"


def test_repr_counts_a_branching_graph():
    dag = {
        "modules": [
            {"id": "a", "name": "fetch"},
            {"id": "b", "name": "fetch"},
            {"id": "u", "name": "union"},
        ],
        "wires": [["a", "u"], ["b", "u", "in:1"]],
    }
    expected = "Workflow(nodes: 3, edges: 2; outputs: default)"
    assert repr(Workflow.parse(dag)) == expected


def test_repr_shows_an_empty_workflow():
    assert repr(Workflow()) == "Workflow(empty)"


def test_repr_counts_disconnected_nodes():
    flow = normalize_workflow({"nodes": [{"name": "fetch"}, {"name": "sort"}]})
    assert repr(flow) == "Workflow(nodes: 2, edges: 0)"


def test_repr_survives_a_cycle():
    flow = normalize_workflow(
        {
            "nodes": [{"id": "a", "name": "fetch"}, {"id": "b", "name": "sort"}],
            "edges": [
                {"source": {"node": "a"}, "target": {"node": "b"}},
                {"source": {"node": "b"}, "target": {"node": "a"}},
            ],
        }
    )
    assert repr(flow) == "Workflow(nodes: 2, edges: 2)"


def test_pipeline_repr_notes_seed_and_context():
    fetch = Pipeline.from_module("fetch")
    assert repr(fetch) == "Pipeline(fetch-1; outputs: default)"
    seeded = Pipeline(source=[{"x": 1}], context=Context())
    assert repr(seeded) == "Pipeline(empty; seed; context)"
