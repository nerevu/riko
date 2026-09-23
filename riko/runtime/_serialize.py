# vim: sw=4:ts=4:expandtab
"""
Deterministic canonical serialization and parsing of Workflow v2 specs.

``serialize_workflow`` emits a byte-stable canonical JSON document, and
``parse_workflow`` reconstructs a ``WorkflowSpec`` from it by reusing the shared
normalization boundary. Serialization emits v2 only. v1 documents are converted to v2
through ``migrate_v1_to_v2`` before it is ever serialized.

Examples:

    Basic usage::

        >>> from riko.ext import normalize_workflow, parse_workflow, serialize_workflow
        >>>
        >>> spec = normalize_workflow({"nodes": [{"name": "fetch"}]})
        >>> json = serialize_workflow(spec)
        >>> parse_workflow(json) == spec
        True

"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from dataclasses import fields, is_dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

import attrs
from attrs import AttrsInstance

from riko.definitions._workflow import Node, WorkflowSpec
from riko.types._workflow import Edge

from ._normalize import normalize_workflow

if TYPE_CHECKING:
    from _typeshed import DataclassInstance


def _has_value(_: object = None, value: object = None) -> bool:
    return not (value is None or isinstance(value, (Mapping, tuple)) and not value)


def _serialize_dataclass(
    instance: DataclassInstance | type[DataclassInstance], *keep_fields: str
) -> Iterator[tuple[str, object]]:
    keep = frozenset(keep_fields)

    for field in fields(instance):
        value = getattr(instance, field.name)

        if _has_value(value=value) or field.name in keep:
            yield (field.name, value)


def _serialize_attrs(instance: AttrsInstance, *keep_fields: str) -> dict[str, object]:
    keep = frozenset(keep_fields)
    filterer = lambda field, value: _has_value(field, value) or field.name in keep
    return attrs.asdict(instance, recurse=False, filter=filterer)


class WorkflowEncoder(json.JSONEncoder):
    """Renders the structural and JSON-native value types a canonical spec carries."""

    def default(self, o: object) -> Any:
        if isinstance(o, WorkflowSpec):
            result = _serialize_attrs(o, "edges")
        elif isinstance(o, (Node, Edge)):
            result = {"type": o.family, **_serialize_attrs(o)}
        elif attrs.has(type(o)):
            result = attrs.asdict(o, recurse=False, filter=_has_value)
        elif is_dataclass(o):
            result = dict(_serialize_dataclass(o))
        elif isinstance(o, tuple):
            result = list(o)
        elif isinstance(o, Mapping):
            result = dict(o)
        elif isinstance(o, Enum):
            result = o.value
        else:
            result = super().default(o)

        return result


def parse_workflow(data: bytes | str) -> WorkflowSpec:
    """
    Parses a canonical Workflow v2 JSON document into a spec.

    Reuses the shared normalization boundary, so a serialized document round-trips back
    to an equal spec. Structural validity beyond reconstruction stays with the separate
    validation step.

    Args:

        data: The canonical JSON document as bytes or text.

    Returns:

        The reconstructed :class:`~riko.definitions._workflow.WorkflowSpec`.

    Examples:
        >>> from json import dumps
        >>>
        >>> json = json.dumps({"nodes": [{"name": "fetch"}]})
        >>> parse_workflow(json).nodes["fetch-1"].name
        'fetch'

    """
    return normalize_workflow(json.loads(data))


def serialize_workflow(spec: WorkflowSpec) -> bytes:
    """
    Serializes a canonical workflow spec into byte-stable canonical JSON.

    Map keys are sorted at every level and node/edge fields use a fixed shape, so the
    same spec always yields identical bytes for golden-fixture comparison. Edge order
    follows the spec; semantic wiring lives in the endpoints, not the array order.

    Args:

        spec: The canonical :class:`~riko.definitions._workflow.WorkflowSpec`.

    Returns:

        The canonical UTF-8 JSON document as bytes.

    Examples:

        >>> from riko.ext import normalize_workflow
        >>>
        >>> spec = normalize_workflow({"nodes": [{"name": "fetch"}]})
        >>> serialize_workflow(spec)
        b'{"edges":[],"nodes":{"fetch-1":{"id":"fetch-1","name":"fetch","type":"module"}},"outputs":{"default":{"node":"fetch-1","port":"out"}},"version":"2"}'

    """
    dumped = json.dumps(
        spec,
        cls=WorkflowEncoder,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return dumped.encode("utf-8")


__all__ = ["parse_workflow", "serialize_workflow"]
