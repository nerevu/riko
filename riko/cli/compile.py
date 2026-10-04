"""
Compiles a workflow document into a Python module.

A workflow document (``WorkflowDocument``) is a serialized ``Workflow``. Convert a
serialized ``PipeDef`` or ``PipeDag`` with ``build-workflow`` first.

Examples:

    Basic usage::

        >>> from riko import compile_pipe
        >>>
        >>> workflow = {
        ...     "nodes": [
        ...         {"id": "gen", "name": "forever"},
        ...         {"id": "trunc", "name": "truncate", "conf": {"count": 3}},
        ...     ],
        ...     "edges": [{"source": {"node": "gen"}, "target": {"node": "trunc"}}],
        ... }
        >>> source = compile_pipe(workflow, "pipe_demo")
        >>> print(next(l for l in source.splitlines() if l.startswith("def pipe")))
        def pipe(item=None, context: Context | None = None, **_):

    CLI composition::

        $ build-workflow dag.json | compile-pipe - -o flow.py

"""

from __future__ import annotations

import sys
from argparse import ArgumentParser, RawTextHelpFormatter
from pathlib import Path

from riko.base.exceptions import InvalidPipelineError
from riko.runtime._codegen import compile_pipe

from ._workflow import read_document, require_workflow


def run() -> None:
    """CLI compiler."""
    parser = ArgumentParser(
        description="description: Compiles a workflow document into a Python module",
        prog="compile-pipe",
        usage="%(prog)s [path]",
        formatter_class=RawTextHelpFormatter,
    )

    parser.add_argument(
        dest="path",
        nargs="?",
        default="-",
        help="Path to the workflow document ('-' or omitted reads stdin).",
    )

    parser.add_argument(
        "-o",
        "--output",
        dest="output",
        default=None,
        help="Write the generated module to this path (default: stdout).\n\n",
    )

    parser.add_argument(
        "-a",
        "--async",
        dest="is_async",
        action="store_true",
        default=False,
        help="Generate an async (anyio) pipeline module.\n\n",
    )

    parser.add_argument(
        "-v",
        "--verbose",
        dest="verbose",
        action="store_true",
        default=False,
        help="Report the modules used and bytes written to stderr.\n\n",
    )

    args = parser.parse_args()
    document, name = read_document(args.path)

    if document is None:
        return_code = 1
    else:
        try:
            workflow = require_workflow(document)
            source = compile_pipe(workflow, name, is_async=args.is_async)
        except InvalidPipelineError as e:
            print(e, file=sys.stderr)
            return_code = 1
        else:
            if args.output is None:
                size = sys.stdout.write(source)
                dest = "stdout"
            else:
                size = Path(args.output).write_text(source, encoding="utf-8")
                dest = args.output

            if args.verbose:
                deps = ", ".join(
                    sorted({node.name for node in workflow.nodes.values()})
                )
                print(f"Modules used in {name}: {deps}", file=sys.stderr)
                print(f"wrote {size} bytes to {dest}", file=sys.stderr)

            return_code = 0

    sys.exit(return_code)


if __name__ == "__main__":
    run()
