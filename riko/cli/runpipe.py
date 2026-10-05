"""
Runs a pipe script, a workflow module, or a workflow document from the CLI.

A pipe script is a Python file that defines ``pipe(test=False)``. A workflow module
(``WorkflowModule``) is the Python source ``compile-workflow`` generates. A workflow
document (``WorkflowDocument``) is a serialized ``Workflow``.
"""

from __future__ import annotations

import sys
from argparse import ArgumentParser, RawTextHelpFormatter
from collections.abc import Callable, Iterable, Mapping
from importlib.util import module_from_spec, spec_from_file_location
from itertools import chain
from os.path import basename, splitext
from pathlib import Path
from typing import TYPE_CHECKING

from riko.bado._backend import run as async_run
from riko.base._paths import ROOT_DIR
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


def get_example_dirs() -> list[Path]:
    """
    Lists the directories searched for an example id, nearest first.

    The ``examples`` directory under the current one comes first, then the one in the
    riko checkout. When both are the same directory, it is listed once.

    Examples:

        >>> str(get_example_dirs()[0])
        'examples'

    """
    local, checkout = Path("examples"), ROOT_DIR / "examples"
    return [local] if local.resolve() == checkout.resolve() else [local, checkout]


def resolve_example(pipeid: str) -> str | ModuleType | None:
    """
    Resolves an example id to the pipe script or ``WorkflowDocument`` it names.

    Each example directory is searched for ``<pipeid>.py``, then
    ``workflows/<pipeid>.json``, before moving to the next directory.

    Args:

        pipeid: The id of an example pipe script or workflow document.

    Returns:

        The loaded pipe script, or the path to the ``WorkflowDocument`` of that name.

    """
    dirs = get_example_dirs()
    candidates = chain.from_iterable(
        (dir / f"{pipeid}.py", dir / "workflows" / f"{pipeid}.json") for dir in dirs
    )

    if (found := next((path for path in candidates if path.is_file()), None)) is None:
        searched = ", ".join(str(directory) for directory in dirs)
        sys.exit(f"Example {pipeid} not found in {searched}!")
    elif found.suffix == ".json":
        target: str | ModuleType | None = str(found)
    else:
        target = load_file(file2name(found.name), str(found))

    return target


def resolve_target(
    path: str | None = None, pipeid: str | None = None
) -> str | ModuleType | None:
    """
    Resolves a run target: a pipe script, workflow module, or ``WorkflowDocument``.

    Args:

        path: The path to a pipe script, a ``WorkflowModule``, or a
            ``WorkflowDocument``.

        pipeid: The id of an example pipe script or workflow document.

    Returns:

        The loaded pipe script or ``WorkflowModule``, or path to a ``WorkflowDocument``.

    """
    if path is not None and path.endswith(".json"):
        target: str | ModuleType | None = path
    elif path is not None:
        try:
            target = load_file(file2name(path), path)
        except io_error:
            sys.exit(f"File {path} not found!")
    elif pipeid is not None:
        target = resolve_example(pipeid)
    else:
        sys.exit("Please provide a pipeid or a path to run.")

    return target


def run() -> None:
    """CLI runner."""
    parser = ArgumentParser(
        description=(
            "description: Runs a pipe script, workflow module, or workflow document"
        ),
        prog="run-pipe",
        usage="%(prog)s [pipeid] [-p PATH]",
        formatter_class=RawTextHelpFormatter,
    )

    parser.add_argument(
        dest="pipeid",
        nargs="?",
        default=None,
        help="The id of an example pipe script or workflow document.",
    )

    parser.add_argument(
        "-p",
        "--path",
        dest="path",
        default=None,
        help=(
            "Path to a pipe script, workflow module, or workflow document to run,\n"
            "e.g. pipe.py or flow.json.\n\n"
        ),
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
