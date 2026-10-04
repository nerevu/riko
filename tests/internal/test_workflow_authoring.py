# vim: sw=4:ts=4:expandtab
"""Guards the ``Raw*`` TypedDicts against drift from the workflow attrs classes."""

from dataclasses import dataclass
from typing import ClassVar

from attrs import fields_dict

from riko.definitions._workflow import (
    ActionNode,
    CacheNode,
    ModuleNode,
    ReadNode,
    SubscribeNode,
    WriteNode,
)
from riko.types._collections import field_names
from riko.types._workflow import Edge as EdgeBase
from riko.types._workflow import Endpoint, RawEdge, RawEndpoint, RawNode

_NODES = (ModuleNode, ReadNode, WriteNode, ActionNode, CacheNode, SubscribeNode)
_NODE_ALIASES = frozenset({"type", "family", "format"})
_EDGE_ALIASES = frozenset({"type", "family"})


def _attrs_fields(*classes) -> set[str]:
    return {name for cls in classes for name in fields_dict(cls)}


def test_raw_node_covers_every_node_field():
    attrs_keys = _attrs_fields(*_NODES)
    raw_keys = set(RawNode.__annotations__)
    assert not (attrs_keys - raw_keys), f"missing: {sorted(attrs_keys - raw_keys)}"
    assert not (raw_keys - attrs_keys - _NODE_ALIASES), (
        f"unknown: {sorted(raw_keys - attrs_keys - _NODE_ALIASES)}"
    )


def test_raw_edge_covers_every_edge_field():
    attrs_keys = _attrs_fields(EdgeBase)
    raw_keys = set(RawEdge.__annotations__)
    assert not (attrs_keys - raw_keys), f"missing: {sorted(attrs_keys - raw_keys)}"
    assert not (raw_keys - attrs_keys - _EDGE_ALIASES), (
        f"unknown: {sorted(raw_keys - attrs_keys - _EDGE_ALIASES)}"
    )


def test_raw_endpoint_covers_every_endpoint_field():
    attrs_keys = _attrs_fields(Endpoint)
    raw_keys = set(RawEndpoint.__annotations__)
    assert attrs_keys == raw_keys


def test_field_names_includes_classvar_for_attrs_and_dataclass():
    @dataclass
    class _Record:
        tag: ClassVar[str] = "point"
        x: int = 0

    assert "family" in field_names(EdgeBase)
    assert "family" in field_names(WriteNode)
    assert field_names(_Record) == frozenset({"tag", "x"})
    assert "family" not in field_names(Endpoint)


def _required_keys(raw) -> set[str]:
    items = raw.__annotations__.items()
    return {key for key, hint in items if "Required[" in str(hint)}


def test_raw_requiredness_matches_contract():
    assert _required_keys(RawNode) == {"name"}
    assert "id" in RawNode.__annotations__
    assert "id" not in _required_keys(RawNode)
    assert _required_keys(RawEndpoint) == {"node"}
    assert _required_keys(RawEdge) == {"source", "target"}
