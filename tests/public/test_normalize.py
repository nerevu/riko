# vim: sw=4:ts=4:expandtab
"""
Tests for the ``normalize_workflow`` authoring-sugar normalization boundary.

These cover the structural, contract-free pass: node id generation and family
dispatch, enum coercion, legacy port aliases, edge-alias rejection, publish-edge
detection, omitted-outputs materialization, input shorthand, resource sugar, and
idempotency over an already-canonical authoring mapping.
"""

import pytest

from riko.base.exceptions import InvalidPipelineError
from riko.definitions._workflow import (
    ModuleNode,
    PublishEdge,
    ReadNode,
    StreamEdge,
    SubscribeNode,
    WriteNode,
)
from riko.definitions._write import WriteMode
from riko.ext import normalize_workflow
from riko.runtime._normalize import _normalize_port
from riko.types._enums import Backends, Formats
from riko.types._workflow import Endpoint


@pytest.mark.parametrize(
    ("legacy", "canonical"),
    [
        ("_INPUT", "in"),
        ("_OTHER", "in:1"),
        ("_OTHER2", "in:2"),
        ("_OTHER5", "in:5"),
        ("_OUTPUT", "out"),
        ("_OUTPUT2", "out:1"),
        ("_OUTPUT4", "out:3"),
        ("out:matched", "out:matched"),
        ("in", "in"),
    ],
)
def test_normalize_port_maps_open_ended_legacy_series(legacy, canonical):
    assert _normalize_port(legacy) == canonical


def test_list_nodes_generate_occurrence_ids():
    spec = normalize_workflow(
        {"nodes": [{"name": "fetch"}, {"name": "filter"}, {"name": "filter"}]}
    )
    assert list(spec.nodes) == ["fetch-1", "filter-1", "filter-2"]


def test_mapping_nodes_keep_explicit_ids():
    spec = normalize_workflow({"nodes": {"a": {"name": "fetch"}}})
    assert isinstance(spec.nodes["a"], ModuleNode)
    assert spec.nodes["a"].name == "fetch"


def test_explicit_id_in_list_is_preserved():
    spec = normalize_workflow({"nodes": [{"id": "keep", "name": "fetch"}]})
    assert list(spec.nodes) == ["keep"]


def test_family_dispatch_and_enum_coercion():
    spec = normalize_workflow(
        {
            "nodes": [
                {"name": "read", "type": "read", "backend": "file", "fmt": "csv"},
                {
                    "name": "write",
                    "type": "write",
                    "backend": "s3",
                    "fmt": "jsonl",
                    "mode": "append",
                    "keys": "id",
                },
            ]
        }
    )
    read = spec.nodes["read-1"]
    write = spec.nodes["write-1"]
    assert isinstance(read, ReadNode)
    assert read.backend is Backends.FILE
    assert read.fmt is Formats.CSV
    assert isinstance(write, WriteNode)
    assert write.backend is Backends.S3
    assert write.fmt is Formats.JSONL
    assert write.mode is WriteMode.APPEND
    assert write.keys == ("id",)


def test_unknown_backend_raises():
    with pytest.raises(InvalidPipelineError, match="unknown backend"):
        normalize_workflow({"nodes": [{"name": "r", "type": "read", "backend": "ftp"}]})


def test_unknown_node_family_raises():
    with pytest.raises(InvalidPipelineError, match="unknown node family"):
        normalize_workflow({"nodes": [{"name": "x", "family": "sink"}]})


def test_missing_node_name_raises():
    with pytest.raises(InvalidPipelineError, match="node 'name'"):
        normalize_workflow({"nodes": [{"type": "module"}]})


def test_legacy_ports_map_to_canonical_grammar():
    spec = normalize_workflow(
        {
            "nodes": [{"id": "a", "name": "fetch"}, {"id": "b", "name": "join"}],
            "edges": [
                {
                    "source": {"node": "a", "port": "_OUTPUT"},
                    "target": {"node": "b", "port": "_OTHER"},
                }
            ],
        }
    )
    edge = spec.edges[0]
    assert edge.source == Endpoint("a", "out")
    assert edge.target == Endpoint("b", "in:1")


def test_default_ports_when_omitted():
    spec = normalize_workflow(
        {
            "nodes": [{"id": "a", "name": "fetch"}, {"id": "b", "name": "filter"}],
            "edges": [{"source": {"node": "a"}, "target": {"node": "b"}}],
        }
    )
    assert spec.edges[0] == StreamEdge(Endpoint("a", "out"), Endpoint("b", "in"))


