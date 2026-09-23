# vim: sw=4:ts=4:expandtab
"""Guards the authoring TypedDicts against drift from the canonical attrs classes."""

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
from riko.types._workflow import (
    EdgeAuthoring,
    Endpoint,
    EndpointAuthoring,
    NodeAuthoring,
)

_NODES = (ModuleNode, ReadNode, WriteNode, ActionNode, CacheNode, SubscribeNode)
_NODE_ALIASES = frozenset({"type", "family", "format"})
_EDGE_ALIASES = frozenset({"type", "family"})


def _attrs_fields(*classes) -> set[str]:
    return {name for cls in classes for name in fields_dict(cls)}


def test_node_authoring_covers_every_node_field():
    canonical = _attrs_fields(*_NODES)
    authoring = set(NodeAuthoring.__annotations__)
    assert not (canonical - authoring), f"missing: {sorted(canonical - authoring)}"
    assert not (authoring - canonical - _NODE_ALIASES), (
        f"unknown: {sorted(authoring - canonical - _NODE_ALIASES)}"
    )


def test_edge_authoring_covers_every_edge_field():
    canonical = _attrs_fields(EdgeBase)
    authoring = set(EdgeAuthoring.__annotations__)
    assert not (canonical - authoring), f"missing: {sorted(canonical - authoring)}"
    assert not (authoring - canonical - _EDGE_ALIASES), (
        f"unknown: {sorted(authoring - canonical - _EDGE_ALIASES)}"
    )


def test_endpoint_authoring_covers_every_endpoint_field():
    canonical = _attrs_fields(Endpoint)
    authoring = set(EndpointAuthoring.__annotations__)
    assert canonical == authoring


def test_field_names_includes_classvar_for_attrs_and_dataclass():
    @dataclass
    class _Record:
        tag: ClassVar[str] = "point"
        x: int = 0

    assert "family" in field_names(EdgeBase)
    assert "family" in field_names(WriteNode)
    assert field_names(_Record) == frozenset({"tag", "x"})
    assert "family" not in field_names(Endpoint)


def _required_keys(typed_dict) -> set[str]:
    return {
        key
        for key, hint in typed_dict.__annotations__.items()
        if "Required[" in str(hint)
    }


def test_authoring_requiredness_matches_contract():
    assert _required_keys(NodeAuthoring) == {"name"}
    assert "id" in NodeAuthoring.__annotations__
    assert "id" not in _required_keys(NodeAuthoring)
    assert _required_keys(EndpointAuthoring) == {"node"}
    assert _required_keys(EdgeAuthoring) == {"source", "target"}
