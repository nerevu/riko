# vim: sw=4:ts=4:expandtab
"""
Tests for the ``migrate_v1_to_v2`` one-shot legacy migration boundary.

These cover the v1-specific translation before the shared normalization pass: legacy
port mapping, ``src``/``tgt`` wire translation, the ``write`` module becoming a
``WriteNode``, terminal ``_OUTPUT`` pseudo-node consumption into ``outputs``, orphan
retention, the migration warning, and that migrated output carries no v1-only structure.
"""

import pytest

from riko.base.exceptions import InvalidPipelineError
from riko.definitions._workflow import ModuleNode, WriteNode
from riko.definitions._write import WriteMode
from riko.ext import migrate_v1_to_v2
from riko.types._enums import Backends, Formats
from riko.types._workflow import Endpoint


def _wire(wid, src_mod, tgt_mod, src_port="_OUTPUT", tgt_port="_INPUT"):
    return {
        "id": wid,
        "src": {"id": src_port, "moduleid": src_mod},
        "tgt": {"id": tgt_port, "moduleid": tgt_mod},
    }


def test_terminal_output_becomes_default_output():
    workflow = migrate_v1_to_v2(
        {
            "modules": [
                {"id": "sw-1", "type": "fetch", "conf": {}},
                {"id": "_OUTPUT", "type": "output", "conf": {}},
            ],
            "wires": [_wire("_w1", "sw-1", "_OUTPUT")],
        }
    )
    assert list(workflow.nodes) == ["sw-1"]
    assert workflow.outputs["default"] == Endpoint("sw-1", "out")
    assert workflow.edges == ()


def test_legacy_ports_map_to_canonical_grammar():
    workflow = migrate_v1_to_v2(
        {
            "modules": [
                {"id": "a", "type": "fetch", "conf": {}},
                {"id": "b", "type": "union", "conf": {}},
            ],
            "wires": [_wire("_w1", "a", "b", src_port="_OUTPUT", tgt_port="_OTHER1")],
        }
    )
    edge = workflow.edges[0]
    assert edge.source == Endpoint("a", "out")
    assert edge.target == Endpoint("b", "in:1")


def test_null_wire_ports_take_the_default_ports():
    workflow = migrate_v1_to_v2(
        {
            "modules": [
                {"id": "a", "type": "fetch", "conf": {}},
                {"id": "b", "type": "union", "conf": {}},
            ],
            "wires": [
                {
                    "id": "_w1",
                    "src": {"id": None, "moduleid": "a"},
                    "tgt": {"id": None, "moduleid": "b"},
                }
            ],
        }
    )
    edge = workflow.edges[0]
    assert edge.source == Endpoint("a", "out")
    assert edge.target == Endpoint("b", "in")


def test_named_secondary_port_canonicalized():
    workflow = migrate_v1_to_v2(
        {
            "modules": [
                {"id": "a", "type": "count", "conf": {}},
                {"id": "b", "type": "truncate", "conf": {}},
            ],
            "wires": [_wire("_w1", "a", "b", tgt_port="count")],
        }
    )
    assert workflow.edges[0].target == Endpoint("b", "in:count")


def test_write_module_becomes_write_node():
    workflow = migrate_v1_to_v2(
        {
            "modules": [
                {"id": "sw-1", "type": "fetch", "conf": {}},
                {
                    "id": "sw-2",
                    "type": "write",
                    "conf": {"dest": "out.json", "fmt": "json"},
                },
            ],
            "wires": [_wire("_w1", "sw-1", "sw-2")],
        }
    )
    node = workflow.nodes["sw-2"]
    assert isinstance(node, WriteNode)
    assert node.backend is Backends.FILE
    assert node.fmt is Formats.JSON


def test_write_module_preserves_destination_mode_and_keys():
    workflow = migrate_v1_to_v2(
        {
            "modules": [
                {
                    "id": "w",
                    "type": "write",
                    "conf": {
                        "dest": "out.jsonl",
                        "fmt": "jsonl",
                        "mode": "append",
                        "keys": "id",
                    },
                }
            ]
        }
    )
    node = workflow.nodes["w"]
    assert isinstance(node, WriteNode)
    assert node.dest == "out.jsonl"
    assert node.fmt is Formats.JSONL
    assert node.mode is WriteMode.APPEND
    assert node.keys == ("id",)


