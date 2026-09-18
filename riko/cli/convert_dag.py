"""
Converts a compact Riko DAG into a full pipeline definition.

Examples:

    Basic usage::

        >>> from riko import convert_dag
        >>>
        >>> dag = {
        ...     "modules": [
        ...         {"type": "forever", "conf": {}},
        ...         {"type": "truncate", "conf": {}},
        ...     ]
        ... }
        >>> pipe_def = convert_dag(dag)
        >>> [(w["src"]["moduleid"], w["tgt"]["moduleid"]) for w in pipe_def["wires"]]
        [('sw-1', 'sw-2'), ('sw-2', '_OUTPUT')]

"""

import sys
from argparse import ArgumentParser, RawTextHelpFormatter
from json import dumps, loads
from pathlib import Path

from riko.runtime._compile import convert_dag


def run() -> None:
    """CLI DAG converter."""
    parser = ArgumentParser(
        description="description: Converts a bare-bones riko DAG into a JSON pipeline",
        prog="convert-dag",
        usage="%(prog)s [path]",
        formatter_class=RawTextHelpFormatter,
    )

    parser.add_argument(dest="path", help="Path to the bare-bones DAG definition.")

    parser.add_argument(
        "-o",
        "--output",
        dest="output",
        default=None,
        help="Write the JSON pipeline to this path (default: stdout).\n\n",
    )

    args = parser.parse_args()
    dag = loads(Path(args.path).read_text(encoding="utf-8"))
    pipe_def = dumps(convert_dag(dag), indent=4)

    if args.output:
        Path(args.output).write_text(pipe_def, encoding="utf-8")
    else:
        sys.stdout.write(pipe_def)


if __name__ == "__main__":
    run()
