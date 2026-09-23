# vim: sw=4:ts=4:expandtab
"""
Tests for the ``normalize_workflow`` authoring-sugar normalization boundary.

These cover the structural, contract-free pass: node id generation and family
dispatch, enum coercion, legacy port aliases, edge-alias rejection, publish-edge
detection, omitted-outputs materialization, input shorthand, resource sugar, and
idempotency over an already-canonical authoring mapping.
"""

from types import MappingProxyType

import pytest

from riko.base.exceptions import InvalidPipelineError
from riko.definitions._workflow import (
    ModuleNode,
    PublishEdge,
    ReadNode,
    StreamEdge,
    SubscribeNode,
    WorkflowSpec,
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
    with pytest.raises(ValueError, match="Invalid Backends"):
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


def test_invalid_write_mode_rejected():
    with pytest.raises(ValueError, match="Invalid WriteMode"):
        normalize_workflow(
            {
                "nodes": [
                    {"name": "w", "type": "write", "backend": "file", "mode": "apend"}
                ]
            }
        )


def test_invalid_format_rejected():
    with pytest.raises(ValueError, match="Invalid Formats"):
        normalize_workflow(
            {"nodes": [{"name": "r", "type": "read", "backend": "file", "fmt": "xml"}]}
        )


def test_unknown_node_field_rejected():
    with pytest.raises(InvalidPipelineError, match="unknown ModuleNode field"):
        normalize_workflow({"nodes": [{"name": "fetch", "bogus": 1}]})


def test_unknown_top_level_field_rejected():
    with pytest.raises(InvalidPipelineError, match="unknown WorkflowSpec field"):
        normalize_workflow({"nodes": [{"name": "fetch"}], "bogus": 1})


def test_unknown_edge_field_rejected():
    with pytest.raises(InvalidPipelineError, match="unknown Edge field"):
        normalize_workflow(
            {
                "nodes": [{"id": "a", "name": "fetch"}],
                "edges": [
                    {"source": {"node": "a"}, "target": {"node": "a"}, "bogus": 1}
                ],
            }
        )


def test_unknown_edge_family_rejected():
    with pytest.raises(InvalidPipelineError, match="unknown edge family"):
        normalize_workflow(
            {
                "nodes": [{"id": "a", "name": "fetch"}, {"id": "b", "name": "filter"}],
                "edges": [
                    {
                        "source": {"node": "a"},
                        "target": {"node": "b"},
                        "family": "broadcast",
                    }
                ],
            }
        )


def test_explicit_stream_family_to_subscribe_is_preserved():
    spec = normalize_workflow(
        {
            "nodes": [
                {"id": "a", "name": "fetch"},
                {"id": "s", "name": "sub", "type": "subscribe"},
            ],
            "edges": [
                {"source": {"node": "a"}, "target": {"node": "s"}, "family": "stream"}
            ],
        }
    )
    assert isinstance(spec.edges[0], StreamEdge)


@pytest.mark.parametrize("port", ["out:", "bogus:x", ""])
def test_invalid_port_rejected(port):
    with pytest.raises(InvalidPipelineError, match="port"):
        normalize_workflow(
            {
                "nodes": [{"id": "a", "name": "fetch"}, {"id": "b", "name": "filter"}],
                "edges": [
                    {"source": {"node": "a"}, "target": {"node": "b", "port": port}}
                ],
            }
        )


def test_explicit_empty_outputs_not_materialized():
    spec = normalize_workflow({"nodes": [{"id": "a", "name": "fetch"}], "outputs": {}})
    assert spec.outputs == {}


def test_falsey_conf_rejected_not_coerced():
    with pytest.raises(InvalidPipelineError, match="ModuleNode 'conf'"):
        normalize_workflow({"nodes": [{"name": "fetch", "conf": []}]})


def test_write_dest_is_preserved():
    spec = normalize_workflow(
        {
            "nodes": [
                {"name": "w", "type": "write", "backend": "file", "dest": "out.json"}
            ]
        }
    )
    write = spec.nodes["w-1"]
    assert isinstance(write, WriteNode)
    assert write.dest == "out.json"


def test_node_conf_is_isolated_from_caller_mutation():
    conf = {"limit": 5}
    spec = normalize_workflow({"nodes": [{"id": "a", "name": "fetch", "conf": conf}]})
    node = spec.nodes["a"]
    conf["limit"] = 99
    assert isinstance(node, ModuleNode)
    assert node.conf == {"limit": 5}


def test_normalizing_a_spec_is_a_fixed_point():
    first = normalize_workflow(
        {
            "nodes": [
                {"name": "fetch"},
                {"name": "write", "type": "write", "backend": "file"},
            ],
            "edges": [{"source": {"node": "fetch-1"}, "target": {"node": "write-1"}}],
        }
    )
    assert normalize_workflow(first) == first
    assert normalize_workflow(normalize_workflow(first)) == first


def test_normalize_recanonicalizes_a_hand_built_spec():
    a = ModuleNode(id="a", name="fetch")
    b = ModuleNode(id="b", name="filter")
    hand = WorkflowSpec(
        nodes={"a": a, "b": b},
        edges=(StreamEdge(Endpoint("a", "_OUTPUT"), Endpoint("b", "_OTHER2")),),
        outputs={"default": Endpoint("b", "_OUTPUT")},
        inputs={},
    )
    canon = normalize_workflow(hand)
    assert canon.edges[0].source.port == "out"
    assert canon.edges[0].target.port == "in:2"
    assert canon.outputs["default"].port == "out"


def test_mapping_key_conflicting_inner_id_rejected():
    with pytest.raises(InvalidPipelineError, match="conflicts"):
        normalize_workflow({"nodes": {"a": {"id": "b", "name": "fetch"}}})


def test_mapping_key_matching_inner_id_allowed():
    spec = normalize_workflow({"nodes": {"a": {"id": "a", "name": "fetch"}}})
    assert list(spec.nodes) == ["a"]


def test_unknown_endpoint_field_rejected():
    with pytest.raises(InvalidPipelineError, match="unknown Endpoint field"):
        normalize_workflow(
            {
                "nodes": [{"id": "a", "name": "f"}, {"id": "b", "name": "g"}],
                "edges": [
                    {"source": {"node": "a"}, "target": {"node": "b", "porrt": "in"}}
                ],
            }
        )


def test_format_alias_maps_to_fmt():
    spec = normalize_workflow(
        {
            "nodes": [
                {
                    "id": "r",
                    "name": "read",
                    "type": "read",
                    "backend": "file",
                    "format": "csv",
                }
            ]
        }
    )
    read = spec.nodes["r"]
    assert isinstance(read, ReadNode)
    assert read.fmt is Formats.CSV


def test_format_and_fmt_together_rejected():
    with pytest.raises(InvalidPipelineError, match="'fmt' or 'format'"):
        normalize_workflow(
            {
                "nodes": [
                    {
                        "id": "r",
                        "name": "read",
                        "type": "read",
                        "backend": "file",
                        "fmt": "csv",
                        "format": "jsonl",
                    }
                ]
            }
        )


@pytest.mark.parametrize("port", ["in:name", "in:x", "out:-1"])
def test_named_input_and_bad_index_ports_rejected(port):
    with pytest.raises(InvalidPipelineError, match="port"):
        normalize_workflow(
            {
                "nodes": [{"id": "a", "name": "f"}, {"id": "b", "name": "g"}],
                "edges": [
                    {"source": {"node": "a"}, "target": {"node": "b", "port": port}}
                ],
            }
        )


def test_legacy_prefix_with_non_numeric_suffix_is_not_misconverted():
    spec = normalize_workflow(
        {
            "nodes": [{"id": "a", "name": "f"}, {"id": "b", "name": "g"}],
            "edges": [
                {"source": {"node": "a"}, "target": {"node": "b", "port": "count"}}
            ],
        }
    )
    assert spec.edges[0].target.port == "count"


def test_nested_conf_is_deeply_frozen_and_isolated():
    inner = {"k": 1}
    spec = normalize_workflow(
        {"nodes": [{"id": "a", "name": "f", "conf": {"nested": inner, "list": [1, 2]}}]}
    )
    inner["k"] = 99
    node = spec.nodes["a"]
    assert isinstance(node, ModuleNode)
    assert node.conf is not None
    assert node.conf["nested"] == {"k": 1}
    assert node.conf["list"] == (1, 2)
    assert isinstance(node.conf["nested"], MappingProxyType)
