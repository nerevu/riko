# vim: sw=4:ts=4:expandtab
"""
Deterministic serialization of workflow graphs and shape-aware document parsing.

A workflow document (``WorkflowDocument``) is a serialized ``Workflow``. Workflows
serialize to byte-stable documents here. A JSON input in any of the three readable
shapes (a workflow document, a serialized pipe definition, or a serialized
``PipeDag``) is recognized and read into the field values a ``Workflow`` is built
from.

"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, TypeGuard

import attrs

from riko.base._config import OUTPUT_MODULE
from riko.base.exceptions import InvalidPipelineError
from riko.types._collections import serialize_attrs
from riko.types._enums import DocumentShape
from riko.types._guards import is_listlike, is_mapping, require_mapping
from riko.types._workflow import Edge, RawWorkflow, WorkflowDocument

from ._migrate import migrate_pipe_def, parse_dag_graph
from ._nodes import Node
from ._normalize import WorkflowFields, build_workflow_fields

if TYPE_CHECKING:
    from collections.abc import Mapping

    from riko.types._compiler import PipeDag, PipeDefLike

    from ._workflow import Workflow

_SHAPE_ERROR = "the input needs 'nodes' or 'modules'"
_WIRE_KEYS = frozenset({"src", "tgt"})


class WorkflowEncoder(json.JSONEncoder):
    """Renders the structural and JSON-native value types a workflow carries."""

    def default(self, o: object) -> Any:
        if isinstance(o, (Node, Edge)):
            result = {"family": o.family, **serialize_attrs(o)}
        elif is_mapping(o):
            result = dict(o)
        elif attrs.has(type(o)):
            result = serialize_attrs(o)
        else:
            result = super().default(o)

        return result


def serialize_graph(flow: Workflow, *, indent: int | None = 4) -> WorkflowDocument:
    """
    Serializes a workflow into a byte-stable ``WorkflowDocument``.

    Map keys are sorted at every level and node/edge fields use a fixed shape, so the
    same workflow always yields identical bytes.

    Args:

        flow: The ``Workflow`` to serialize.

        indent: Number of spaces to indent each nesting level by. Pass ``None`` for the
            compact single-line form.

    Returns:

        The ``WorkflowDocument`` as UTF-8 JSON bytes.

    """
    if indent is None:
        separators = (",", ":")
        suffix = ""
    else:
        separators = None
        suffix = "\n"

    dumped = json.dumps(
        serialize_attrs(flow, "edges"),
        cls=WorkflowEncoder,
        sort_keys=True,
        indent=indent,
        separators=separators,
        ensure_ascii=False,
        allow_nan=False,
    )
    return (dumped + suffix).encode("utf-8")


def is_raw_workflow(value: object) -> TypeGuard[RawWorkflow | Mapping[str, object]]:
    """Reports whether ``value`` is a mapping listing ``nodes`` or a ``version``."""
    return is_mapping(value) and bool({"nodes", "version"}.intersection(value))


def is_pipedeflike(value: object) -> TypeGuard[PipeDefLike]:
    """Reports whether ``value`` is a ``PipeDef``."""
    if is_mapping(value) and not is_raw_workflow(value) and "modules" in value:
        wires = value.get("wires")
        modules = value.get("modules")

        wired = is_listlike(wires) and any(
            is_mapping(wire) and not _WIRE_KEYS.isdisjoint(wire) for wire in wires
        )
        terminal = is_listlike(modules) and any(
            is_mapping(module) and module.get("type") == OUTPUT_MODULE
            for module in modules
        )
        result = wired or terminal
    else:
        result = False

    return result


def is_pipedag(value: object) -> TypeGuard[PipeDag]:
    """Reports whether ``value`` is a ``PipeDag``."""
    possible = is_mapping(value) and not is_raw_workflow(value) and "modules" in value
    return possible and not is_pipedeflike(value)


def get_document_shape(document: Mapping[str, object]) -> DocumentShape:
    """
    Detects which of the readable shapes ``document`` is written in.

    A mapping listing ``nodes`` or declaring the workflow format version it targets
    is a workflow document. One listing ``modules`` is either a ``PipeDef``,
    recognised by its wire mappings and its ``output`` node, or a ``PipeDag``.

    Args:

        document: The parsed JSON input.

    Returns:

        The detected :class:`~riko.types._enums.DocumentShape`.

    Raises:

        InvalidPipelineError: If the input lists neither ``nodes`` nor ``modules``.

    """
    if is_raw_workflow(document):
        shape = DocumentShape.V2
    elif is_pipedeflike(document):
        shape = DocumentShape.V1
    elif is_pipedag(document):
        shape = DocumentShape.DAG
    else:
        raise InvalidPipelineError(_SHAPE_ERROR)

    return shape


def _parse_mapping(document: object) -> Mapping[str, object]:
    """Decodes a JSON document, or passes a parsed one through, as a mapping."""
    if isinstance(document, (bytes, str)):
        try:
            raw: object = json.loads(document)
        except ValueError as e:
            raise InvalidPipelineError(f"malformed JSON input: {e}") from e
    else:
        raw = document

    return require_mapping(raw, "workflow")


def parse_graph(
    document: WorkflowDocument | str | Mapping[str, object],
    *,
    shape: DocumentShape | None = None,
) -> WorkflowFields:
    """
    Parses a JSON input of any readable shape into ``Workflow`` field values.

    Args:

        document: The JSON input as bytes or text, or already parsed.

        shape: The shape to read it as. Omit it to detect the shape from the input.

    Returns:

        The keyword arguments that build the normalized ``Workflow``.

    Raises:

        InvalidPipelineError: If ``document`` is not valid JSON, is not a mapping, its
            shape cannot be detected, or it does not hold the shape it is read as.

    """
    mapping = _parse_mapping(document)
    resolved = get_document_shape(mapping) if shape is None else shape

    if resolved is DocumentShape.V2:
        fields = build_workflow_fields(mapping)
    elif resolved is DocumentShape.V1:
        fields = build_workflow_fields(migrate_pipe_def(mapping))
    elif is_pipedag(mapping):
        fields = build_workflow_fields(parse_dag_graph(mapping))
    else:
        raise InvalidPipelineError("the input is not a serialized bare-bones DAG")

    return fields


__all__ = [
    "WorkflowEncoder",
    "get_document_shape",
    "is_pipedag",
    "is_pipedeflike",
    "is_raw_workflow",
    "parse_graph",
    "serialize_graph",
]
