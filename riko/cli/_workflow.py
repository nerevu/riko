# vim: sw=4:ts=4:expandtab
"""
Shared JSON input front door for the riko console scripts.

The console scripts read three JSON shapes: a workflow document (``WorkflowDocument``
aka a serialized ``Workflow``), a serialized pipe definition (``PipeDef``), and a
serialized ``PipeDag``. Every command reads its input from here. This module decides
which shape the input is written in, which loader turns it into a validated
``Workflow``, and which commands accept a ``PipeDef`` or ``PipeDag`` at all.

``build-workflow`` is the most lenient. The commands that run or generate code take a
``WorkflowDocument`` only.

Examples:

    Basic usage::

        >>> from riko.cli._workflow import get_document_format, normalize_document
        >>>
        >>> dag = {"modules": [{"type": "forever"}, {"type": "truncate"}]}
        >>> get_document_format(dag).value
        'dag'
        >>> list(normalize_document(dag).nodes)
        ['sw-1', 'sw-2']

"""

from __future__ import annotations

import sys
from enum import StrEnum
from json import loads
from pathlib import Path
from typing import TYPE_CHECKING, TypeGuard

from riko.base._config import OUTPUT_MODULE
from riko.base._logging import logger
from riko.base.exceptions import InvalidPipelineError
from riko.runtime._migrate import migrate_v1_to_v2, parse_dag
from riko.runtime._normalize import normalize_workflow
from riko.types._guards import is_listlike, is_mapping

if TYPE_CHECKING:
    from riko.definitions._workflow import Workflow, WorkflowLike
    from riko.types._compiler import PipeDag, PipeDefLike

_SHAPE_ERROR = "the input needs 'nodes' or 'modules'"
_WIRE_KEYS = frozenset({"src", "tgt"})
_OTHER_FORMS = {
    "dag": "a serialized bare-bones DAG",
    "v1": "a serialized pipe definition",
}

type DocumentMapping = WorkflowLike | PipeDefLike | PipeDag


class DocumentFormat(StrEnum):
    """The JSON input shapes the console scripts read."""

    DAG = "dag"
    V1 = "v1"
    V2 = "v2"


def read_document(path: Path | str) -> tuple[DocumentMapping | None, str]:
    """
    Reads a JSON input from ``path``, or from stdin when it is ``-``.

    An unreadable, undecodable, or malformed input is reported as a warning and leaves
    the caller to decide what absent input means for it.

    Args:

        path: The path to read, or ``-`` for standard input.

    Returns:

        The parsed ``WorkflowLike``, ``PipeDef``, or ``PipeDag`` mapping, or ``None``
        when it could not be read; and the name it is known by: the file stem, or
        ``anonymous`` for standard input.

    Examples:

        >>> read_document("no-such-flow.json")
        (None, 'no-such-flow')

    """
    if path == "-":
        name = "anonymous"
        text = sys.stdin.read()
    else:
        path = Path(path)
        name = path.stem
        text = None

        try:
            text = path.read_text(encoding="utf-8")
        except OSError as e:
            logger.warning("Unable to read input file: %s", e)
        except ValueError as e:
            logger.warning("Unable to decode input file: %s", e)

    document = None

    if text is not None:
        try:
            document = loads(text)
        except ValueError as e:
            logger.warning("Unable to parse input: %s", e)

    return document, name


def is_workflowlike(value: object) -> TypeGuard[WorkflowLike]:
    """Reports whether ``value`` is a ``WorkflowLike`` mapping."""
    return is_mapping(value) and bool({"nodes", "version"}.intersection(value))


def is_pipedeflike(value: object) -> TypeGuard[PipeDefLike]:
    """Reports whether ``value`` is a ``PipeDef``."""
    if is_mapping(value) and not is_workflowlike(value) and "modules" in value:
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
    possible = is_mapping(value) and not is_workflowlike(value) and "modules" in value
    return possible and not is_pipedeflike(value)


