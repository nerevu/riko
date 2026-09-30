"""
Converts a terser workflow document into a canonical workflow document.

Examples:

    Basic usage::

        >>> from riko import build_workflow
        >>>
        >>> count = {"count": {"type": "int", "value": "3"}}
        >>> dag = {
        ...     "modules": [
        ...         {"type": "forever"},
        ...         {"type": "truncate", "conf": count},
        ...     ]
        ... }
        >>> spec = build_workflow(dag)
        >>> list(spec.nodes)
        ['sw-1', 'sw-2']
        >>> spec.outputs["default"]
        Endpoint(node='sw-2', port='out')

    CLI composition::

        $ convert-dag dag.json | compile-pipe - -o flow.py

"""

from __future__ import annotations

import sys
from argparse import ArgumentParser, RawTextHelpFormatter
from pathlib import Path

from riko.base.exceptions import InvalidPipelineError
from riko.runtime._serialize import serialize_workflow

from ._workflow import DocumentFormat, load_workflow, read_document


def run() -> None:
    """CLI workflow converter."""
    parser = ArgumentParser(
        description=(
            "description: Converts a bare-bones DAG or an older pipe definition "
            "into a canonical workflow document"
        ),
        prog="convert-dag",
        usage="%(prog)s [path]",
        formatter_class=RawTextHelpFormatter,
    )

    parser.add_argument(
        dest="path",
        nargs="?",
        default="-",
        help="Path to the document to convert ('-' or omitted reads stdin).",
    )

    parser.add_argument(
        "-f",
        "--format",
        dest="fmt",
        choices=[member.value for member in DocumentFormat],
        default=None,
        help="Read the document in this form (default: detect it).\n\n",
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
        help="Write the canonical workflow to this path (default: stdout).\n\n",
    )

    args = parser.parse_args()
    document, _ = read_document(args.path)
    fmt = None if args.fmt is None else DocumentFormat(args.fmt)

    if document is None:
        print(f"Unable to convert {args.path}", file=sys.stderr)
        return_code = 1
    else:
        try:
            spec = load_workflow(document, fmt)
        except InvalidPipelineError as e:
            print(e, file=sys.stderr)
            return_code = 1
        else:
            options = {"indent": None} if args.compact else {}
            text = serialize_workflow(spec, **options).decode("utf-8")

            if args.output is None:
                sys.stdout.write(text)
            else:
                Path(args.output).write_text(text, encoding="utf-8")

            return_code = 0

    sys.exit(return_code)


if __name__ == "__main__":
    run()
