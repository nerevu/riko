"""
Runs a pipe script, a workflow module, or a workflow document from the CLI.

A pipe script is a Python file that defines ``pipe(test=False)``. A workflow module
(``WorkflowModule``) is Python source defining ``pipe`` and/or ``async_pipe`` over an
item, a stream, or nothing, plus a ``context``, such as ``compile-workflow`` output. A
workflow document (``WorkflowDocument``) is a serialized ``Workflow``.
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
from riko.bado.itertools import alist
from riko.base._paths import ROOT_DIR
from riko.base.exceptions import RikoError
from riko.definitions._context import Context
from riko.runtime._pipeline import Pipeline
from riko.types._wrappers import is_subpipe

from ._document import read_document, require_workflow

if TYPE_CHECKING:
    from types import ModuleType

    from riko.types._io import PathLike
    from riko.types._wrappers import AsyncModuleWrapper, ModuleWrapper

io_error = FileNotFoundError


def emit_result(result: object) -> None:
    """
    Prints a pipe result item by item.

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
        [emit_result(item) for item in result]
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


def build_pipe_kwargs(pipe: ModuleWrapper, test: bool) -> dict[str, object]:
    """
    Builds the keyword arguments that pass ``test`` to a run target's pipe.

    The ``workflow``-decorated pipe of a ``WorkflowModule`` (Python source defining
    ``pipe``/``async_pipe`` over an item, a stream, or nothing, plus a ``context``)
    reads ``test`` from its ``Context``, while a pipe script (a Python file defining
    ``pipe(test=False)``) or an undecorated pipe takes it directly.

    Args:

        pipe: The target's ``pipe`` or ``async_pipe``.
        test: Whether to use default input values instead of prompting.

    Returns:

        The keyword arguments to call ``pipe`` with.

    Examples:

        >>> def pipe(test=False): ...
        >>> build_pipe_kwargs(pipe, True)
        {'test': True}

    """
    return {"context": Context(test=test)} if is_subpipe(pipe) else {"test": test}


async def runner(
    async_pipe: AsyncModuleWrapper, test: bool = False, cb: Callable | None = None
) -> None:
    stream = async_pipe(**build_pipe_kwargs(async_pipe, test))
    result = await alist(stream)
    cb(result) if callable(cb) else None


async def aemit_result(pipeline: Pipeline) -> None:
    """
    Runs a pipeline asynchronously and prints the items it produces.

    Args:

        pipeline: The pipeline to iterate with ``async for``.

    """
    emit_result(await alist(pipeline))


def run_document(path: PathLike, isasync: bool = False, test: bool = False) -> None:
    """
    Runs the ``WorkflowDocument`` at ``path`` and prints what it produces.

    Args:

        path: The path to the ``WorkflowDocument``.
        isasync: Whether to iterate the pipeline asynchronously.
        test: Whether to use default input values instead of prompting.

    """
    document, _ = read_document(path)

    if document is None:
        sys.exit(f"Workflow document {path} not found!")

    pipeline = Pipeline(require_workflow(document), context=Context(test=test))
    async_run(aemit_result, pipeline) if isasync else emit_result(pipeline)


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


def resolve_example(pipeid: str) -> Path | ModuleType | None:
    """
    Resolves an id to the example pipe script or ``WorkflowDocument`` it names.

    Each candidate example directory is searched for ``<pipeid>.py`` and
    ``workflows/<pipeid>.json`` files.

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
        target: Path | ModuleType | None = found
    else:
        target = load_file(file2name(found.name), str(found))

    return target


def resolve_target(
    path: str | None = None, pipeid: str | None = None
) -> Path | ModuleType | None:
    """
    Resolves a run target: a pipe script, ``WorkflowModule``, or ``WorkflowDocument``.

    A pipe script is a Python file defining ``pipe(test=False)``; a ``WorkflowModule``
    is Python source defining ``pipe`` and/or ``async_pipe`` over an item, a stream,
    or nothing, plus a ``context``; and a ``WorkflowDocument`` is a serialized
    ``Workflow``.

    Args:

        path: The path to a pipe script, ``WorkflowModule``, or ``WorkflowDocument``.
        pipeid: The id of a pipe script/``WorkflowDocument`` in the example directory.

    Returns:

        The imported pipe script or ``WorkflowModule``, or the path to a
        ``WorkflowDocument``.

    """
    if path is not None and path.endswith(".json"):
        target: Path | ModuleType | None = Path(path)
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


def run_target(
    target: Path | ModuleType | None, *, isasync: bool = False, test: bool = False
) -> None:
    """
    Runs a resolved pipe script, ``WorkflowModule``, or ``WorkflowDocument``.

    Args:

        target: The loaded pipe script or ``WorkflowModule``, or path to a
            ``WorkflowDocument``.

        isasync: Whether to run the async pipe when the target has one.

        test: Whether to use default input values instead of prompting.

    """
    if isinstance(target, Path):
        run_document(target, isasync, test)
    else:
        printer = getattr(target, "print_results", emit_result)

        if isasync and (async_pipe := getattr(target, "async_pipe", None)):
            async_run(runner, async_pipe, test, printer)
        elif main := getattr(target, "main", None):
            main(test=test)
        elif target is not None:
            emit_result(target.pipe(**build_pipe_kwargs(target.pipe, test)))


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

    try:
        run_target(target, isasync=args.isasync, test=args.test)
    except RikoError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    run()
