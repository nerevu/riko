"""
Command for running a pipe script or a workflow document from the CLI.

A workflow document (``WorkflowDocument``) is a serialized ``Workflow``.
"""

from __future__ import annotations

import sys
from argparse import ArgumentParser, RawTextHelpFormatter
from collections.abc import Callable, Iterable, Mapping
from importlib import import_module
from importlib.util import module_from_spec, spec_from_file_location
from os.path import basename, isfile, splitext
from typing import TYPE_CHECKING

from riko.bado._backend import run as async_run
from riko.base.exceptions import InvalidPipelineError
from riko.execution._execution import AsyncExecution, SyncExecution
from riko.execution.context import Context
from riko.runtime._execution_plan import build_execution_plan

from ._workflow import read_document, require_workflow

if TYPE_CHECKING:
    from types import ModuleType

    from riko.runtime._execution_plan import ExecutionPlan
    from riko.types._wrappers import AsyncModuleWrapper

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

        if spec.loader:
            spec.loader.exec_module(module)
    else:
        module = None

    return module


def file2name(_path: str) -> str:
    """
    Derives the base module name for a file path.

    >>> file2name("examples/demo.py")
    'demo'
    """
    return splitext(basename(_path))[0]


async def runner(
    async_pipe: AsyncModuleWrapper, test: bool = False, cb: Callable | None = None
) -> None:
    stream = async_pipe(test=test)
    result = [item async for item in stream]
    cb(result) if callable(cb) else None


async def plan_runner(plan: ExecutionPlan, test: bool = False) -> None:
    """Runs a prepared workflow asynchronously and prints the items it produces."""
    async with AsyncExecution(context=Context(test=test)) as execution:
        stream = await execution.run(plan)
        items = [item async for item in stream]
        emit_result(items)


def run_document(path: str, isasync: bool = False, test: bool = False) -> None:
    """
    Runs the ``WorkflowDocument`` at ``path`` and prints what it produces.

    Args:

        path: The path to the ``WorkflowDocument``.
        isasync: Whether to run the ``Workflow`` through the asynchronous execution.
        test: Whether to run with the modules' default inputs.

    """
    document, _ = read_document(path)

    if document is None:
        sys.exit(f"Workflow document {path} not found!")

    try:
        plan = build_execution_plan(require_workflow(document))
    except InvalidPipelineError as e:
        sys.exit(str(e))

    if isasync:
        async_run(plan_runner, plan, test)
    else:
        with SyncExecution(context=Context(test=test)) as execution:
            emit_result(execution.run(plan))


def resolve_example(pipeid: str) -> str | ModuleType | None:
    """
    Resolves an example id to the pipe module or ``WorkflowDocument`` it names.

    Args:

        pipeid: The name of a pipeline in the examples directory.

    Returns:

        The loaded pipe module, or the path to the ``WorkflowDocument`` of that name.

    """
    try:
        name = file2name(f"{pipeid}.py")
        target: str | ModuleType | None = load_file(name, f"examples/{pipeid}.py")
    except io_error:
        document = f"examples/pipelines/{pipeid}.json"

        if isfile(document):
            target = document
        else:
            try:
                target = import_module(f"examples.{pipeid}")
            except ImportError:
                sys.exit(f"Pipe examples.{pipeid} not found!")

    return target


def resolve_target(
    path: str | None = None, pipeid: str | None = None
) -> str | ModuleType | None:
    """
    Resolves what a run refers to: a ``WorkflowDocument``, or a pipe module.

    Args:

        path: The path to a pipe script or a ``WorkflowDocument``.
        pipeid: The name of a pipeline in the examples directory.

    Returns:

        The loaded pipe module, or the path to a ``WorkflowDocument``.

    """
    if path is not None and path.endswith(".json"):
        target: str | ModuleType | None = path
    elif path is not None:
        try:
            target = load_file(file2name(path), path)
        except io_error:
            sys.exit(f"Pipe file {path} not found!")
    elif pipeid is not None:
        target = resolve_example(pipeid)
    else:
        sys.exit("Please provide a pipeid or path to a pipe file.")

    return target


def run() -> None:
    """CLI runner."""
    parser = ArgumentParser(
        description="description: Runs a riko pipe or a workflow document",
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
        help="Path to a pipe file to run, e.g. flow.py or flow.json.\n\n",
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
    target = resolve_target(args.path, args.pipeid)

    if isinstance(target, str):
        run_document(target, args.isasync, args.test)
    else:
        printer = getattr(target, "print_results", emit_result)

        if args.isasync and (async_pipe := getattr(target, "async_pipe", None)):
            async_run(runner, async_pipe, args.test, printer)
        elif main := getattr(target, "main", None):
            main(test=args.test)
        elif target:
            emit_result(target.pipe(test=args.test))


if __name__ == "__main__":
    run()
