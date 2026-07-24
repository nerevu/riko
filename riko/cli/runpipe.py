import sys
from argparse import ArgumentParser, RawTextHelpFormatter
from collections.abc import Iterable, Mapping
from importlib import import_module
from importlib.util import module_from_spec, spec_from_file_location
from os import path as p

from riko.bado import run as async_run

io_error = FileNotFoundError


def emit_result(result) -> None:
    """
    Print a pipe result, expanding iterables item by item.

    >>> emit_result(["alpha", "beta"])
    alpha
    beta
    >>> emit_result({"title": "riko"})
    {'title': 'riko'}
    >>> emit_result(None)
    """
    if result is None:
        pass
    elif isinstance(result, (Mapping, str)):
        print(result)
    elif isinstance(result, Iterable):
        for item in result:
            emit_result(item)
    else:
        print(result)


def load_file(name, src):
    location = f"examples/{src}.py"

    if spec := spec_from_file_location(name, location):
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
    else:
        module = None

    return module


def file2name(path):
    """
    Return the base module name for a file path.

    >>> file2name("examples/demo.py")
    'demo'
    """
    return p.splitext(p.basename(path))[0]


async def runner(async_pipe, test=False, cb=None):
    result = await async_pipe(test=test)
    cb(result) if callable(cb) else None


def run():
    """CLI runner"""
    parser = ArgumentParser(
        description="description: Runs a riko pipe",
        prog="runpipe",
        usage="%(prog)s [pipeid]",
        formatter_class=RawTextHelpFormatter,
    )

    parser.add_argument(
        dest="pipeid",
        nargs="?",
        default=None,
        help="The pipe to run (default: reads from stdin).",
    )

    parser.add_argument(
        "-a",
        "--async",
        dest="isasync",
        action="store_true",
        default=False,
        help="Load async pipe.\n\n",
    )

    parser.add_argument(
        "-t",
        "--test",
        action="store_true",
        default=False,
        help="Run in test mode (uses default inputs).\n\n",
    )

    args = parser.parse_args()

    try:
        name = file2name(f"{args.pipeid}.py")
        module = load_file(name, args.pipeid)
    except io_error:
        try:
            module = import_module(f"examples.{args.pipeid}")
        except ImportError:
            sys.exit(f"Pipe examples.{args.pipeid} not found!")

    printer = getattr(module, "print_results", emit_result)

    if args.isasync and (async_pipe := getattr(module, "async_pipe", None)):
        async_run(runner, async_pipe, args.test, printer)
    elif main := getattr(module, "main", None):
        main(test=args.test)
    else:
        emit_result(module.pipe(test=args.test))


if __name__ == "__main__":
    run()
