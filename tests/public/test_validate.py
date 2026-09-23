# vim: sw=4:ts=4:expandtab
"""
Tests for ``spec.validate`` structural graph validation.

These build canonical ``WorkflowSpec`` graphs directly and assert the closed-schema
rules: version, non-empty nodes, id/key agreement, endpoint references, stream fan-in,
publish/subscribe edge coherence, resource references, and exposed outputs.
"""

import pytest

from riko.base.exceptions import InvalidPipelineError
from riko.ext import (
    Endpoint,
    ModuleNode,
    PublishEdge,
    StreamEdge,
    SubscribeNode,
    WorkflowSpec,
)


def _spec(nodes, edges=(), outputs=None, inputs=None, resources=(), version="2"):
    node_map = {node.id: node for node in nodes}
    return WorkflowSpec(
        nodes=node_map,
        edges=tuple(edges),
        outputs={} if outputs is None else outputs,
        inputs={} if inputs is None else inputs,
        resources=resources,
        version=version,
    )


def test_valid_spec_passes():
    node = ModuleNode(id="a", name="fetch")
    spec = _spec([node], outputs={"default": Endpoint("a", "out")})
    assert spec.validate() is None


def test_unsupported_version_rejected():
    node = ModuleNode(id="a", name="fetch")
    spec = _spec([node], outputs={"default": Endpoint("a", "out")}, version="1")
    with pytest.raises(InvalidPipelineError, match="unsupported workflow version"):
        spec.validate()


def test_empty_node_set_rejected():
    with pytest.raises(InvalidPipelineError, match="no nodes"):
        _spec([]).validate()


def test_node_id_key_mismatch_rejected():
    spec = WorkflowSpec(
        nodes={"a": ModuleNode(id="b", name="fetch")},
        edges=(),
        outputs={"default": Endpoint("b", "out")},
        inputs={},
    )
    with pytest.raises(InvalidPipelineError, match="does not match its key"):
        spec.validate()


def test_missing_edge_reference_rejected():
    node = ModuleNode(id="a", name="fetch")
    edge = StreamEdge(Endpoint("a", "out"), Endpoint("ghost", "in"))
    spec = _spec([node], edges=[edge], outputs={"default": Endpoint("a", "out")})
    with pytest.raises(InvalidPipelineError, match="missing node"):
        spec.validate()


def test_missing_output_reference_rejected():
    node = ModuleNode(id="a", name="fetch")
    spec = _spec([node], outputs={"default": Endpoint("ghost", "out")})
    with pytest.raises(InvalidPipelineError, match="missing node"):
        spec.validate()


def test_multiple_stream_edges_into_one_port_rejected():
    a = ModuleNode(id="a", name="fetch")
    b = ModuleNode(id="b", name="fetch")
    c = ModuleNode(id="c", name="join")
    edges = [
        StreamEdge(Endpoint("a", "out"), Endpoint("c", "in")),
        StreamEdge(Endpoint("b", "out"), Endpoint("c", "in")),
    ]
    spec = _spec([a, b, c], edges=edges, outputs={"default": Endpoint("c", "out")})
    with pytest.raises(InvalidPipelineError, match="multiple stream edges"):
        spec.validate()


def test_distinct_fanin_ports_pass():
    a = ModuleNode(id="a", name="fetch")
    b = ModuleNode(id="b", name="fetch")
    c = ModuleNode(id="c", name="join")
    edges = [
        StreamEdge(Endpoint("a", "out"), Endpoint("c", "in")),
        StreamEdge(Endpoint("b", "out"), Endpoint("c", "in:1")),
    ]
    spec = _spec([a, b, c], edges=edges, outputs={"default": Endpoint("c", "out")})
    assert spec.validate() is None


def test_publish_edge_to_non_subscribe_rejected():
    a = ModuleNode(id="a", name="fetch")
    b = ModuleNode(id="b", name="filter")
    edge = PublishEdge(Endpoint("a", "out"), Endpoint("b", "in"))
    spec = _spec([a, b], edges=[edge], outputs={"default": Endpoint("b", "out")})
    with pytest.raises(InvalidPipelineError, match="edge family disagrees"):
        spec.validate()


def test_stream_edge_to_subscribe_rejected():
    a = ModuleNode(id="a", name="fetch")
    sub = SubscribeNode(id="s", name="sub")
    edge = StreamEdge(Endpoint("a", "out"), Endpoint("s", "in"))
    spec = _spec([a, sub], edges=[edge], outputs={"default": Endpoint("a", "out")})
    with pytest.raises(InvalidPipelineError, match="edge family disagrees"):
        spec.validate()


def test_publish_edge_to_subscribe_passes():
    a = ModuleNode(id="a", name="fetch")
    sub = SubscribeNode(id="s", name="sub")
    edge = PublishEdge(Endpoint("a", "out"), Endpoint("s", "in"))
    spec = _spec([a, sub], edges=[edge], outputs={"default": Endpoint("a", "out")})
    assert spec.validate() is None


def test_unresolved_resource_reference_rejected():
    node = ModuleNode(id="a", name="fetch", resources={"db": "prod"})
    spec = _spec([node], outputs={"default": Endpoint("a", "out")})
    with pytest.raises(InvalidPipelineError, match="unresolved resource"):
        spec.validate()


def test_declared_resource_reference_passes():
    node = ModuleNode(id="a", name="fetch", resources={"db": "prod"})
    spec = _spec([node], outputs={"default": Endpoint("a", "out")}, resources=("prod",))
    assert spec.validate() is None


def test_non_empty_graph_without_output_rejected():
    node = ModuleNode(id="a", name="fetch")
    with pytest.raises(InvalidPipelineError, match="exposes no output"):
        _spec([node]).validate()