@pytest.mark.parametrize(
    ("v1_mode", "canonical"),
    [
        ("wb+", WriteMode.REPLACE),
        ("w", WriteMode.REPLACE),
        ("ab", WriteMode.APPEND),
        ("a+", WriteMode.APPEND),
    ],
)
def test_v1_file_open_mode_translates(v1_mode, canonical):
    workflow = migrate_v1_to_v2(
        {
            "modules": [
                {
                    "id": "w",
                    "type": "write",
                    "conf": {"dest": "o.json", "mode": v1_mode},
                }
            ]
        }
    )
    node = workflow.nodes["w"]
    assert isinstance(node, WriteNode)
    assert node.mode is canonical


def test_unmappable_v1_write_mode_rejected():
    with pytest.raises(InvalidPipelineError, match="write mode"):
        migrate_v1_to_v2(
            {
                "modules": [
                    {"id": "w", "type": "write", "conf": {"dest": "o", "mode": "rb"}}
                ]
            }
        )


def test_v1_write_wrapper_option_rejected():
    with pytest.raises(InvalidPipelineError, match="write option"):
        migrate_v1_to_v2(
            {
                "modules": [
                    {"id": "w", "type": "write", "conf": {"dest": "o"}, "emit": True}
                ]
            }
        )


def test_v1_write_unknown_conf_key_rejected():
    with pytest.raises(InvalidPipelineError, match="write option"):
        migrate_v1_to_v2(
            {
                "modules": [
                    {"id": "w", "type": "write", "conf": {"dest": "o", "bogus": 1}}
                ]
            }
        )


def test_write_module_without_format_defaults_to_none():
    workflow = migrate_v1_to_v2(
        {"modules": [{"id": "w", "type": "write", "conf": {"dest": "out.dat"}}]}
    )
    node = workflow.nodes["w"]
    assert isinstance(node, WriteNode)
    assert node.backend is Backends.FILE
    assert node.fmt is None


def test_module_extras_fold_into_conf():
    workflow = migrate_v1_to_v2(
        {"modules": [{"id": "c", "type": "count", "conf": {"x": 1}, "bogus": True}]}
    )
    node = workflow.nodes["c"]
    assert isinstance(node, ModuleNode)
    assert node.conf == {"bogus": True, "x": 1}


def test_module_call_options_become_node_options():
    workflow = migrate_v1_to_v2(
        {
            "modules": [
                {
                    "id": "c",
                    "type": "count",
                    "conf": {"x": 1},
                    "emit": True,
                    "assign": "total",
                    "field": "title",
                    "count": "first",
                }
            ]
        }
    )
    node = workflow.nodes["c"]
    assert isinstance(node, ModuleNode)
    assert node.conf == {"x": 1}
    assert node.options == {
        "emit": True,
        "assign": "total",
        "field": "title",
        "count": "first",
    }


def test_call_option_does_not_collide_with_a_same_named_conf_key():
    workflow = migrate_v1_to_v2(
        {
            "modules": [
                {
                    "id": "t",
                    "type": "truncate",
                    "conf": {"count": {"value": 3}},
                    "count": "first",
                }
            ]
        }
    )
    node = workflow.nodes["t"]
    assert isinstance(node, ModuleNode)
    assert node.conf == {"count": {"value": 3}}
    assert node.options == {"count": "first"}


def test_loop_embed_and_its_configuration_become_the_node_embed():
    workflow = migrate_v1_to_v2(
        {
            "modules": [
                {
                    "id": "sw-2",
                    "type": "loop",
                    "embed": {"id": "sw-3", "type": "tokenizer"},
                    "conf": {"delimiter": {"value": ","}},
                    "count": "first",
                    "assign": "words",
                    "emit": True,
                    "field": "title",
                }
            ]
        }
    )
    node = workflow.nodes["sw-2"]
    assert isinstance(node, ModuleNode)
    assert node.conf == {}
    assert node.embed == {"name": "tokenizer", "conf": {"delimiter": {"value": ","}}}
    assert node.options == {
        "count": "first",
        "assign": "words",
        "emit": True,
        "field": "title",
    }


