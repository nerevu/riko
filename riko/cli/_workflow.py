# vim: sw=4:ts=4:expandtab
"""
Shared JSON document front door for the riko console scripts.

Every command that takes a workflow document reads it here, so one place decides
which shape a document is written in, which loader turns it into a canonical
workflow, and which commands accept the older shapes at all. ``build-workflow`` is the
lenient one; the commands that run or generate code take canonical documents only.

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
from riko.types._guards import is_mapping

if TYPE_CHECKING:
    from riko.definitions._workflow import Workflow, WorkflowLike
    from riko.types._compiler import PipeDag, PipeDefLike

_SHAPE_ERROR = "a workflow document needs 'nodes' or 'modules'"
_WIRE_KEYS = frozenset({"src", "tgt"})

type DocumentMapping = WorkflowLike | PipeDefLike | PipeDag


class DocumentFormat(StrEnum):
    """The document shapes the console scripts read."""

    DAG = "dag"
    V1 = "v1"
    V2 = "v2"


def read_document(path: Path | str) -> tuple[DocumentMapping | None, str]:
    """
    Reads a JSON workflow document from ``path``, or from stdin when it is ``-``.

    An unreadable path and malformed JSON are both reported as a warning, leaving the
    caller to decide what an absent document means for it.

    Args:

        path: The path to read, or ``-`` for standard input.

    Returns:

        The parsed document, or ``None`` when it could not be read, together with the
        name it is known by: the file stem, or ``anonymous`` for standard input.

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
            logger.warning("Unable to read workflow document: %s", e)
        except ValueError as e:
            logger.warning("Invalid JSON in workflow document: %s", e)

    document = None if text is None else loads(text)
    return document, name


def is_workflowlike(value: object) -> TypeGuard[WorkflowLike]:
    """Reports whether ``value`` is a workflow document."""
    return is_mapping(value) and bool({"nodes", "version"}.intersection(value))


def is_pipedeflike(value: object) -> TypeGuard[PipeDefLike]:
    """Reports whether ``value`` is a released pipe definition."""
    if is_mapping(value) and not is_workflowlike(value) and "modules" in value:
        wires = value.get("wires", ())
        modules = value.get("modules", ())

        wired = any(
            is_mapping(wire) and not _WIRE_KEYS.isdisjoint(wire) for wire in wires
        )
        terminal = any(
            is_mapping(module) and module.get("type") == OUTPUT_MODULE
            for module in modules
        )
        result = wired or terminal
    else:
        result = False

    return result


def is_pipedag(value: object) -> TypeGuard[PipeDag]:
    """Reports whether ``value`` is a bare-bones DAG."""
    possible = is_mapping(value) and not is_workflowlike(value) and "modules" in value
    return possible and not is_pipedeflike(value)


def get_document_format(document: DocumentMapping) -> DocumentFormat:
    """
    Detects which of the readable shapes ``document`` is written in.

    A document listing ``nodes``, or declaring the workflow version it targets, is a
    canonical workflow. One listing ``modules`` is either a released pipe definition,
    recognised by its wire mappings and its terminal output module, or a bare-bones
    DAG.

    Args:

        document: The parsed JSON document.

    Returns:

        The detected :class:`DocumentFormat`.

    Raises:

        InvalidPipelineError: If the document is not a mapping, or lists neither
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
    Converts a document of any readable shape into a validated canonical workflow.

    Args:

        document: The parsed JSON document.
        fmt: The shape to read it as. Omit it to detect the shape from the document.

    Returns:

        The canonical :class:`~riko.definitions._workflow.Workflow`.

    Raises:

        InvalidPipelineError: If the shape cannot be detected, the document does not
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
    if fmt is DocumentFormat.V2 or is_workflowlike(document):
        workflow = normalize_workflow(document)
    elif fmt is DocumentFormat.V1 or is_pipedeflike(document):
        workflow = migrate_v1_to_v2(document)  # pyright: ignore[reportArgumentType]
    elif fmt is DocumentFormat.DAG or is_pipedag(document):
        workflow = parse_dag(document)  # pyright: ignore[reportArgumentType]
    else:
        raise InvalidPipelineError(_SHAPE_ERROR)

    workflow.validate()
    return workflow


def require_workflow(document: DocumentMapping) -> Workflow:
    """
    Loads a document that has to already be a canonical workflow.

    Args:

        document: The parsed JSON document.

    Returns:

        The canonical :class:`~riko.definitions._workflow.Workflow`.

    Raises:

        InvalidPipelineError: If the document is written in an older shape, or is not
            a valid canonical workflow.

    Examples:

        >>> workflow = require_workflow({"nodes": [{"name": "forever"}]})
        >>> list(workflow.nodes)
        ['forever-1']

    """
    if (fmt := get_document_format(document)) is not DocumentFormat.V2:
        msg = f"this document is written in the older {fmt.value} form; run it through "
        msg += "build-workflow first to get a canonical workflow document"
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
