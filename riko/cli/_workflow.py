# vim: sw=4:ts=4:expandtab
"""
Shared JSON document front door for the riko console scripts.

Every command that takes a workflow document reads it here, so one place decides
which shape a document is written in, which loader turns it into a canonical
workflow, and which commands accept the older shapes at all. ``convert-dag`` is the
lenient one; the commands that run or generate code take canonical documents only.

Examples:

    Basic usage::

        >>> from riko.cli._workflow import detect_format, load_workflow
        >>>
        >>> dag = {"modules": [{"type": "forever"}, {"type": "truncate"}]}
        >>> detect_format(dag).value
        'dag'
        >>> list(load_workflow(dag).nodes)
        ['sw-1', 'sw-2']

"""

from __future__ import annotations

import sys
from enum import StrEnum
from json import loads
from pathlib import Path
from typing import TYPE_CHECKING, cast

from riko.base._config import OUTPUT_MODULE
from riko.base._logging import logger
from riko.base.exceptions import InvalidPipelineError
from riko.runtime._migrate import build_workflow, migrate_v1_to_v2
from riko.runtime._normalize import normalize_workflow
from riko.types._guards import is_mapping

if TYPE_CHECKING:
    from riko.definitions._workflow import WorkflowSpec
    from riko.types._compiler import PipeDag, PipeDefLike
    from riko.types._workflow import WorkflowSpecLike

type WorkflowDocument = WorkflowSpecLike | PipeDefLike | PipeDag

_SHAPE_ERROR = "a workflow document needs 'nodes' or 'modules'"
_WIRE_KEYS = frozenset({"src", "tgt"})


class DocumentFormat(StrEnum):
    """The document shapes the console scripts read."""

    DAG = "dag"
    V1 = "v1"
    V2 = "v2"


def _entries(value: object) -> tuple[object, ...]:
    """Supplies a document's listed entries, or nothing when it lists none."""
    return tuple(value) if isinstance(value, (list, tuple)) else ()


def _is_legacy(**document: object) -> bool:
    """Reports whether a ``modules`` document uses the older wire and output shape."""
    wired = any(
        is_mapping(wire) and not _WIRE_KEYS.isdisjoint(wire)
        for wire in _entries(document.get("wires"))
    )
    terminal = any(
        is_mapping(module) and module.get("type") == OUTPUT_MODULE
        for module in _entries(document.get("modules"))
    )
    return wired or terminal


def read_document(path: str) -> tuple[WorkflowDocument | None, str]:
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
    stdin = path == "-"
    name = "anonymous" if stdin else Path(path).stem

    try:
        text = sys.stdin.read() if stdin else Path(path).read_text(encoding="utf-8")
        document = loads(text)
    except OSError as e:
        logger.warning("Unable to read workflow document: %s", e)
        document = None
    except ValueError as e:
        logger.warning("Invalid JSON in workflow document: %s", e)
        document = None

    return document, name


def detect_format(document: WorkflowDocument) -> DocumentFormat:
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

        >>> detect_format({"nodes": [{"name": "forever"}]}).value
        'v2'
        >>> detect_format({"modules": [{"id": "_OUTPUT", "type": "output"}]}).value
        'v1'

    """
    keys = document if is_mapping(document) else {}

    if "nodes" in keys or "version" in keys:
        fmt = DocumentFormat.V2
    elif "modules" in keys:
        fmt = DocumentFormat.V1 if _is_legacy(**keys) else DocumentFormat.DAG
    else:
        raise InvalidPipelineError(_SHAPE_ERROR)

    return fmt


def load_workflow(
    document: WorkflowDocument, fmt: DocumentFormat | None = None
) -> WorkflowSpec:
    """
    Loads a document of any readable shape as a validated canonical workflow.

    Args:

        document: The parsed JSON document.
        fmt: The shape to read it as. Omit it to detect the shape from the document.

    Returns:

        The canonical :class:`~riko.definitions._workflow.WorkflowSpec`.

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
        >>> load_workflow(pipe_def).outputs["default"]
        Endpoint(node='sw-1', port='out')

    """
    resolved = detect_format(document) if fmt is None else fmt

    if resolved is DocumentFormat.V2:
        spec = normalize_workflow(document)
    elif resolved is DocumentFormat.V1:
        spec = migrate_v1_to_v2(document)
    else:
        spec = build_workflow(cast("PipeDag", document))

    spec.validate()
    return spec


def require_workflow(document: WorkflowDocument) -> WorkflowSpec:
    """
    Loads a document that has to already be a canonical workflow.

    Args:

        document: The parsed JSON document.

    Returns:

        The canonical :class:`~riko.definitions._workflow.WorkflowSpec`.

    Raises:

        InvalidPipelineError: If the document is written in an older shape, or is not
            a valid canonical workflow.

    Examples:

        >>> spec = require_workflow({"nodes": [{"name": "forever"}]})
        >>> list(spec.nodes)
        ['forever-1']

    """
    if (fmt := detect_format(document)) is not DocumentFormat.V2:
        msg = f"this document is written in the older {fmt.value} form; run it through "
        msg += "convert-dag first to get a canonical workflow document"
        raise InvalidPipelineError(msg)

    return load_workflow(document, DocumentFormat.V2)


__all__ = [
    "DocumentFormat",
    "WorkflowDocument",
    "detect_format",
    "load_workflow",
    "read_document",
    "require_workflow",
]
