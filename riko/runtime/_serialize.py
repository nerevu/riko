# vim: sw=4:ts=4:expandtab
"""
Deterministic serialization and parsing of workflow documents.

A workflow document is a serialized ``Workflow``. ``serialize_workflow`` emits a
byte-stable ``WorkflowDocument``, and ``parse_document`` reconstructs a ``Workflow``
from one by reusing the shared normalization boundary. A ``PipeDef`` becomes a
``Workflow`` through ``migrate_v1_to_v2`` before it is serialized.

Examples:

    Basic usage::

        >>> from riko.ext import normalize_workflow, parse_document, serialize_workflow
        >>>
        >>> workflow = normalize_workflow({"nodes": [{"name": "fetch"}]})
        >>> json = serialize_workflow(workflow)
        >>> parse_document(json) == workflow
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

from riko.definitions._workflow import Node, Workflow
from riko.types._workflow import Edge, WorkflowDocument

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
    """Renders the structural and JSON-native value types a workflow carries."""

    def default(self, o: object) -> Any:
        if isinstance(o, Workflow):
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


def parse_document(document: WorkflowDocument | str) -> Workflow:
    """
    Parses a ``WorkflowDocument`` into a ``Workflow``.

    Reuses the shared normalization boundary, so a ``WorkflowDocument`` round-trips
    back to an equal ``Workflow``. Structural validity beyond reconstruction stays
    with the separate validation step.

    Args:

        document: The ``WorkflowDocument`` as bytes or text.

    Returns:

        The reconstructed :class:`~riko.definitions._workflow.Workflow`.

    Examples:

        >>> from json import dumps
        >>>
        >>> document = dumps({"nodes": [{"name": "fetch"}]})
        >>> parse_document(document).nodes["fetch-1"].name
        'fetch'

    """
    return normalize_workflow(json.loads(document))


def serialize_workflow(
    workflow: Workflow, *, indent: int | None = 4
) -> WorkflowDocument:
    """
    Serializes a ``Workflow`` into a byte-stable ``WorkflowDocument``.

    Map keys are sorted at every level and node/edge fields use a fixed shape, so the
    same workflow always yields identical bytes for golden-fixture comparison. Edge
    order follows the workflow; semantic wiring lives in the endpoints, not the array
    order. The default is the readable indented form committed files are stored in.

    Args:

        workflow: The :class:`~riko.definitions._workflow.Workflow` to serialize.
        indent: Number of spaces to indent each nesting level by. The readable form
            ends with a trailing newline; pass ``None`` for the compact single-line
            form.

    Returns:

        The ``WorkflowDocument`` as UTF-8 JSON bytes.

    Examples:

        >>> from riko.ext import normalize_workflow
        >>>
        >>> workflow = normalize_workflow({"nodes": [{"name": "fetch"}]})
        >>> document = serialize_workflow(workflow).decode("utf-8")
        >>> document.splitlines()[1]
        '    "edges": [],'
        >>> document.endswith("\\n")
        True

        Compact form::

            >>> serialize_workflow(workflow, indent=None)
            b'{"edges":[],"nodes":{"fetch-1":{"id":"fetch-1","name":"fetch","type":"module"}},"outputs":{"default":{"node":"fetch-1","port":"out"}},"version":"2"}'

    """
    if indent is None:
        separators = (",", ":")
        suffix = ""
    else:
        separators = None
        suffix = "\n"

    dumped = json.dumps(
        workflow,
        cls=WorkflowEncoder,
        sort_keys=True,
        indent=indent,
        separators=separators,
        ensure_ascii=False,
        allow_nan=False,
    )
    return (dumped + suffix).encode("utf-8")


__all__ = ["parse_document", "serialize_workflow"]
