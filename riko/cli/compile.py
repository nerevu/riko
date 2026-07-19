"""
Compile a riko JSON pipeline into a Python module.

A full pipe definition (modules + verbose ``src``/``tgt`` wires) compiles to a
runnable module whose function is named after the pipe:

>>> from riko.compile import compile
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
>>> source = compile(pipe_def, "pipe_demo")
>>> print(next(line for line in source.splitlines() if line.startswith("def ")))
def pipe_demo(item=None, conf: Conf = None, context: Context | None = None, **kwargs):
"""

import sys
from argparse import ArgumentParser, RawTextHelpFormatter
from json import loads
from pathlib import Path

from riko.compile import compile as compile_pipe


def run():
    """CLI compiler"""
    parser = ArgumentParser(
        description="description: Compiles a riko JSON pipeline into a Python module",
        prog="compile",
        usage="%(prog)s [path]",
        formatter_class=RawTextHelpFormatter,
    )

    parser.add_argument(
        dest="path",
        help="Path to the JSON pipeline definition.",
    )

    parser.add_argument(
        "-o",
        "--output",
        dest="output",
        default=None,
        help="Write the generated module to this path (default: stdout).\n\n",
    )

    args = parser.parse_args()
    pipe_file = Path(args.path)
    pipe_def = loads(pipe_file.read_text(encoding="utf-8"))
    source = compile_pipe(pipe_def, pipe_file.stem)

    if args.output:
        Path(args.output).write_text(source, encoding="utf-8")
    else:
        sys.stdout.write(source)


if __name__ == "__main__":
    run()
