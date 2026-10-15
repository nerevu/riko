"""
Converts a serialized ``PipeDag`` or pipe definition into a workflow document.

A pipe definition (``PipeDef``) is the older ``src``/``tgt``-wired module listing; a
workflow document (``WorkflowDocument``) is a serialized ``Workflow``. A
``WorkflowDocument`` given as input is re-normalized and written back out.

Examples:

    Basic usage::

        >>> from riko import Workflow
        >>>
        >>> count = {"count": {"type": "int", "value": "3"}}
        >>> dag = {
        ...     "modules": [
        ...         {"name": "forever"},
        ...         {"name": "truncate", "conf": count},
        ...     ]
        ... }
        >>> flow = Workflow.parse(dag)
        >>> list(flow.nodes)
        ['sw-1', 'sw-2']
        >>> flow.outputs["default"]
        Endpoint(node='sw-2', port='out')

    CLI composition::

        $ build-workflow dag.json | compile-workflow - -o flow.py

"""

from __future__ import annotations

import sys
from argparse import ArgumentParser, RawTextHelpFormatter
from pathlib import Path

from riko.base.exceptions import InvalidPipelineError
from riko.definitions._workflow import Workflow
from riko.types._enums import DocumentShape
from riko.types._guards import require_mapping

from ._workflow import read_document


def run() -> None:
    """CLI workflow converter."""
    parser = ArgumentParser(
        description=(
            "description: Converts a serialized bare-bones DAG or serialized pipe "
            "definition into a workflow document"
        ),
        prog="build-workflow",
        usage="%(prog)s [path]",
        formatter_class=RawTextHelpFormatter,
    )

    parser.add_argument(
        dest="path",
        nargs="?",
        default="-",
        help="Path to the JSON file to convert ('-' or omitted reads stdin).",
    )

    parser.add_argument(
        "-f",
        "--format",
        dest="fmt",
        choices=[member.value for member in DocumentShape],
        default=None,
        help="Read the input in this form (default: detect it).\n\n",
    )

    parser.add_argument(
        "-c",
        "--compact",
        dest="compact",
        action="store_true",
        default=False,
        help="Write the compact single-line form instead of the readable one.\n\n",
    )

    parser.add_argument(
        "-o",
        "--output",
        dest="output",
        default=None,
        help="Write the workflow document to this path (default: stdout).\n\n",
    )

    args = parser.parse_args()
    document = read_document(args.path)[0]

    if document is None:
        print(f"Unable to convert {args.path}", file=sys.stderr)
        return_code = 1
    else:
        try:
            mapping = require_mapping(document, "workflow")
            flow = Workflow.parse(mapping, shape=args.fmt)
        except InvalidPipelineError as e:
            print(e, file=sys.stderr)
            return_code = 1
        else:
            options = {"indent": None} if args.compact else {}
            text = flow.serialize(**options).decode("utf-8")

            if args.output is None:
                sys.stdout.write(text)
            else:
                Path(args.output).write_text(text, encoding="utf-8")

            return_code = 0

    sys.exit(return_code)


if __name__ == "__main__":
    run()
