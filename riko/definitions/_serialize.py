# vim: sw=4:ts=4:expandtab
"""
Deterministic serialization of workflow graphs and shape-aware document parsing.

A workflow document (``WorkflowDocument``) is a serialized ``Workflow``. Workflows
serialize to byte-stable documents here. A JSON input in any of the three readable
shapes (a workflow document, a serialized pipe definition, or a serialized
``PipeDag``) is recognized and read into the shorthand workflow mapping a
``Workflow`` is built from.

"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, TypeGuard

import attrs

from riko.base._config import OUTPUT_MODULE
from riko.base._exceptions import InvalidPipelineError
from riko.base._guards import is_listlike, is_mapping, require_mapping
from riko.base._recordutils import serialize_attrs
from riko.base._require_guards import typed_dict_keys
from riko.types._enums import DocumentShape
from riko.types._pipedef import PipeDag, PipeDef, PipeModule, Wire
from riko.types._workflow import PortEdge, RawWorkflow, WorkflowDocument

from ._migrate import parse_pipedag, parse_pipedef
from ._nodes import RikoNode

if TYPE_CHECKING:
    from riko.types._pipedef import PipeLike

    from ._workflow_definition import (
        DocumentLike,
        DocumentMapping,
        Workflow,
        WorkflowLike,
    )

_SHAPE_ERROR = "the document needs 'nodes' or 'modules'"
_WIRE_KEYS = typed_dict_keys(Wire)[0]
_PIPE_MODULE_KEYS = typed_dict_keys(PipeModule)[0]
_UNIQ_PIPEDEF_MODULE_KEYS = frozenset({"emit", "assign", "field", "count"})
_UNIQ_PIPEDAG_MODULE_KEYS = frozenset({"name", "options", "label", "resources"})


class WorkflowEncoder(json.JSONEncoder):
    """Renders the structural and JSON-native value types a workflow carries."""

    def default(self, o: object) -> object:
        if isinstance(o, (RikoNode, PortEdge)):
            result = {"family": o.family, **serialize_attrs(o)}
        elif is_mapping(o):
            result = dict(o)
        elif attrs.has(type(o)):
            result = serialize_attrs(o)
        else:
            result = super().default(o)

        return result


def serialize_workflow(flow: Workflow, *, indent: int | None = 4) -> WorkflowDocument:
    """
    Serializes a workflow into a byte-stable ``WorkflowDocument``.

    Map keys are sorted at every level and node/edge fields use a fixed shape, so the
    same workflow always yields identical bytes.

    Args:

        flow: The ``Workflow`` to serialize.

    Kwargs:

        indent: Number of spaces to indent each nesting level by. Pass ``None`` for the
            compact single-line form.

    Returns:

        The ``WorkflowDocument`` as UTF-8 JSON bytes.

    Raises:

        InvalidPipelineError: If the workflow has a callable node.

    """
    flow.validate_document_nodes()

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


def is_workflowlike(value: object) -> TypeGuard[Workflow | RawWorkflow]:
    """Reports whether ``value`` is a mapping listing ``nodes`` or a ``version``."""
    return is_mapping(value) and bool({"nodes", "version"}.intersection(value))


def _is_pipedag_module(module: object) -> bool:
    """Reports whether ``module`` has a key only a ``PipeDag`` module uses."""
    if is_mapping(module):
        result = bool(_UNIQ_PIPEDAG_MODULE_KEYS.intersection(module))
    else:
        result = False

    return result


def _is_pipedef_module(module: object) -> bool:
    """Reports whether ``module`` has a ``PipeDef``-only key or ``output`` type."""
    if is_mapping(module):
        if not (result := bool(_UNIQ_PIPEDEF_MODULE_KEYS.intersection(module))):
            result = module.get("type") == OUTPUT_MODULE
    else:
        result = False

    return result


def is_pipedef(value: object) -> TypeGuard[PipeDef]:
    """Reports whether ``value`` is a ``PipeDef``."""
    if is_mapping(value) and (modules := value.get("modules")):
        if (wires := value.get("wires")) and is_listlike(wires):
            result = any(is_mapping(w) and _WIRE_KEYS.intersection(w) for w in wires)
        else:
            result = False

        if not result:
            result = is_listlike(modules) and any(filter(_is_pipedef_module, modules))
    else:
        result = False

    return result


def is_pipedag(value: object) -> TypeGuard[PipeDag]:
    """Reports whether ``value`` is a ``PipeDag``."""
    if is_mapping(value) and (modules := value.get("modules")) and is_listlike(modules):
        wires = value.get("wires")
        listed = is_listlike(wires) and any(is_listlike(wire) for wire in wires)
        result = listed or any(filter(_is_pipedag_module, modules))
    else:
        result = False

    return result


def is_pipelike(value: object) -> TypeGuard[PipeLike]:
    """Reports whether ``value`` is a mapping listing at least one module."""
    return (
        is_mapping(value)
        and bool(modules := value.get("modules"))
        and is_listlike(modules)
    )


def _has_pipe_modules(value: PipeLike) -> bool:
    """Reports whether ``value`` lists modules that all have a ``PipeModule``'s keys."""
    result = (is_mapping(m) and _PIPE_MODULE_KEYS <= m.keys() for m in value["modules"])
    return all(result)


