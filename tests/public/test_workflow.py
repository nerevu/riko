# vim: sw=4:ts=4:expandtab
"""
Structural tests for the canonical Workflow v2 model.

These exercise the closed node/edge families, the immutable ``WorkflowSpec`` envelope,
the ``Pipeline`` definition, and the port grammar. They cover structure only; runtime
execution of the graph lands in a later phase.
"""

import pytest

from riko import Pipeline
from riko.definitions._write import WriteMode
from riko.ext import (
    ActionNode,
    CacheNode,
    Endpoint,
    ModuleNode,
    PublishEdge,
    ReadNode,
    StreamEdge,
    SubscribeNode,
    WorkflowSpec,
    WriteNode,
)
from riko.types._enums import Backends
from riko.types._workflow import ParsedPort, parse_port

NODE_FAMILIES = (
    (ModuleNode(id="fetch-1", name="fetch"), "module"),
    (ReadNode(id="read-1", name="read", backend=Backends.FILE), "read"),
    (WriteNode(id="write-1", name="write", backend=Backends.FILE), "write"),
    (CacheNode(id="cache-1", name="cache"), "cache"),
    (ActionNode(id="act-1", name="act", backend=Backends.HTTP), "action"),
    (SubscribeNode(id="sub-1", name="sub"), "subscribe"),
)


def _spec():
    node = ModuleNode(id="fetch-1", name="fetch")
    return WorkflowSpec(
        nodes={node.id: node},
        edges=(),
        outputs={"default": Endpoint(node.id, "out")},
        inputs={},
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


def test_spec_mappings_are_read_only():
    spec = _spec()
    assert type(spec.nodes).__name__ == "mappingproxy"
    with pytest.raises(TypeError):
        spec.outputs["extra"] = Endpoint("fetch-1", "out")  # type: ignore[index]


def test_spec_version_defaults_to_v2():
    assert _spec().version == "2"


def test_pipeline_wraps_spec():
    spec = _spec()
    pipeline: Pipeline[dict[str, object]] = Pipeline(spec)
    assert pipeline.spec is spec
    assert pipeline.spec.outputs["default"] == Endpoint("fetch-1", "out")


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
