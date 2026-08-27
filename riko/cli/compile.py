"""
Compile a riko JSON pipeline into a Python module.

A full pipe definition (modules + verbose ``src``/``tgt`` wires) compiles to a
runnable module exposing a ``pipe`` (or ``async_pipe``) entry point:

>>> from riko.compile import compile_pipe
>>>
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
>>> source = compile_pipe(pipe_def, "pipe_demo")
>>> print(next(line for line in source.splitlines() if line.startswith("def ")))
def pipe(item=None, context: Context | None = None, **_):

A ``path`` of ``-`` (or no ``path`` at all) reads the definition from stdin and
names the pipe ``anonymous``, so the compiler composes in a shell pipeline::

    convert-dag flow.dag | compile-pipe - -o flow.py
"""

import sys
from argparse import ArgumentParser, RawTextHelpFormatter
from json import loads
from pathlib import Path

from riko._logging import logger
from riko.compile import compile_pipe, extract_dependencies
from riko.types.compile import PipeDef


def _load_pipe_def(path: str) -> tuple[PipeDef | None, str]:
    """Reads a pipe definition from `path`, or from stdin when it is ``-``."""
    stdin = path == "-"
    name = "anonymous" if stdin else Path(path).stem

    try:
        text = sys.stdin.read() if stdin else Path(path).read_text(encoding="utf-8")
        pipe_def = loads(text)
    except OSError as e:
        logger.warning("Unable to read pipe definition: %s", e)
        pipe_def = None
    except ValueError as e:
        logger.warning("Invalid JSON in pipe definition: %s", e)
        pipe_def = None

    return pipe_def, name


def run() -> None:
    """CLI compiler"""
    parser = ArgumentParser(
        description="description: Compiles a riko JSON pipeline into a Python module",
        prog="compile",
        usage="%(prog)s [path]",
        formatter_class=RawTextHelpFormatter,
    )

    parser.add_argument(
        dest="path",
        nargs="?",
        default="-",
        help="Path to the JSON pipeline definition ('-' or omitted reads stdin).",
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
    pipe_def, name = _load_pipe_def(args.path)

    if pipe_def is None:
        return_code = 1
    else:
        source = compile_pipe(pipe_def, name, is_async=args.is_async)

        if args.output:
            size = Path(args.output).write_text(source, encoding="utf-8")
            dest = args.output
        else:
            size = sys.stdout.write(source)
            dest = "stdout"

        if args.verbose:
            deps = ", ".join(extract_dependencies(pipe_def))
            print(f"Modules used in {name}: {deps}", file=sys.stderr)
            print(f"wrote {size} bytes to {dest}", file=sys.stderr)

        return_code = 0

    sys.exit(return_code)


if __name__ == "__main__":
    run()
