# vim: sw=4:ts=4:expandtab
"""
Tests for ``workflow.validate`` structural graph validation.

These build ``Workflow`` graphs directly and assert the closed-schema
rules: version, non-empty nodes, id/key agreement, endpoint references, stream fan-in,
publish/subscribe edge coherence, port direction, acyclicity, resource references, and
exposed outputs.
"""

import pytest

from riko.base.exceptions import InvalidPipelineError
from riko.definitions._workflow import Pipeline, Workflow
from riko.ext import ModuleNode, PublishEdge, StreamEdge, SubscribeNode
from riko.types._workflow import Endpoint


def _workflow(nodes, edges=(), outputs=None, inputs=None, resources=(), version="2"):
    node_map = {node.id: node for node in nodes}
    return Workflow(
        nodes=node_map,
        edges=tuple(edges),
        outputs={} if outputs is None else outputs,
        inputs={} if inputs is None else inputs,
        resources=resources,
        version=version,
    )


def test_valid_workflow_passes():
    node = ModuleNode(id="a", name="fetch")
    workflow = _workflow([node], outputs={"default": Endpoint("a", "out")})
    assert workflow.validate() is None


def test_unsupported_version_rejected():
    node = ModuleNode(id="a", name="fetch")
    workflow = _workflow([node], outputs={"default": Endpoint("a", "out")}, version="1")
    with pytest.raises(InvalidPipelineError, match="unsupported workflow version"):
        workflow.validate()


def test_empty_node_set_rejected():
    with pytest.raises(InvalidPipelineError, match="no nodes"):
        _workflow([]).validate()


def test_node_id_key_mismatch_rejected():
    workflow = Workflow(
        nodes={"a": ModuleNode(id="b", name="fetch")},
        edges=(),
        outputs={"default": Endpoint("b", "out")},
        inputs={},
    )
    with pytest.raises(InvalidPipelineError, match="does not match its key"):
        workflow.validate()


def test_missing_edge_reference_rejected():
    node = ModuleNode(id="a", name="fetch")
    edge = StreamEdge(Endpoint("a", "out"), Endpoint("ghost", "in"))
    workflow = _workflow(
        [node], edges=[edge], outputs={"default": Endpoint("a", "out")}
    )
    with pytest.raises(InvalidPipelineError, match="missing node"):
        workflow.validate()


def test_missing_output_reference_rejected():
    node = ModuleNode(id="a", name="fetch")
    workflow = _workflow([node], outputs={"default": Endpoint("ghost", "out")})
    with pytest.raises(InvalidPipelineError, match="missing node"):
        workflow.validate()


def test_multiple_stream_edges_into_one_port_rejected():
    a = ModuleNode(id="a", name="fetch")
    b = ModuleNode(id="b", name="fetch")
    c = ModuleNode(id="c", name="join")
    edges = [
        StreamEdge(Endpoint("a", "out"), Endpoint("c", "in")),
        StreamEdge(Endpoint("b", "out"), Endpoint("c", "in")),
    ]
    workflow = _workflow(
        [a, b, c], edges=edges, outputs={"default": Endpoint("c", "out")}
    )
    with pytest.raises(InvalidPipelineError, match="multiple stream edges"):
        workflow.validate()


def test_distinct_fanin_ports_pass():
    a = ModuleNode(id="a", name="fetch")
    b = ModuleNode(id="b", name="fetch")
    c = ModuleNode(id="c", name="join")
    edges = [
        StreamEdge(Endpoint("a", "out"), Endpoint("c", "in")),
        StreamEdge(Endpoint("b", "out"), Endpoint("c", "in:1")),
    ]
    workflow = _workflow(
        [a, b, c], edges=edges, outputs={"default": Endpoint("c", "out")}
    )
    assert workflow.validate() is None


def test_publish_edge_to_non_subscribe_rejected():
    a = ModuleNode(id="a", name="fetch")
    b = ModuleNode(id="b", name="filter")
    edge = PublishEdge(Endpoint("a", "out"), Endpoint("b", "in"))
    workflow = _workflow(
        [a, b], edges=[edge], outputs={"default": Endpoint("b", "out")}
    )
    with pytest.raises(InvalidPipelineError, match="edge family disagrees"):
        workflow.validate()


def test_stream_edge_to_subscribe_rejected():
    a = ModuleNode(id="a", name="fetch")
    sub = SubscribeNode(id="s", name="sub")
    edge = StreamEdge(Endpoint("a", "out"), Endpoint("s", "in"))
    workflow = _workflow(
        [a, sub], edges=[edge], outputs={"default": Endpoint("a", "out")}
    )
    with pytest.raises(InvalidPipelineError, match="edge family disagrees"):
        workflow.validate()


def test_publish_edge_to_subscribe_passes():
    a = ModuleNode(id="a", name="fetch")
    sub = SubscribeNode(id="s", name="sub")
    edge = PublishEdge(Endpoint("a", "out"), Endpoint("s", "in"))
    workflow = _workflow(
        [a, sub], edges=[edge], outputs={"default": Endpoint("a", "out")}
    )
    assert workflow.validate() is None


def test_unresolved_resource_reference_rejected():
    node = ModuleNode(id="a", name="fetch", resources={"db": "prod"})
    workflow = _workflow([node], outputs={"default": Endpoint("a", "out")})
    with pytest.raises(InvalidPipelineError, match="unresolved resource"):
        workflow.validate()


