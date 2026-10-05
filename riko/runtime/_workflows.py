# vim: sw=4:ts=4:expandtab
"""
Provides resolution for named workflows.

A named workflow is a ``Workflow`` filed under a ``pipe_<id>`` name: a workflow module
(``WorkflowModule``), generated or hand-written, or a workflow document
(``WorkflowDocument``: a serialized ``Workflow``).

Attributes:

    workflow_resolver: Process-global resolver. Core ships it unconfigured, since
        a bare install has no named workflows.

"""

from __future__ import annotations

from functools import partial, update_wrapper
from typing import TYPE_CHECKING, Literal, Protocol, cast, overload

from riko.base._config import SUBPIPE_TYPE
from riko.base._imports import import_or_else
from riko.base._strutils import pythonise
from riko.base.exceptions import UnsupportedPipelineError
from riko.types._guards import is_subpipe

from ._importutils import load_interfaces, require_interface
from ._serialize import parse_document

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path
    from types import ModuleType

    from riko.definitions._workflow import Workflow
    from riko.types._wrappers import (
        AsyncModuleWrapper,
        AsyncSubPipe,
        AysncFunc,
        Func,
        Interface,
        ModuleWrapper,
        SubPipe,
        SyncModuleWrapper,
        SyncSubPipe,
    )
    from riko.types.modules import ModuleSubtype


@overload
def mark_subpipe(  # noqa: E704  # pyright: ignore[reportOverlappingOverload]
    pipe: AysncFunc, *, subtype: ModuleSubtype = ..., loopable: bool = ...
) -> AsyncSubPipe: ...
@overload  # noqa: E302
def mark_subpipe(  # noqa: E704
    pipe: Func, *, subtype: ModuleSubtype = ..., loopable: bool = ...
) -> SyncSubPipe: ...
def mark_subpipe(  # noqa: E302
    pipe: Func, *, subtype: ModuleSubtype = "transformer", loopable: bool = True
) -> SubPipe:
    setattr(pipe, "name", getattr(pipe, "__name__", SUBPIPE_TYPE))  # noqa: B010
    setattr(pipe, "type", SUBPIPE_TYPE)  # noqa: B010
    setattr(pipe, "subtype", subtype)  # noqa: B010
    setattr(pipe, "subtypes", {subtype})  # noqa: B010
    setattr(pipe, "loopable", loopable)  # noqa: B010
    setattr(pipe, "pollable", False)  # noqa: B010
    return cast("SubPipe", pipe)


def _as_subpipe(pipe: ModuleWrapper) -> SubPipe:
    """
    Builds a sub-pipe-marked wrapper around ``pipe``.

    The marker goes on a fresh ``partial`` because the module callable is shared
    with anyone importing the workflow module directly; marking it in place
    would leak sub-pipe semantics into those calls.

    """
    if is_subpipe(pipe):
        subpipe = pipe
    else:
        subpipe = cast("SubPipe", partial(pipe))
        update_wrapper(subpipe, pipe)
        subtype = cast("ModuleSubtype", getattr(pipe, "subtype", "source"))
        loopable = cast("bool", getattr(pipe, "loopable", True))
        mark_subpipe(subpipe, subtype=subtype, loopable=loopable)

    return subpipe


class ModuleStore(Protocol):
    """Loads workflow modules by name and returns ``None`` if absent."""

    def load(self, name: str) -> ModuleType | None: ...  # noqa: E704


class PackageStore:
    """Loads workflow modules from a Python package."""

    def __init__(self, package: str) -> None:
        self._package = package

    def load(self, name: str) -> ModuleType | None:
        return import_or_else(f"{self._package}.{name}")


class MappingStore:
    """Loads workflow modules from an in-memory mapping."""

    def __init__(self, modules: Mapping[str, ModuleType]) -> None:
        self._modules = dict(modules)

    def load(self, name: str) -> ModuleType | None:
        return self._modules.get(name)


class CompositeStore:
    """Loads a workflow module from the first store that has it."""

    def __init__(self, *stores: ModuleStore) -> None:
        self._stores = stores

    def load(self, name: str) -> ModuleType | None:
        found = None

        for store in self._stores:
            if (found := store.load(name)) is not None:
                break

        return found


class DirectoryStore:
    """
    Loads ``WorkflowDocument`` files from a directory.

    Despite the shared ``load`` name, this is not a ``ModuleStore``. It yields a
    ``Workflow`` rather than a module. This is why ``WorkflowResolver`` keeps
    it in its own slot instead of chaining it into a ``CompositeStore``. A loaded
    workflow is interface-agnostic; the caller runs it with the execution layer.

    """

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def load(self, name: str) -> Workflow | None:
        try:
            text = (self._directory / f"{name}.json").read_text()
        except OSError:
            parsed = None
        else:
            parsed = parse_document(text)

        return parsed


