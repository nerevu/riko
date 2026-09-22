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
    spec = migrate_v1_to_v2(
        {
            "modules": [
                {"id": "sw-1", "type": "fetch", "conf": {}},
                {"id": "_OUTPUT", "type": "output", "conf": {}},
            ],
            "wires": [_wire("_w1", "sw-1", "_OUTPUT")],
        }
    )
    assert list(spec.nodes) == ["sw-1"]
    assert spec.outputs["default"] == Endpoint("sw-1", "out")
    assert spec.edges == ()


def test_legacy_ports_map_to_canonical_grammar():
    spec = migrate_v1_to_v2(
        {
            "modules": [
                {"id": "a", "type": "fetch", "conf": {}},
                {"id": "b", "type": "union", "conf": {}},
            ],
            "wires": [_wire("_w1", "a", "b", src_port="_OUTPUT", tgt_port="_OTHER1")],
        }
    )
    edge = spec.edges[0]
    assert edge.source == Endpoint("a", "out")
    assert edge.target == Endpoint("b", "in:1")


def test_named_secondary_port_preserved():
    spec = migrate_v1_to_v2(
        {
            "modules": [
                {"id": "a", "type": "count", "conf": {}},
                {"id": "b", "type": "truncate", "conf": {}},
            ],
            "wires": [_wire("_w1", "a", "b", tgt_port="count")],
        }
    )
    assert spec.edges[0].target == Endpoint("b", "count")


def test_write_module_becomes_write_node():
    spec = migrate_v1_to_v2(
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
    node = spec.nodes["sw-2"]
    assert isinstance(node, WriteNode)
    assert node.backend is Backends.FILE
    assert node.fmt is Formats.JSON


def test_write_module_without_format_defaults_to_none():
    spec = migrate_v1_to_v2(
        {"modules": [{"id": "w", "type": "write", "conf": {"dest": "out.dat"}}]}
    )
    node = spec.nodes["w"]
    assert isinstance(node, WriteNode)
    assert node.backend is Backends.FILE
    assert node.fmt is None


def test_module_extras_fold_into_conf():
    spec = migrate_v1_to_v2(
        {"modules": [{"id": "c", "type": "count", "conf": {"x": 1}, "emit": True}]}
    )
    node = spec.nodes["c"]
    assert isinstance(node, ModuleNode)
    assert node.conf == {"emit": True, "x": 1}


def test_uppercase_conf_keys_are_lowered():
    spec = migrate_v1_to_v2(
        {"modules": [{"id": "f", "type": "fetch", "conf": {"URL": {"value": "x"}}}]}
    )
    node = spec.nodes["f"]
    assert isinstance(node, ModuleNode)
    assert node.conf == {"url": {"value": "x"}}


def test_orphan_module_is_retained_not_erased():
    spec = migrate_v1_to_v2(
        {
            "modules": [
                {"id": "a", "type": "fetch", "conf": {}},
                {"id": "orphan", "type": "count", "conf": {}},
                {"id": "_OUTPUT", "type": "output", "conf": {}},
            ],
            "wires": [_wire("_w1", "a", "_OUTPUT")],
        }
    )
    assert "orphan" in spec.nodes


def test_omitted_output_node_defaults_to_lone_leaf():
    spec = migrate_v1_to_v2(
        {
            "modules": [
                {"id": "a", "type": "fetch", "conf": {}},
                {"id": "b", "type": "filter", "conf": {}},
            ],
            "wires": [_wire("_w1", "a", "b")],
        }
    )
    assert spec.outputs == {"default": Endpoint("b", "out")}


def test_migration_warns(caplog):
    migrate_v1_to_v2({"modules": [{"id": "a", "type": "fetch", "conf": {}}]})
    assert any("v1" in record.message for record in caplog.records)


def test_migrated_spec_carries_no_v1_structure():
    spec = migrate_v1_to_v2(
        {
            "modules": [
                {"id": "sw-1", "type": "fetch", "conf": {}},
                {"id": "_OUTPUT", "type": "output", "conf": {}},
            ],
            "wires": [_wire("_w1", "sw-1", "_OUTPUT")],
        }
    )
    assert "_OUTPUT" not in spec.nodes
    assert spec.version == "2"
    ports = {edge.source.port for edge in spec.edges}
    ports |= {edge.target.port for edge in spec.edges}
    assert not any(port.startswith("_") for port in ports)


def test_malformed_module_raises():
    with pytest.raises(InvalidPipelineError, match="module 'type'"):
        migrate_v1_to_v2({"modules": [{"id": "a", "conf": {}}]})


def test_non_mapping_pipe_def_raises():
    with pytest.raises(InvalidPipelineError, match="pipe definition"):
        migrate_v1_to_v2(["not", "a", "mapping"])  # pyright: ignore[reportArgumentType]
