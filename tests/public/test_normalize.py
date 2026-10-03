# vim: sw=4:ts=4:expandtab
"""
Tests for the ``normalize_workflow`` authoring-sugar normalization boundary.

These cover the structural, contract-free pass: node id generation and family
dispatch, enum coercion, legacy port aliases, edge-alias rejection, publish-edge
detection, omitted-outputs materialization, input shorthand, resource sugar, and
idempotency over an already-canonical RawWorkflow.
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
    Workflow,
    WriteNode,
)
from riko.definitions._write import WriteMode
from riko.ext import normalize_workflow
from riko.runtime._normalize import _normalize_port
from riko.types._enums import Backends, Formats
from riko.types._workflow import Endpoint


@pytest.mark.parametrize(
    ("legacy", "direction", "canonical"),
    [
        ("_INPUT", "in", "in"),
        ("_OTHER", "in", "in:1"),
        ("_OTHER2", "in", "in:2"),
        ("_OTHER5", "in", "in:5"),
        ("_OUTPUT", "out", "out"),
        ("_OUTPUT2", "out", "out:1"),
        ("_OUTPUT4", "out", "out:3"),
        ("out:matched", "out", "out:matched"),
        ("in", "in", "in"),
        ("count", "in", "in:count"),
        ("matched", "out", "out:matched"),
    ],
)
def test_normalize_port_maps_open_ended_legacy_series(legacy, direction, canonical):
    assert _normalize_port(legacy, direction) == canonical


def test_list_nodes_generate_occurrence_ids():
    workflow = normalize_workflow(
        {"nodes": [{"name": "fetch"}, {"name": "filter"}, {"name": "filter"}]}
    )
    assert list(workflow.nodes) == ["fetch-1", "filter-1", "filter-2"]


def test_mapping_nodes_keep_explicit_ids():
    workflow = normalize_workflow({"nodes": {"a": {"name": "fetch"}}})
    assert isinstance(workflow.nodes["a"], ModuleNode)
    assert workflow.nodes["a"].name == "fetch"


def test_explicit_id_in_list_is_preserved():
    workflow = normalize_workflow({"nodes": [{"id": "keep", "name": "fetch"}]})
    assert list(workflow.nodes) == ["keep"]


def test_family_dispatch_and_enum_coercion():
    workflow = normalize_workflow(
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
    read = workflow.nodes["read-1"]
    write = workflow.nodes["write-1"]
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
    workflow = normalize_workflow(
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
    edge = workflow.edges[0]
    assert edge.source == Endpoint("a", "out")
    assert edge.target == Endpoint("b", "in:1")


def test_default_ports_when_omitted():
    workflow = normalize_workflow(
        {
            "nodes": [{"id": "a", "name": "fetch"}, {"id": "b", "name": "filter"}],
            "edges": [{"source": {"node": "a"}, "target": {"node": "b"}}],
        }
    )
    assert workflow.edges[0] == StreamEdge(Endpoint("a", "out"), Endpoint("b", "in"))


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
    workflow = normalize_workflow(
        {
            "nodes": [
                {"id": "a", "name": "fetch"},
                {"id": "s", "name": "sub", "type": "subscribe"},
            ],
            "edges": [{"source": {"node": "a"}, "target": {"node": "s"}}],
        }
    )
    assert isinstance(workflow.nodes["s"], SubscribeNode)
    assert isinstance(workflow.edges[0], PublishEdge)


def test_omitted_outputs_materialize_single_leaf():
    workflow = normalize_workflow(
        {
            "nodes": [{"id": "a", "name": "fetch"}, {"id": "b", "name": "filter"}],
            "edges": [{"source": {"node": "a"}, "target": {"node": "b"}}],
        }
    )
    assert workflow.outputs == {"default": Endpoint("b", "out")}


def test_omitted_outputs_empty_when_ambiguous():
    workflow = normalize_workflow(
        {"nodes": [{"id": "a", "name": "fetch"}, {"id": "b", "name": "other"}]}
    )
    assert workflow.outputs == {}


def test_explicit_outputs_alias_ports():
    workflow = normalize_workflow(
        {
            "nodes": [{"id": "a", "name": "route"}],
            "outputs": {"errors": {"node": "a", "port": "_OUTPUT2"}},
        }
    )
    assert workflow.outputs == {"errors": Endpoint("a", "out:1")}


def test_input_string_shorthand_becomes_schema():
    workflow = normalize_workflow(
        {"nodes": [{"id": "a", "name": "fetch"}], "inputs": {"customer_id": "string"}}
    )
    assert workflow.inputs["customer_id"] == {"type": "string"}


def test_input_mapping_passes_through():
    schema = {"type": "integer", "default": 0}
    workflow = normalize_workflow(
        {"nodes": [{"id": "a", "name": "fetch"}], "inputs": {"n": schema}}
    )
    assert workflow.inputs["n"] == schema


def test_bare_string_resource_binds_to_itself():
    workflow = normalize_workflow(
        {"nodes": [{"id": "a", "name": "fetch", "resources": "db"}]}
    )
    assert workflow.nodes["a"].resources == {"db": "db"}


def test_top_level_resources_normalize_to_tuple():
    workflow = normalize_workflow(
        {"nodes": [{"id": "a", "name": "fetch"}], "resources": ["db", "cache"]}
    )
    assert workflow.resources == ("db", "cache")


def test_top_level_resources_accept_bare_string():
    workflow = normalize_workflow(
        {"nodes": [{"id": "a", "name": "fetch"}], "resources": "db"}
    )
    assert workflow.resources == ("db",)


def test_version_defaults_to_v2():
    workflow = normalize_workflow({"nodes": [{"id": "a", "name": "fetch"}]})
    assert workflow.version == "2"


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
    with pytest.raises(InvalidPipelineError, match="unknown Workflow field"):
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
    workflow = normalize_workflow(
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
    assert isinstance(workflow.edges[0], StreamEdge)


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
    workflow = normalize_workflow(
        {"nodes": [{"id": "a", "name": "fetch"}], "outputs": {}}
    )
    assert workflow.outputs == {}


def test_falsey_conf_rejected_not_coerced():
    with pytest.raises(InvalidPipelineError, match="ModuleNode 'conf'"):
        normalize_workflow({"nodes": [{"name": "fetch", "conf": []}]})


def test_write_dest_is_preserved():
    workflow = normalize_workflow(
        {
            "nodes": [
                {"name": "w", "type": "write", "backend": "file", "dest": "out.json"}
            ]
        }
    )
    write = workflow.nodes["w-1"]
    assert isinstance(write, WriteNode)
    assert write.dest == "out.json"


def test_node_conf_is_isolated_from_caller_mutation():
    conf = {"limit": 5}
    workflow = normalize_workflow(
        {"nodes": [{"id": "a", "name": "fetch", "conf": conf}]}
    )
    node = workflow.nodes["a"]
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
    hand = Workflow(
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
    workflow = normalize_workflow({"nodes": {"a": {"id": "a", "name": "fetch"}}})
    assert list(workflow.nodes) == ["a"]


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
    workflow = normalize_workflow(
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
    read = workflow.nodes["r"]
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


@pytest.mark.parametrize("port", ["out:-1", "in:-1", "out:a b"])
def test_bad_index_ports_rejected(port):
    with pytest.raises(InvalidPipelineError, match="port"):
        normalize_workflow(
            {
                "nodes": [{"id": "a", "name": "f"}, {"id": "b", "name": "g"}],
                "edges": [
                    {"source": {"node": "a"}, "target": {"node": "b", "port": port}}
                ],
            }
        )


def test_named_input_port_canonicalized():
    workflow = normalize_workflow(
        {
            "nodes": [{"id": "a", "name": "f"}, {"id": "b", "name": "g"}],
            "edges": [
                {"source": {"node": "a"}, "target": {"node": "b", "port": "in:count"}}
            ],
        }
    )
    assert workflow.edges[0].target.port == "in:count"


def test_legacy_prefix_with_non_numeric_suffix_is_not_misconverted():
    workflow = normalize_workflow(
        {
            "nodes": [{"id": "a", "name": "f"}, {"id": "b", "name": "g"}],
            "edges": [
                {"source": {"node": "a"}, "target": {"node": "b", "port": "count"}}
            ],
        }
    )
    assert workflow.edges[0].target.port == "in:count"


def test_authoring_call_options_are_accepted():
    workflow = normalize_workflow(
        {
            "nodes": [
                {"name": "tokenizer", "options": {"field": "title", "count": "first"}}
            ]
        }
    )
    node = workflow.nodes["tokenizer-1"]
    assert isinstance(node, ModuleNode)
    assert node.options == {"field": "title", "count": "first"}
    assert node.conf == {}


def test_unknown_call_option_is_rejected():
    with pytest.raises(InvalidPipelineError, match="unknown module option"):
        normalize_workflow({"nodes": [{"name": "tokenizer", "options": {"bogus": 1}}]})


def test_nested_conf_is_deeply_frozen_and_isolated():
    inner = {"k": 1}
    workflow = normalize_workflow(
        {"nodes": [{"id": "a", "name": "f", "conf": {"nested": inner, "list": [1, 2]}}]}
    )
    inner["k"] = 99
    node = workflow.nodes["a"]
    assert isinstance(node, ModuleNode)
    assert node.conf is not None
    assert node.conf.get("nested") == {"k": 1}
    assert node.conf.get("list") == (1, 2)
    assert isinstance(node.conf.get("nested"), MappingProxyType)


def test_authoring_embed_becomes_a_read_only_node_field():
    workflow = normalize_workflow(
        {
            "nodes": [
                {"name": "loop", "embed": {"name": "tokenizer", "conf": {"d": " "}}}
            ]
        }
    )
    node = workflow.nodes["loop-1"]
    assert isinstance(node, ModuleNode)
    assert node.embed == {"name": "tokenizer", "conf": {"d": " "}}
    assert isinstance(node.embed, MappingProxyType)
    assert node.conf == {}


def test_embed_conf_defaults_to_empty_when_omitted():
    workflow = normalize_workflow(
        {"nodes": [{"name": "loop", "embed": {"name": "tokenizer"}}]}
    )
    node = workflow.nodes["loop-1"]
    assert isinstance(node, ModuleNode)
    assert node.embed == {"name": "tokenizer", "conf": {}}


def test_unknown_embed_key_is_rejected():
    with pytest.raises(InvalidPipelineError, match="unknown embed key"):
        normalize_workflow(
            {"nodes": [{"name": "loop", "embed": {"name": "tokenizer", "bogus": 1}}]}
        )


def test_embed_without_a_name_is_rejected():
    with pytest.raises(InvalidPipelineError, match="missing embed key"):
        normalize_workflow({"nodes": [{"name": "loop", "embed": {"conf": {}}}]})


def test_normalizing_a_spec_with_an_embed_is_a_fixed_point():
    workflow = normalize_workflow(
        {
            "nodes": [
                {"name": "loop", "embed": {"name": "tokenizer", "conf": {"d": " "}}}
            ]
        }
    )
    assert normalize_workflow(workflow) == workflow