@pytest.mark.parametrize("alias", ["src", "tgt", "from", "to"])
def test_edge_shorthand_aliases_rejected(alias):
    with pytest.raises(InvalidPipelineError, match="'source'/'target'"):
        normalize_workflow(
            {
                "nodes": [{"id": "a", "name": "fetch"}],
                "edges": [{alias: {"node": "a"}, "target": {"node": "a"}}],
            }
        )


def test_publish_edge_detected_from_subscribe_target():
    spec = normalize_workflow(
        {
            "nodes": [
                {"id": "a", "name": "fetch"},
                {"id": "s", "name": "sub", "type": "subscribe"},
            ],
            "edges": [{"source": {"node": "a"}, "target": {"node": "s"}}],
        }
    )
    assert isinstance(spec.nodes["s"], SubscribeNode)
    assert isinstance(spec.edges[0], PublishEdge)


def test_omitted_outputs_materialize_single_leaf():
    spec = normalize_workflow(
        {
            "nodes": [{"id": "a", "name": "fetch"}, {"id": "b", "name": "filter"}],
            "edges": [{"source": {"node": "a"}, "target": {"node": "b"}}],
        }
    )
    assert spec.outputs == {"default": Endpoint("b", "out")}


def test_omitted_outputs_empty_when_ambiguous():
    spec = normalize_workflow(
        {"nodes": [{"id": "a", "name": "fetch"}, {"id": "b", "name": "other"}]}
    )
    assert spec.outputs == {}


def test_explicit_outputs_alias_ports():
    spec = normalize_workflow(
        {
            "nodes": [{"id": "a", "name": "route"}],
            "outputs": {"errors": {"node": "a", "port": "_OUTPUT2"}},
        }
    )
    assert spec.outputs == {"errors": Endpoint("a", "out:1")}


def test_input_string_shorthand_becomes_schema():
    spec = normalize_workflow(
        {"nodes": [{"id": "a", "name": "fetch"}], "inputs": {"customer_id": "string"}}
    )
    assert spec.inputs["customer_id"] == {"type": "string"}


def test_input_mapping_passes_through():
    schema = {"type": "integer", "default": 0}
    spec = normalize_workflow(
        {"nodes": [{"id": "a", "name": "fetch"}], "inputs": {"n": schema}}
    )
    assert spec.inputs["n"] == schema


def test_bare_string_resource_binds_to_itself():
    spec = normalize_workflow(
        {"nodes": [{"id": "a", "name": "fetch", "resources": "db"}]}
    )
    assert spec.nodes["a"].resources == {"db": "db"}


def test_top_level_resources_normalize_to_tuple():
    spec = normalize_workflow(
        {"nodes": [{"id": "a", "name": "fetch"}], "resources": ["db", "cache"]}
    )
    assert spec.resources == ("db", "cache")


def test_top_level_resources_accept_bare_string():
    spec = normalize_workflow(
        {"nodes": [{"id": "a", "name": "fetch"}], "resources": "db"}
    )
    assert spec.resources == ("db",)


def test_version_defaults_to_v2():
    spec = normalize_workflow({"nodes": [{"id": "a", "name": "fetch"}]})
    assert spec.version == "2"


def test_duplicate_ids_rejected():
    with pytest.raises(InvalidPipelineError, match="duplicate node id"):
        normalize_workflow(
            {"nodes": [{"id": "a", "name": "fetch"}, {"id": "a", "name": "filter"}]}
        )


def test_normalize_is_idempotent_over_canonical_input():
    canonical = {
        "nodes": [
            {"id": "fetch-1", "name": "fetch"},
            {"id": "write-1", "name": "write", "type": "write", "backend": "file"},
        ],
        "edges": [{"source": {"node": "fetch-1"}, "target": {"node": "write-1"}}],
        "outputs": {"default": {"node": "write-1", "port": "out"}},
        "inputs": {},
        "resources": (),
        "version": "2",
    }
    first = normalize_workflow(canonical)
    second = normalize_workflow(canonical)
    assert first == second
    assert dict(first.nodes) == dict(second.nodes)
    assert first.edges == second.edges
    assert dict(first.outputs) == dict(second.outputs)