def get_document_format(document: DocumentMapping) -> DocumentFormat:
    """
    Detects which of the readable shapes ``document`` is written in.

    A mapping listing ``nodes``, or declaring the workflow format version it targets,
    is a ``WorkflowLike``. One listing ``modules`` is either a ``PipeDef``, recognised
    by its wire mappings and its terminal output module, or a ``PipeDag``.

    Args:

        document: The parsed JSON input.

    Returns:

        The detected :class:`DocumentFormat`.

    Raises:

        InvalidPipelineError: If the input is not a mapping, or lists neither
            ``nodes`` nor ``modules``.

    Examples:

        >>> get_document_format({"nodes": [{"name": "forever"}]}).value
        'v2'
        >>> modules = [{"id": "_OUTPUT", "type": "output"}]
        >>> get_document_format({"modules": modules}).value
        'v1'

    """
    if is_workflowlike(document):
        fmt = DocumentFormat.V2
    elif is_pipedeflike(document):
        fmt = DocumentFormat.V1
    elif is_pipedag(document):
        fmt = DocumentFormat.DAG
    else:
        raise InvalidPipelineError(_SHAPE_ERROR)

    return fmt


def normalize_document(
    document: DocumentMapping, fmt: DocumentFormat | None = None
) -> Workflow:
    """
    Converts parsed input of any readable shape into a validated ``Workflow``.

    Args:

        document: The parsed JSON input.
        fmt: The shape to read it as. Omit it to detect the shape from the input.

    Returns:

        The validated :class:`~riko.definitions._workflow.Workflow`.

    Raises:

        InvalidPipelineError: If the shape cannot be detected, the input does not
            hold the shape it is read as, or the resulting workflow is invalid.

    Examples:

        >>> pipe_def = {
        ...     "modules": [
        ...         {"id": "sw-1", "type": "forever", "conf": {}},
        ...         {"id": "_OUTPUT", "type": "output", "conf": {}},
        ...     ],
        ...     "wires": [
        ...         {
        ...             "id": "_w1",
        ...             "src": {"id": "_OUTPUT", "moduleid": "sw-1"},
        ...             "tgt": {"id": "_INPUT", "moduleid": "_OUTPUT"},
        ...         }
        ...     ],
        ... }
        >>> normalize_document(pipe_def).outputs["default"]
        Endpoint(node='sw-1', port='out')

    """
    resolved = get_document_format(document) if fmt is None else fmt

    if resolved is DocumentFormat.V2:
        workflow = normalize_workflow(document)
    elif resolved is DocumentFormat.V1:
        workflow = migrate_v1_to_v2(document)  # pyright: ignore[reportArgumentType]
    else:
        workflow = parse_dag(document)  # pyright: ignore[reportArgumentType]

    workflow.validate()
    return workflow


def require_workflow(document: DocumentMapping) -> Workflow:
    """
    Loads parsed input that must already be a ``WorkflowLike``.

    Args:

        document: The parsed JSON input.

    Returns:

        The validated :class:`~riko.definitions._workflow.Workflow`.

    Raises:

        InvalidPipelineError: If the input is a ``PipeDef`` or ``PipeDag``, or is not
            a valid ``WorkflowLike``.

    Examples:

        >>> workflow = require_workflow({"nodes": [{"name": "forever"}]})
        >>> list(workflow.nodes)
        ['forever-1']

    """
    if (fmt := get_document_format(document)) is not DocumentFormat.V2:
        msg = f"this input is {_OTHER_FORMS[fmt.value]}, not a workflow document; run "
        msg += "it through build-workflow first to get one"
        raise InvalidPipelineError(msg)

    return normalize_document(document, DocumentFormat.V2)


__all__ = [
    "DocumentFormat",
    "DocumentMapping",
    "get_document_format",
    "normalize_document",
    "read_document",
    "require_workflow",
]
