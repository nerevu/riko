"""
Converts a serialized ``PipeDag`` or pipe definition into a workflow document.

A pipe definition (``PipeDef``) is the older ``src``/``tgt``-wired module listing; a
workflow document (``WorkflowDocument``) is a serialized ``Workflow``. A
``WorkflowDocument`` given as input is re-normalized and written back out.

Examples:

    Basic usage::

        >>> from riko import parse_dag
        >>>
        >>> count = {"count": {"type": "int", "value": "3"}}
        >>> dag = {
        ...     "modules": [
        ...         {"type": "forever"},
        ...         {"type": "truncate", "conf": count},
        ...     ]
        ... }
        >>> workflow = parse_dag(dag)
        >>> list(workflow.nodes)
        ['sw-1', 'sw-2']
        >>> workflow.outputs["default"]
        Endpoint(node='sw-2', port='out')

    CLI composition::

        $ build-workflow dag.json | compile-pipe - -o flow.py

"""

from __future__ import annotations

import sys
from argparse import ArgumentParser, RawTextHelpFormatter
from pathlib import Path

from riko.base.exceptions import InvalidPipelineError
from riko.runtime._serialize import serialize_workflow

from ._workflow import DocumentFormat, normalize_document, read_document


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
        choices=[member.value for member in DocumentFormat],
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
    fmt = None if args.fmt is None else DocumentFormat(args.fmt)

    if document is None:
        print(f"Unable to convert {args.path}", file=sys.stderr)
        return_code = 1
    else:
        try:
            workflow = normalize_document(document, fmt)
        except InvalidPipelineError as e:
            print(e, file=sys.stderr)
            return_code = 1
        else:
            options = {"indent": None} if args.compact else {}
            text = serialize_workflow(workflow, **options).decode("utf-8")

            if args.output is None:
                sys.stdout.write(text)
            else:
                Path(args.output).write_text(text, encoding="utf-8")

            return_code = 0

    sys.exit(return_code)


if __name__ == "__main__":
    run()