def test_loop_embedded_subpipe_keeps_its_prefixed_name():
    workflow = migrate_v1_to_v2(
        {
            "modules": [
                {
                    "id": "sw-2",
                    "type": "loop",
                    "embed": {"id": "sw-3", "type": "pipe:shout"},
                    "conf": {},
                }
            ]
        }
    )
    node = workflow.nodes["sw-2"]
    assert isinstance(node, ModuleNode)
    assert node.conf == {}
    assert node.embed == {"name": "pipe:shout", "conf": {}}


@pytest.mark.parametrize(
    ("v1_port", "canonical"),
    [("1_URL", "in:_1_URL"), ("PARAM_5_value", "in:PARAM_5_value")],
)
def test_wire_target_port_is_sanitized_like_a_module_terminal(v1_port, canonical):
    workflow = migrate_v1_to_v2(
        {
            "modules": [
                {"id": "a", "type": "fetch", "conf": {}},
                {"id": "b", "type": "urlbuilder", "conf": {}},
            ],
            "wires": [_wire("_w1", "a", "b", tgt_port=v1_port)],
        }
    )
    assert workflow.edges[0].target == Endpoint("b", canonical)


def test_uppercase_conf_keys_are_lowered():
    workflow = migrate_v1_to_v2(
        {"modules": [{"id": "f", "type": "fetch", "conf": {"URL": {"value": "x"}}}]}
    )
    node = workflow.nodes["f"]
    assert isinstance(node, ModuleNode)
    assert node.conf == {"url": {"value": "x"}}


def test_orphan_module_is_retained_not_erased():
    workflow = migrate_v1_to_v2(
        {
            "modules": [
                {"id": "a", "type": "fetch", "conf": {}},
                {"id": "orphan", "type": "count", "conf": {}},
                {"id": "_OUTPUT", "type": "output", "conf": {}},
            ],
            "wires": [_wire("_w1", "a", "_OUTPUT")],
        }
    )
    assert "orphan" in workflow.nodes


def test_omitted_output_node_defaults_to_lone_leaf():
    workflow = migrate_v1_to_v2(
        {
            "modules": [
                {"id": "a", "type": "fetch", "conf": {}},
                {"id": "b", "type": "filter", "conf": {}},
            ],
            "wires": [_wire("_w1", "a", "b")],
        }
    )
    assert workflow.outputs == {"default": Endpoint("b", "out")}


def test_migration_warns(caplog):
    migrate_v1_to_v2({"modules": [{"id": "a", "type": "fetch", "conf": {}}]})
    assert any("PipeDef to Workflow" in record.message for record in caplog.records)


def test_migrated_spec_carries_no_v1_structure():
    workflow = migrate_v1_to_v2(
        {
            "modules": [
                {"id": "sw-1", "type": "fetch", "conf": {}},
                {"id": "_OUTPUT", "type": "output", "conf": {}},
            ],
            "wires": [_wire("_w1", "sw-1", "_OUTPUT")],
        }
    )
    assert "_OUTPUT" not in workflow.nodes
    assert workflow.version == "2"
    ports = {edge.source.port for edge in workflow.edges}
    ports |= {edge.target.port for edge in workflow.edges}
    assert not any(port.startswith("_") for port in ports)


def test_malformed_module_raises():
    with pytest.raises(InvalidPipelineError, match="module 'type'"):
        migrate_v1_to_v2({"modules": [{"id": "a", "conf": {}}]})


def test_non_mapping_pipe_def_raises():
    with pytest.raises(InvalidPipelineError, match="pipe definition"):
        migrate_v1_to_v2(["not", "a", "mapping"])  # pyright: ignore[reportArgumentType]
