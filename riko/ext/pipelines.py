# vim: sw=4:ts=4:expandtab
"""
riko.ext.pipelines
~~~~~~~~~~~~~~~~~~~
Resolution of *named pipelines* (``pipe_*``) — the counterpart to the module
registry. Where the registry resolves leaf module implementations, this resolves
whole sub-pipelines: a generated Python module found via a pluggable
``ModuleStore``, or (as a fallback) a JSON definition compiled from a configured
directory.

The locations are **injected**, not hardcoded: core ships an empty
``pipeline_resolver`` (a bare install has no named pipelines), and the test suite
configures it with a ``PackageStore("tests.pypipelines")`` + ``tests/pipelines``
directory via ``conftest``. This is what keeps the ``tests.*`` paths out of the
core compiler.
"""

from collections.abc import Mapping
from functools import partial, update_wrapper
from importlib import import_module
from json import loads
from pathlib import Path
from types import ModuleType
from typing import Literal, Protocol, cast, overload

from riko.exceptions import UnsupportedPipelineError
from riko.modules._subpipe import is_subpipe, mark_subpipe
from riko.types.compile import ParsedPipeDef
from riko.types.general import AsyncPipeParser, Interface, Pipeline, SyncPipeParser
from riko.types.modules import ModuleSubtype


def _as_subpipe(pipeline: Pipeline) -> Pipeline:
    """
    Mark a resolved ``pipe_*`` callable as a sub-pipeline via a fresh wrapper,
    leaving the original module callable unmutated.
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
    """Locates a generated pipeline module by name (``None`` if absent)."""

    def load(self, name: str) -> ModuleType | None: ...  # noqa: E704


class PackageStore:
    """Import ``<package>.<name>`` — the shape generated pipelines ship in."""

    def __init__(self, package: str) -> None:
        self._package = package

    def load(self, name: str) -> ModuleType | None:
        target = f"{self._package}.{name}"

        try:
            module = import_module(target)
        except ModuleNotFoundError as e:
            if missing_name := e.name:
                is_target = target == missing_name

                if not (is_target or target.startswith(f"{missing_name}.")):
                    raise

            module = None

        return module


class MappingStore:
    """Serve pipeline modules from an in-memory ``{name: module}`` mapping."""

    def __init__(self, modules: Mapping[str, ModuleType]) -> None:
        self._modules = dict(modules)

    def load(self, name: str) -> ModuleType | None:
        return self._modules.get(name)


class CompositeStore:
    """Try each store in order; first hit wins."""

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
    Compile ``<directory>/<name>.json`` into a ``ParsedPipeDef`` (``None`` if
    the file is absent). The definition is interface-agnostic — the caller
    builds it sync (``build_pipeline``) or async (``abuild_pipeline``).
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
        self._store = store
        self._definitions = definitions

    def load(self, name: str) -> ModuleType | None:
        """The generated pipeline module for ``name``, or ``None``."""
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
        Resolve a ``pipe_<id>`` / ``pipe:<id>`` sub-pipeline to its marked
        callable — the counterpart to ``ModuleRegistry.resolve``.
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
        """Compile ``name``'s JSON definition, raising if it can't be found."""
        store = self._definitions if directory is None else DirectoryStore(directory)
        parsed = store.load(name) if store is not None else None

        if parsed is None:
            raise UnsupportedPipelineError(name)

        return parsed


pipeline_resolver: PipelineResolver = PipelineResolver()