class WorkflowResolver:
    """
    Resolves named workflows.

    Use the module registry to resolve leaf modules.

    Examples:

        >>> from types import ModuleType
        >>>
        >>> module = ModuleType("pipe_demo")
        >>> module.pipe = lambda stream=None, **kwargs: iter([{"x": 1}])
        >>> resolver = WorkflowResolver(store=MappingStore({"pipe_demo": module}))
        >>> list(resolver.require("pipe_demo")())
        [{'x': 1}]

    """

    def __init__(
        self,
        *,
        store: ModuleStore | None = None,
        documents: DirectoryStore | None = None,
    ) -> None:
        self._store = store
        self._documents = documents

    @staticmethod
    def _register_slot[T](
        current: T | None, value: T | None, kind: str, replace: bool
    ) -> T | None:
        if value is not None and current is not None and not replace:
            raise ValueError(f"workflow {kind} already registered")

        return current if value is None else value

    def register(
        self,
        *,
        store: ModuleStore | None = None,
        documents: DirectoryStore | None = None,
        replace: bool = False,
    ) -> None:
        """
        Registers a module store and/or a ``WorkflowDocument`` directory.

        Only the halves supplied are touched; an omitted half is left as it is.

        Args:

            store: Workflow-module store to register.
            documents: ``WorkflowDocument`` directory to register.
            replace: Whether an already-registered half of the same kind may be
                replaced.

        Raises:

            ValueError: If a supplied half is already registered and ``replace``
                is False.

        """
        register_slot = partial(self._register_slot, replace=replace)
        self._store = register_slot(self._store, store, "store")
        self._documents = register_slot(self._documents, documents, "documents")

    def reset(self) -> None:
        """Clears the registered store and documents, chiefly for test isolation."""
        self._store = None
        self._documents = None

    def is_compatible(self, name: str) -> bool:
        return name.startswith(("pipe_", "pipe:"))

    def load(self, name: str) -> ModuleType | None:
        """Loads the workflow module for ``name``, or ``None``."""
        return None if self._store is None else self._store.load(name)

    @overload
    def require(  # noqa: E704
        self, name: str, is_async: Literal[False] = ...
    ) -> SyncModuleWrapper: ...
    @overload  # noqa: E301
    def require(  # noqa: E704
        self, name: str, is_async: Literal[True]
    ) -> AsyncModuleWrapper: ...
    def require(self, name: str, is_async: bool = False) -> ModuleWrapper:  # noqa: E301
        """
        Resolves a ``pipe_<id>`` / ``pipe:<id>`` name to its marked callable.

        Raises:

            UnsupportedPipelineError: If no store supplies ``name``, or its module
                has no ``interface`` callable.

        """
        kwargs = {"is_async": is_async, "builtin": False}
        pipe = require_interface(pythonise(name), loader=self.load, **kwargs)
        return _as_subpipe(pipe)

    def require_interfaces(self, name: str) -> frozenset[Interface]:
        """
        Resolves which of a named workflow's sync and async interfaces are defined.

        Args:

            name: ``pipe_<id>`` / ``pipe:<id>`` name to inspect.

        Returns:

            The subset of ``pipe``/``async_pipe`` the workflow module exposes.

        Raises:

            UnsupportedPipelineError: If no store supplies ``name``.

        """
        return load_interfaces(pythonise(name), builtin=False, loader=self.load)

    def load_definition(self, name: str, *, directory: Path | None = None) -> Workflow:
        """
        Loads a named ``WorkflowDocument``, optionally from ``directory``.

        Args:

            name: ``pipe_<id>`` / ``pipe:<id>`` name to load.
            directory: Directory to read from instead of the registered one.

        Returns:

            The ``Workflow`` the ``WorkflowDocument`` describes.

        Raises:

            UnsupportedPipelineError: If the ``WorkflowDocument`` cannot be found.

        """
        store = self._documents if directory is None else DirectoryStore(directory)

        if (parsed := None if store is None else store.load(name)) is None:
            raise UnsupportedPipelineError(name)

        return parsed


workflow_resolver: WorkflowResolver = WorkflowResolver()


def register_workflow_store(
    *, package: str | None = None, directory: Path | None = None, replace: bool = False
) -> None:
    """
    Registers named-workflow sources on the process-global resolver.

    Args:

        package: Import path of a package holding generated ``pipe_*`` modules.
        directory: Filesystem directory holding ``WorkflowDocument`` files.
        replace: Whether an already-registered source of the same kind may be
            replaced.

    Raises:

        ValueError: If a supplied source is already registered and ``replace`` is
            False.

    Examples:

        >>> reset_workflow_resolver()
        >>> register_workflow_store(package="riko.modules")
        >>> reset_workflow_resolver()

    """
    store = None if package is None else PackageStore(package)
    documents = None if directory is None else DirectoryStore(directory)
    workflow_resolver.register(store=store, documents=documents, replace=replace)


def reset_workflow_resolver() -> None:
    """
    Resets the process-global resolver, chiefly for test isolation.

    Examples:

        >>> reset_workflow_resolver()
        >>> register_workflow_store(package="riko.modules")
        >>> reset_workflow_resolver()
        >>> workflow_resolver.load("pipe_demo") is None
        True

    """
    workflow_resolver.reset()


__all__ = [
    "DirectoryStore",
    "MappingStore",
    "PackageStore",
    "WorkflowResolver",
    "register_workflow_store",
    "reset_workflow_resolver",
    "workflow_resolver",
]
