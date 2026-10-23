# vim: sw=4:ts=4:expandtab
"""
Shared JSON input front door for the riko console scripts.

The console scripts read three JSON shapes: a workflow document (``WorkflowDocument``
aka a serialized ``Workflow``), a serialized pipe definition (``PipeDef``), and a
serialized ``PipeDag``. Every command reads its input from here. ``build-workflow``
is the most lenient and reads all three. The commands that run or generate code take
a ``WorkflowDocument`` only.

"""

from __future__ import annotations

import sys
from json import loads
from pathlib import Path
from typing import TYPE_CHECKING

from riko.base._exceptions import InvalidPipelineError
from riko.base._guards import require_mapping
from riko.base._logging import get_logger
from riko.definitions._serialize import get_document_shape
from riko.definitions._workflow_definition import Workflow
from riko.types._enums import DocumentShape

if TYPE_CHECKING:
    from logging import Logger

    from riko.types._io import PathLike

logger: Logger = get_logger(__name__)

_OTHER_SHAPES = {
    DocumentShape.DAG: "a serialized bare-bones DAG",
    DocumentShape.V1: "a serialized pipe definition",
}


def read_document(path: PathLike) -> tuple[object | None, str]:
    """
    Reads a JSON input from ``path``, or from stdin when it is ``-``.

    An unreadable, undecodable, or malformed input is reported as a warning and leaves
    the caller to decide what absent input means for it.

    Args:

        path: The path to read, or ``-`` for standard input.

    Returns:

        The parsed JSON input, or ``None`` when it could not be read; and the name it
        is known by: the file stem, or ``anonymous`` for standard input.

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


def require_workflow(document: object) -> Workflow:
    """
    Loads parsed input that must already be a workflow document.

    Args:

        document: The parsed JSON input.

    Returns:

        The validated :class:`~riko.definitions._workflow_definition.Workflow`.

    Raises:

        InvalidPipelineError: If the input is not a mapping, is a ``PipeDef`` or
            ``PipeDag``, or is not a valid workflow document.

    Examples:

        >>> flow = require_workflow({"nodes": [{"name": "forever"}]})
        >>> list(flow.nodes)
        ['forever-1']

    """
    mapping = require_mapping(document, "workflow")

    if (shape := get_document_shape(mapping)) is not DocumentShape.V2:
        msg = f"this input is {_OTHER_SHAPES[shape]}, not a workflow document; run "
        msg += "it through build-workflow first to get one"
        raise InvalidPipelineError(msg)

    return Workflow.parse(mapping, shape=DocumentShape.V2)


__all__ = ["read_document", "require_workflow"]