def get_document_shape(document: DocumentMapping) -> DocumentShape:
    """
    Detects which of the readable shapes ``document`` is written in.

    Tries each shape in order and returns the first that matches:

    - ``WorkflowDocument`` (``V2``): Mapping containing ``nodes`` or ``version``

    - ``PipeDef`` (``V1``): Mapping containing ``modules`` and either ``src``/``tgt``
      ``wires``, an ``output`` module, or a ``PipeDef``-only module key

    - ``PipeDag`` (``DAG``): Mapping containing ``modules`` and either ``wires``
      written as lists or a ``PipeDag``-only module key

    A mapping of ``modules`` with none of these markers is categorized as a ``PipeDef``
    when it lists at least one module and every module has a ``type``, ``id``, and
    ``conf``. Otherwise it is categorized as a ``PipeDag``.

    Args:

        document: The parsed JSON input.

    Returns:

        The detected :class:`~riko.types._enums.DocumentShape`.

    Raises:

        InvalidPipelineError: If the input lists neither ``nodes`` nor ``modules``.

    """
    if is_workflowlike(document):
        shape = DocumentShape.V2
    elif is_pipedef(document):
        shape = DocumentShape.V1
    elif is_pipedag(document):
        shape = DocumentShape.DAG
    elif is_pipelike(document):
        # The modules only have keys both formats share, so test whether any module
        # is missing a key ``PipeModule`` requires.
        shape = DocumentShape.V1 if _has_pipe_modules(document) else DocumentShape.DAG
    elif "modules" in document:
        shape = DocumentShape.DAG  # An empty or non-list ``modules`` value
    else:
        raise InvalidPipelineError(_SHAPE_ERROR)

    return shape


def require_unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """
    Requires a decoded JSON object's keys to be unique.

    Args:

        pairs: The object's key/value pairs, in document order.

    Returns:

        The object as a dict.

    Raises:

        InvalidPipelineError: If a key appears more than once.

    Examples:

        >>> json.loads('{"a": 1}', object_pairs_hook=require_unique_keys)
        {'a': 1}

    """
    result = dict(pairs)

    if len(result) < len(pairs):
        keys = [key for key, _ in pairs]
        duplicate = next(key for key in keys if keys.count(key) > 1)
        raise InvalidPipelineError(f"duplicate key {duplicate!r} in JSON input")

    return result


def _parse_document(document: DocumentLike) -> DocumentMapping:
    """Decodes a JSON document, or passes a parsed one through, as a mapping."""
    if isinstance(document, (bytes, str)):
        try:
            raw: object = json.loads(document, object_pairs_hook=require_unique_keys)
        except ValueError as e:
            raise InvalidPipelineError(f"malformed JSON input: {e}") from e
    else:
        raw = document

    return require_mapping(raw, "document")


def parse_document(
    document: DocumentLike, *, shape: DocumentShape | None = None
) -> WorkflowLike:
    """
    Parses a JSON input of any readable shape into the workflow mapping it describes.

    Args:

        document: The JSON input as bytes or text, or already parsed.

    Kwargs:

        shape: The shape to read it as. Omit it to detect the shape from the input.

    Returns:

        The shorthand workflow mapping ``Workflow.from_raw`` builds a ``Workflow``
        from.

    Raises:

        InvalidPipelineError: If ``document`` is not valid JSON, is not a mapping, its
            shape cannot be detected, or it does not hold the shape it is read as.

    """
    mapping = _parse_document(document)
    resolved = get_document_shape(mapping) if shape is None else shape

    if resolved is DocumentShape.V2:
        raw = mapping
    elif resolved is DocumentShape.V1:
        raw = parse_pipedef(mapping)
    else:
        raw = parse_pipedag(mapping)

    return raw


__all__ = [
    "WorkflowEncoder",
    "get_document_shape",
    "is_pipedag",
    "is_pipedef",
    "is_workflowlike",
    "parse_document",
    "require_unique_keys",
    "serialize_workflow",
]
