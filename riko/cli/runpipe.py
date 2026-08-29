import sys
from argparse import ArgumentParser, RawTextHelpFormatter
from collections.abc import Callable, Iterable, Mapping
from importlib import import_module
from importlib.util import module_from_spec, spec_from_file_location
from os.path import basename, splitext
from types import ModuleType

from riko.bado._backend import run as async_run
from riko.types._wrappers import AsyncPipeParser

io_error = FileNotFoundError


def emit_result(result: object) -> None:
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


def load_file(name: str, location: str) -> ModuleType | None:
    if spec := spec_from_file_location(name, location):
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
    else:
        module = None

    return module


def file2name(_path: str) -> str:
    """
    Return the base module name for a file path.

    >>> file2name("examples/demo.py")
    'demo'
    """
    return splitext(basename(_path))[0]


async def runner(
    async_pipe: AsyncPipeParser, test: bool = False, cb: Callable | None = None
) -> None:
    result = await async_pipe(test=test)
    cb(result) if callable(cb) else None


def run() -> None:
    """CLI runner"""
    parser = ArgumentParser(
        description="description: Runs a riko pipe",
        prog="run-pipe",
        usage="%(prog)s [pipeid] [-p PATH]",
        formatter_class=RawTextHelpFormatter,
    )

    parser.add_argument(
        dest="pipeid",
        nargs="?",
        default=None,
        help="The pipeline to run from the examples directory.",
    )

    parser.add_argument(
        "-p",
        "--path",
        dest="path",
        default=None,
        help="Path to a pipe file to run, e.g. flow.py.\n\n",
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

    if args.path:
        name = file2name(args.path)

        try:
            module = load_file(name, args.path)
        except io_error:
            sys.exit(f"Pipe file {args.path} not found!")
    elif args.pipeid:
        try:
            name = file2name(f"{args.pipeid}.py")
            module = load_file(name, f"examples/{args.pipeid}.py")
        except io_error:
            try:
                module = import_module(f"examples.{args.pipeid}")
            except ImportError:
                sys.exit(f"Pipe examples.{args.pipeid} not found!")
    else:
        sys.exit("Please provide a pipeid or path to a pipe file.")

    printer = getattr(module, "print_results", emit_result)

    if args.isasync and (async_pipe := getattr(module, "async_pipe", None)):
        async_run(runner, async_pipe, args.test, printer)
    elif main := getattr(module, "main", None):
        main(test=args.test)
    else:
        emit_result(module.pipe(test=args.test))


if __name__ == "__main__":
    run()
