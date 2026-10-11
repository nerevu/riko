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
from dataclasses import is_dataclass
from enum import Enum
from typing import Any

import attrs

from riko.base.exceptions import InvalidPipelineError
from riko.definitions._workflow import Node, Workflow
from riko.types._collections import serialize_attrs, serialize_dataclass
from riko.types._guards import is_mapping
from riko.types._workflow import Edge, WorkflowDocument

from ._normalize import normalize_workflow


class WorkflowEncoder(json.JSONEncoder):
    """Renders the structural and JSON-native value types a workflow carries."""

    def default(self, o: object) -> Any:
        if isinstance(o, Workflow):
            result = serialize_attrs(o, "edges")
        elif isinstance(o, (Node, Edge)):
            result = {"family": o.family, **serialize_attrs(o)}
        elif is_mapping(o):
            result = dict(o)
        elif attrs.has(type(o)):
            result = serialize_attrs(o)
        elif is_dataclass(o):
            result = serialize_dataclass(o)
        elif isinstance(o, tuple):
            result = list(o)
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

    Raises:

        InvalidPipelineError: If ``document`` is not valid JSON or does not describe a
            workflow.

    Examples:

        >>> from json import dumps
        >>>
        >>> document = dumps({"nodes": [{"name": "fetch"}]})
        >>> parse_document(document).nodes["fetch-1"].name
        'fetch'

    """
    try:
        raw = json.loads(document)
    except ValueError as e:
        raise InvalidPipelineError(f"malformed WorkflowDocument: {e}") from e

    return normalize_workflow(raw)


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

        indent: Number of spaces to indent each nesting level by. Pass ``None`` for the
            compact single-line form.

    Returns:

        The ``WorkflowDocument`` as UTF-8 JSON bytes.

    Examples:

        >>> from riko.ext import normalize_workflow
        >>>
        >>> workflow = normalize_workflow({"nodes": [{"name": "fetch"}]})
        >>> document = serialize_workflow(workflow).decode("utf-8")
        >>> document.splitlines()[1]
        '    "edges": [],'
        >>> serialize_workflow(workflow, indent=None)
        b'{"edges":[],"nodes":{"fetch-1":{"family":"module","id":"fetch-1",...ut"}},"version":"2"}'

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
