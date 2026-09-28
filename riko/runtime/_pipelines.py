# vim: sw=4:ts=4:expandtab
"""
Provides resolution for named pipelines.

Pipelines can be loaded from generated modules or JSON definitions.

Attributes:

    pipeline_resolver: Process-global resolver. Core ships it unconfigured, since
        a bare install has no named pipelines.

"""

from __future__ import annotations

from functools import partial, update_wrapper
from json import loads
from typing import TYPE_CHECKING, Literal, Protocol, cast, overload

from riko.base._config import SUBPIPE_TYPE
from riko.base._imports import import_or_else
from riko.base._strutils import pythonise
from riko.base.exceptions import UnsupportedPipelineError
from riko.types._guards import is_subpipe

from ._compile import parse_pipe_def
from ._importutils import load_interfaces, resolve_interface

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path
    from types import ModuleType

    from riko.types._compiler import ParsedPipeDef
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
    with anyone importing the generated pipe directly; marking it in place
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
    """Loads generated pipe modules by name and returns ``None`` if absent."""

    def load(self, name: str) -> ModuleType | None: ...  # noqa: E704


class PackageStore:
    """Loads pipe modules from a Python package."""

    def __init__(self, package: str) -> None:
        self._package = package

    def load(self, name: str) -> ModuleType | None:
        return import_or_else(f"{self._package}.{name}")


class MappingStore:
    """Loads pipe modules from an in-memory mapping."""

    def __init__(self, modules: Mapping[str, ModuleType]) -> None:
        self._modules = dict(modules)

    def load(self, name: str) -> ModuleType | None:
        return self._modules.get(name)


class CompositeStore:
    """Loads a pipe module from the first store that has it."""

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
    Loads pipeline definitions from a directory of JSON files.

    Despite the shared ``load`` name, this is not a ``ModuleStore``. It yields a
    ``ParsedPipeDef`` rather than a module. This is why ``PipelineResolver`` keeps
    it in its own slot instead of chaining it into a ``CompositeStore``. A loaded
    definition is interface-agnostic; the caller builds it with ``build_pipeline``
    or ``abuild_pipeline``.

    """

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def load(self, name: str) -> ParsedPipeDef | None:
        try:
            pipe_def = loads((self._directory / f"{name}.json").read_text())
        except OSError:
            parsed = None
        else:
            parsed = parse_pipe_def(pipe_def, name)

        return parsed


class PipelineResolver:
    """
    Resolves whole pipelines.

    Use the module registry to resolves leaf modules.

    Examples:

        >>> from types import ModuleType
        >>>
        >>> module = ModuleType("pipe_demo")
        >>> module.pipe = lambda stream=None, **kwargs: iter([{"x": 1}])
        >>> resolver = PipelineResolver(store=MappingStore({"pipe_demo": module}))
        >>> list(resolver.resolve("pipe_demo")())
        [{'x': 1}]

    """

    def __init__(
        self,
        *,
        store: ModuleStore | None = None,
        definitions: DirectoryStore | None = None,
    ) -> None:
        self._store = store
        self._definitions = definitions

    @staticmethod
    def _register_slot[T](
        current: T | None, value: T | None, kind: str, replace: bool
    ) -> T | None:
        if value is not None and current is not None and not replace:
            raise ValueError(f"pipeline {kind} already registered")

        return current if value is None else value

    def register(
        self,
        *,
        store: ModuleStore | None = None,
        definitions: DirectoryStore | None = None,
        replace: bool = False,
    ) -> None:
        """
        Registers a module store and/or a JSON-definition directory.

        Only the halves supplied are touched; an omitted half is left as it is.

        Args:

            store: Generated-pipe module store to register.
            definitions: JSON-definition directory to register.
            replace: Whether an already-registered half of the same kind may be
                replaced.

        Raises:

            ValueError: If a supplied half is already registered and ``replace``
                is False.

        """
        register_slot = partial(self._register_slot, replace=replace)
        self._store = register_slot(self._store, store, "store")
        self._definitions = register_slot(self._definitions, definitions, "definitions")

    def reset(self) -> None:
        """Clears the registered store and definitions, chiefly for test isolation."""
        self._store = None
        self._definitions = None

    def is_compatible(self, name: str) -> bool:
        return name.startswith(("pipe_", "pipe:"))

    def load(self, name: str) -> ModuleType | None:
        """Loads the generated pipe module for ``name``, or ``None``."""
        return None if self._store is None else self._store.load(name)

    @overload
    def resolve(  # noqa: E704
        self, name: str, is_async: Literal[False] = ...
    ) -> SyncModuleWrapper: ...
    @overload  # noqa: E301
    def resolve(  # noqa: E704
        self, name: str, is_async: Literal[True]
    ) -> AsyncModuleWrapper: ...
    def resolve(self, name: str, is_async: bool = False) -> ModuleWrapper:  # noqa: E301
        """
        Resolves a ``pipe_<id>`` / ``pipe:<id>`` name to its marked callable.

        Raises:

            UnsupportedPipelineError: If no store supplies ``name``, or its module
                has no ``interface`` callable.

        """
        kwargs = {"is_async": is_async, "builtin": False}
        pipe = resolve_interface(pythonise(name), loader=self.load, **kwargs)
        return _as_subpipe(pipe)

    def get_interfaces(self, name: str) -> frozenset[Interface]:
        """
        Resolves which of a pipeline's sync and async interfaces are defined.

        Args:

            name: ``pipe_<id>`` / ``pipe:<id>`` name to inspect.

        Returns:

            The subset of ``pipe``/``async_pipe`` the pipeline exposes.

        Raises:

            UnsupportedPipelineError: If no store supplies ``name``.

        """
        return load_interfaces(pythonise(name), builtin=False, loader=self.load)

    def load_definition(
        self, name: str, *, directory: Path | None = None
    ) -> ParsedPipeDef:
        """
        Load a named JSON pipeline with an optional directory override.

        Raises:

            UnsupportedPipelineError: If the definition cannot be found.

        """
        store = self._definitions if directory is None else DirectoryStore(directory)

        if (parsed := None if store is None else store.load(name)) is None:
            raise UnsupportedPipelineError(name)

        return parsed


pipeline_resolver: PipelineResolver = PipelineResolver()


def register_pipeline_store(
    *, package: str | None = None, directory: Path | None = None, replace: bool = False
) -> None:
    """
    Registers pipeline sources on the process-global resolver.

    Args:

        package: Import path of a package holding generated ``pipe_*`` modules.
        directory: Filesystem directory holding JSON pipeline definitions.
        replace: Whether an already-registered source of the same kind may be
            replaced.

    Raises:

        ValueError: If a supplied source is already registered and ``replace`` is
            False.

    Examples:

        >>> reset_pipeline_resolver()
        >>> register_pipeline_store(package="riko.modules")
        >>> reset_pipeline_resolver()

    """
    store = None if package is None else PackageStore(package)
    definitions = None if directory is None else DirectoryStore(directory)
    pipeline_resolver.register(store=store, definitions=definitions, replace=replace)


def reset_pipeline_resolver() -> None:
    """
    Resets the process-global resolver, chiefly for test isolation.

    Examples:

        >>> reset_pipeline_resolver()
        >>> register_pipeline_store(package="riko.modules")
        >>> reset_pipeline_resolver()
        >>> pipeline_resolver.load("pipe_demo") is None
        True

    """
    pipeline_resolver.reset()


__all__ = [
    "DirectoryStore",
    "MappingStore",
    "PackageStore",
    "PipelineResolver",
    "pipeline_resolver",
    "register_pipeline_store",
    "reset_pipeline_resolver",
]
