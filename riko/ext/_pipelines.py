# vim: sw=4:ts=4:expandtab
"""
riko.ext._pipelines
~~~~~~~~~~~~~~~~~~~

Provides resolution for named pipelines.

Pipelines can be loaded from generated modules or JSON definitions.

Examples:
    Basic usage::

        >>> from types import ModuleType
        >>> from riko.ext._pipelines import MappingStore, PipelineResolver
        >>>
        >>> module = ModuleType("pipe_demo")
        >>> module.pipe = lambda stream=None, **kwargs: iter([{"x": 1}])
        >>> resolver = PipelineResolver(store=MappingStore({"pipe_demo": module}))
        >>> list(resolver.resolve("pipe_demo", "pipe")())
        [{'x': 1}]

Attributes:
    pipeline_resolver: Process-global resolver. Core ships it unconfigured, since
        a bare install has no named pipelines.

"""

from collections.abc import Mapping
from functools import partial, update_wrapper
from json import loads
from pathlib import Path
from types import ModuleType
from typing import Literal, Protocol, cast, overload

from riko._importutils import import_or_else
from riko.exceptions import UnsupportedPipelineError
from riko.modules._subpipe import is_subpipe, mark_subpipe
from riko.types.compile import ParsedPipeDef
from riko.types.general import AsyncPipeParser, Interface, Pipeline, SyncPipeParser
from riko.types.modules import ModuleSubtype


def _as_subpipe(pipeline: Pipeline) -> Pipeline:
    """
    Returns a sub-pipeline-marked wrapper around ``pipeline``.

    The marker goes on a fresh ``partial`` because the module callable is shared
    with anyone importing the generated pipeline directly; marking it in place
    would leak sub-pipeline semantics into those calls.

    """
    if is_subpipe(pipeline):
        subpipe = pipeline
    else:
        subpipe = cast(Pipeline, partial(pipeline))
        update_wrapper(subpipe, pipeline)
        subtype = cast(ModuleSubtype, getattr(pipeline, "subtype", "source"))
        loopable = cast(bool, getattr(pipeline, "loopable", True))
        mark_subpipe(subpipe, subtype=subtype, loopable=loopable)

    return subpipe


class ModuleStore(Protocol):
    """Loads generated pipeline modules by name and returns ``None`` if absent."""

    def load(self, name: str) -> ModuleType | None: ...  # noqa: E704


class PackageStore:
    """Loads pipeline modules from a Python package."""

    def __init__(self, package: str) -> None:
        self._package = package

    def load(self, name: str) -> ModuleType | None:
        return import_or_else(f"{self._package}.{name}")


class MappingStore:
    """Loads pipeline modules from an in-memory mapping."""

    def __init__(self, modules: Mapping[str, ModuleType]) -> None:
        self._modules = dict(modules)

    def load(self, name: str) -> ModuleType | None:
        return self._modules.get(name)


class CompositeStore:
    """Loads a pipeline module from the first store that has it."""

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
        from riko.compile import parse_pipe_def  # noqa: PLC0415

        try:
            pipe_def = loads((self._directory / f"{name}.json").read_text())
        except OSError:
            parsed = None
        else:
            parsed = parse_pipe_def(pipe_def, name)

        return parsed


class PipelineResolver:
    """
    Resolves whole sub-pipelines, where the module registry resolves leaf modules.

    Lookup has two independent halves: ``store`` supplies generated Python
    pipeline modules for ``resolve``, and ``definitions`` supplies JSON pipeline
    definitions for ``load_definition``. Both are **injected** rather than
    hardcoded. This is what keeps test-only locations out of the core compiler. The
    suite points the global at its own package and directory via ``conftest``.

    """

    def __init__(
        self,
        *,
        store: ModuleStore | None = None,
        definitions: DirectoryStore | None = None,
    ) -> None:
        self._store = store
        self._definitions = definitions

    def configure(
        self,
        *,
        store: ModuleStore | None = None,
        definitions: DirectoryStore | None = None,
    ) -> None:
        """
        Replaces both halves of the lookup.

        This is a whole-state assignment, not a partial update: an omitted
        argument is set to ``None`` rather than left alone. Passing only ``store``
        also clears ``definitions``. Pass both to keep both.

        """
        self._store = store
        self._definitions = definitions

    def load(self, name: str) -> ModuleType | None:
        """Returns the generated pipeline module for ``name``, or ``None``."""
        return self._store.load(name) if self._store is not None else None

    @overload
    def resolve(  # noqa: E704
        self, name: str, interface: Literal["pipe"]
    ) -> SyncPipeParser: ...
    @overload  # noqa: E301
    def resolve(  # noqa: E704
        self, name: str, interface: Literal["async_pipe"]
    ) -> AsyncPipeParser: ...
    def resolve(self, name: str, interface: Interface) -> Pipeline:  # noqa: E301
        """
        Resolves a ``pipe_<id>`` / ``pipe:<id>`` name to its marked callable.

        Raises:
            UnsupportedPipelineError: If no store supplies ``name``, or its module
                has no ``interface`` callable.

        """
        from riko.compile import pythonise  # noqa: PLC0415

        module = self.load(pythonise(name))
        pipeline = getattr(module, interface, None) if module else None

        if pipeline is None:
            raise UnsupportedPipelineError(name)

        return _as_subpipe(pipeline)

    def load_definition(
        self, name: str, *, directory: Path | None = None
    ) -> ParsedPipeDef:
        """
        Loads a named JSON pipeline definition, overriding the configured
        directory when ``directory`` is given.

        Raises:
            UnsupportedPipelineError: If the definition cannot be found.

        """
        store = self._definitions if directory is None else DirectoryStore(directory)
        parsed = store.load(name) if store is not None else None

        if parsed is None:
            raise UnsupportedPipelineError(name)

        return parsed


pipeline_resolver: PipelineResolver = PipelineResolver()