def test_declared_resource_reference_passes():
    node = ModuleNode(id="a", name="fetch", resources={"db": "prod"})
    workflow = _workflow(
        [node], outputs={"default": Endpoint("a", "out")}, resources=("prod",)
    )
    assert workflow.validate() is None


def test_non_empty_graph_without_output_rejected():
    node = ModuleNode(id="a", name="fetch")
    with pytest.raises(InvalidPipelineError, match="exposes no output"):
        _workflow([node]).validate()


def test_edge_source_on_input_port_rejected():
    a = ModuleNode(id="a", name="fetch")
    b = ModuleNode(id="b", name="sort")
    edges = [StreamEdge(Endpoint("a", "in"), Endpoint("b", "in"))]
    workflow = _workflow([a, b], edges=edges, outputs={"default": Endpoint("b", "out")})
    with pytest.raises(InvalidPipelineError, match=r"'a', 'in'.*not an 'out' port"):
        workflow.validate()


def test_edge_target_on_output_port_rejected():
    a = ModuleNode(id="a", name="fetch")
    b = ModuleNode(id="b", name="sort")
    edges = [StreamEdge(Endpoint("a", "out"), Endpoint("b", "out"))]
    workflow = _workflow([a, b], edges=edges, outputs={"default": Endpoint("b", "out")})
    with pytest.raises(InvalidPipelineError, match=r"'b', 'out'.*not an 'in' port"):
        workflow.validate()


def test_output_on_input_port_rejected():
    node = ModuleNode(id="a", name="fetch")
    workflow = _workflow([node], outputs={"default": Endpoint("a", "in")})
    with pytest.raises(InvalidPipelineError, match="not an 'out' port"):
        workflow.validate()


def test_malformed_port_rejected():
    node = ModuleNode(id="a", name="fetch")
    workflow = _workflow([node], outputs={"default": Endpoint("a", "sideways")})
    with pytest.raises(InvalidPipelineError, match="invalid port direction"):
        workflow.validate()


@pytest.mark.parametrize(
    ("source", "target"), [("out", "in:0"), ("out:0", "in")], ids=["in:0", "out:0"]
)
def test_zero_positional_port_rejected(source, target):
    a = ModuleNode(id="a", name="fetch")
    b = ModuleNode(id="b", name="sort")
    edges = [StreamEdge(Endpoint("a", source), Endpoint("b", target))]
    workflow = _workflow([a, b], edges=edges, outputs={"default": Endpoint("b", "out")})
    with pytest.raises(InvalidPipelineError, match="invalid port"):
        workflow.validate()


def test_cycle_rejected():
    a = ModuleNode(id="a", name="sort")
    b = ModuleNode(id="b", name="sort")
    edges = [
        StreamEdge(Endpoint("a", "out"), Endpoint("b", "in")),
        StreamEdge(Endpoint("b", "out"), Endpoint("a", "in")),
    ]
    workflow = _workflow([a, b], edges=edges, outputs={"default": Endpoint("b", "out")})
    with pytest.raises(InvalidPipelineError, match=r"cycle.*\['a', 'b'\]"):
        workflow.validate()


def test_self_loop_rejected():
    node = ModuleNode(id="a", name="sort")
    edges = [StreamEdge(Endpoint("a", "out"), Endpoint("a", "in"))]
    workflow = _workflow([node], edges=edges, outputs={"default": Endpoint("a", "out")})
    with pytest.raises(InvalidPipelineError, match=r"cycle.*\['a'\]"):
        workflow.validate()


def test_cycle_names_only_the_unrunnable_nodes():
    src = ModuleNode(id="src", name="fetch")
    a = ModuleNode(id="a", name="sort")
    b = ModuleNode(id="b", name="sort")
    edges = [
        StreamEdge(Endpoint("src", "out"), Endpoint("a", "in")),
        StreamEdge(Endpoint("a", "out"), Endpoint("b", "in")),
        StreamEdge(Endpoint("b", "out"), Endpoint("a", "in:1")),
    ]
    workflow = _workflow(
        [src, a, b], edges=edges, outputs={"default": Endpoint("b", "out")}
    )
    assert workflow.cyclic_nodes == ["a", "b"]


def _counted_source(consumed):
    for index in range(3):
        consumed.append(index)
        yield {"title": str(index)}


@pytest.mark.xfail(
    strict=True,
    reason="module configuration is not validated against its contract yet: "
    "an unknown key is silently ignored",
)
def test_unknown_conf_key_rejected_before_the_source_is_read():
    consumed = []
    rule = {"fieldd": "title", "op": "contains", "value": "1"}
    pipeline = _counted_source(consumed) | Pipeline.from_module(
        "filter",
        conf={"rule": rule},  # pyright: ignore[reportArgumentType]
    )

    with pytest.raises(InvalidPipelineError, match="fieldd"):
        list(pipeline)

    assert consumed == []


@pytest.mark.xfail(
    strict=True,
    reason="module configuration is not validated against its contract yet: "
    "a wrongly typed value fails later with AttributeError",
)
def test_wrongly_typed_conf_value_rejected_before_the_source_is_read():
    consumed = []
    pipeline = _counted_source(consumed) | Pipeline.from_module(
        "sort",
        conf={"rule": 5},  # pyright: ignore[reportArgumentType]
    )

    with pytest.raises(InvalidPipelineError, match="rule"):
        list(pipeline)

    assert consumed == []
