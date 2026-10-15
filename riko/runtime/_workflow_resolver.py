# vim: sw=4:ts=4:expandtab
"""
Provides resolution for stored workflows.

Concepts:

    workflow (``Workflow``): An in-memory graph of nodes and edges.

    workflow document (``WorkflowDocument``): A serialized ``Workflow``.

    workflow module (``WorkflowModule``): Python source defining ``pipe`` and/or
        ``async_pipe`` functions that take an item, a stream, or nothing, plus a
        ``context``. Use ``compile_workflow`` to generate one from a ``Workflow``.

    resolved workflow (``ResolvedWorkflow``): A Python module exposing ``pipe`` and/or
        ``async_pipe`` functions. They take an item, a stream, or nothing, plus a
        ``context``.

    workflow store (``WorkflowStore``): Holds stored workflows and loads one by its
        ``pipe_<id>`` name, or returns ``None``. A store is one of two kinds, depending
        on what ``load`` returns:

        module store (``ModuleStore``): Returns a ``ResolvedWorkflow``.

            ``PackageStore``: Lazily imports a package's ``pipe_<id>.py`` file (i.e., a
                saved ``WorkflowModule``) as a ``ResolvedWorkflow``.

            ``MappingStore``: Returns a ``ResolvedWorkflow`` from a mapping its caller
                supplies, keyed by ``pipe_<id>`` name.

            ``CompositeStore``: Combines several ``ModuleStore`` objects. The first one
                that has the name wins.

        document store (``DocumentStore``): Returns the ``Workflow`` a
            ``WorkflowDocument`` describes.

            ``DirectoryStore``: Reads a ``WorkflowDocument``, stored as a
                ``pipe_<id>.json`` file in a directory, when its name is looked up.

    stored workflow: A ``WorkflowStore`` entry looked up by its ``pipe_<id>`` name. It
        has no type of its own. Depending on the store, it is a ``WorkflowDocument``, a
        file imported as a ``ResolvedWorkflow``, or a ``ResolvedWorkflow`` in a mapping.

    workflow resolver (``WorkflowResolver``): Converts a stored workflow's ``pipe_<id>``
        name, or its ``pipe:<id>`` alias, to a ``ResolvedWorkflow``. A ``PackageStore``
        imports it and a ``MappingStore`` returns it as is. For a ``DocumentStore``, the
        resolver creates a ``ResolvedWorkflow`` whose ``pipe`` runs the store's
        ``Workflow``.

        If a name exists in both store kinds, the ``ModuleStore`` wins.

Attributes:

    workflow_resolver: Process-global resolver. Core ships it with no stores
        registered, since a bare install has no stored workflows.

Examples:

    Basic usage::

        >>> from pathlib import Path
        >>> from tempfile import TemporaryDirectory
        >>>
        >>> document = '{"nodes": [{"name": "forever"}]}'
        >>> reset_workflow_resolver()
        >>> with TemporaryDirectory() as tmp:
        ...     _ = (Path(tmp) / "pipe_demo.json").write_text(document)
        ...     register_workflow_store(directory=Path(tmp))
        ...     pipe = workflow_resolver.require("pipe:demo")
        ...     next(iter(pipe()))
        {'forever': True}
        >>> reset_workflow_resolver()

"""

from __future__ import annotations

from functools import partial
from types import ModuleType
from typing import TYPE_CHECKING, Literal, cast, overload

from riko.base._strutils import pythonise
from riko.base.exceptions import UnsupportedWorkflowError
from riko.types._compiler import is_pipe_id
from riko.types._workflow import ResolvedWorkflow
from riko.types._wrappers import is_subpipe

from ._importutils import load_interfaces, require_interface
from ._workflow_pipes import build_workflow_pipes, workflow
from ._workflow_stores import DirectoryStore, PackageStore

if TYPE_CHECKING:
    from pathlib import Path

    from riko.definitions._workflow import Workflow
    from riko.types._wrappers import (
        AsyncModuleWrapper,
        Dispatcher,
        Interface,
        ModuleWrapper,
        SyncModuleWrapper,
    )
    from riko.types.modules import ModuleSubtype

    from ._resolver import ResolverDispatcher
    from ._workflow_stores import DocumentStore, ModuleStore


def _build_resolved_workflow(
    name: str, flow: Workflow, dispatcher: Dispatcher
) -> ResolvedWorkflow:
    """
    Builds a ``ResolvedWorkflow`` whose ``pipe``/``async_pipe`` run ``flow``.

    ``flow`` is the ``Workflow`` a ``WorkflowDocument`` (serialized ``Workflow``)
    describes. Building the module runs nothing. Its ``pipe`` runs ``flow`` when
    called.

    Args:

        name: The stored workflow's ``pipe_<id>`` name.

        flow: The ``Workflow`` the pipes run.

        dispatcher: Finds each node's pipe by name, whether a module such as ``fetch``
            or a stored workflow's ``pipe_<id>``.

    Returns:

        The ``ResolvedWorkflow`` (a module exposing ``pipe`` and ``async_pipe``).

    Examples:

        >>> from riko import Workflow
        >>> from riko.runtime._resolver import dispatcher
        >>>
        >>> flow = Workflow.parse('{"nodes": [{"name": "forever"}]}')
        >>> resolved = _build_resolved_workflow("pipe_demo", flow, dispatcher)
        >>> resolved.DEPENDENCIES
        ['forever']
        >>> next(iter(resolved.pipe()))
        {'forever': True}

    """
    inputs: dict[str, object] = dict(flow.inputs)
    dependencies = sorted({node.name for node in flow.module_nodes.values()})
    subtype: ModuleSubtype = "transformer" if inputs else "source"
    args = (flow, dispatcher)
    pipes = build_workflow_pipes(*args, *dependencies, inputs=inputs, subtype=subtype)
    module = ModuleType(name, f"Pipe {name} built from its workflow document.")
    resolved = ResolvedWorkflow(module)
    vars(resolved).update(
        INPUTS=inputs,
        DEPENDENCIES=dependencies,
        flow=flow,
        pipe=pipes.sync_pipe,
        async_pipe=pipes.async_pipe,
    )
    return resolved


class WorkflowResolver:
    """
    Converts a stored workflow's ``pipe_<id>`` name to a ``ResolvedWorkflow``.

    ``pipe:<id>`` is accepted as an alias. A stored workflow is a ``WorkflowStore``
    entry looked up by its ``pipe_<id>`` name.

    A ``ModuleStore`` returns a ``ResolvedWorkflow`` (a module exposing ``pipe`` and/or
    ``async_pipe``) as is. For a ``DocumentStore``, the resolver creates a
    ``ResolvedWorkflow`` whose ``pipe`` runs the store's ``Workflow``. If a name exists
    in both store kinds, the ``ModuleStore`` wins. Built-in and registered modules, such
    as ``fetch``, are looked up through ``ModuleRegistry`` instead.

    Examples:

        >>> from types import ModuleType
        >>>
        >>> from riko.runtime._workflow_stores import MappingStore
        >>>
        >>> module = ModuleType("pipe_demo")
        >>> module.pipe = lambda stream=None, **kwargs: iter([{"x": 1}])
        >>> store = MappingStore({"pipe_demo": module})
        >>> resolver = WorkflowResolver(module_store=store)
        >>> list(resolver.require("pipe_demo")())
        [{'x': 1}]

    """

    def __init__(
        self,
        *,
        module_store: ModuleStore | None = None,
        document_store: DocumentStore | None = None,
    ) -> None:
        self._module_store = module_store
        self._document_store = document_store
        self._resolved_documents: dict[str, ResolvedWorkflow] = {}
        self._dispatcher: ResolverDispatcher | None = None

    def register_dispatcher(self, dispatcher: ResolverDispatcher) -> None:
        """
        Registers the dispatcher that runs the ``Workflow`` a ``DocumentStore`` returns.

        When a ``ResolvedWorkflow`` created from that ``Workflow`` runs, each node finds
        its pipe through this dispatcher. The process-global ``dispatcher`` registers
        itself here, since it also sends ``pipe_<id>`` names to this resolver.

        Args:

            dispatcher: Finds each node's pipe by name, whether a module such as
                ``fetch`` or a stored workflow's ``pipe_<id>``.

        Examples:

            >>> from riko.runtime._resolver import dispatcher
            >>>
            >>> resolver = WorkflowResolver()
            >>> resolver.register_dispatcher(dispatcher)

        """
        self._dispatcher = dispatcher
        self._resolved_documents.clear()

    def _require_dispatcher(self, name: str) -> ResolverDispatcher:
        if (dispatcher := self._dispatcher) is None:
            msg = "no dispatcher is registered to run it"
            raise UnsupportedWorkflowError(name, msg)

        return dispatcher

    @staticmethod
    def _resolve_store[T](
        current: T | None, value: T | None, kind: str, replace: bool
    ) -> T | None:
        if value is not None and current is not None and not replace:
            raise ValueError(f"workflow {kind} already registered")

        return current if value is None else value

    def register(
        self,
        *,
        module_store: ModuleStore | None = None,
        document_store: DocumentStore | None = None,
        replace: bool = False,
    ) -> None:
        """
        Registers a ``ModuleStore`` and/or a ``DocumentStore``.

        A ``ModuleStore`` returns a ``ResolvedWorkflow`` (a module exposing ``pipe``
        and/or ``async_pipe``). A ``DocumentStore`` returns the ``Workflow`` a
        ``WorkflowDocument`` (serialized ``Workflow``) describes.

        Args:

            module_store: The ``ModuleStore`` to register.

            document_store: The ``DocumentStore`` to register.

            replace: Whether to replace a store of the same kind that is already
                registered.

        Raises:

            ValueError: If a store of the same kind is already registered and
                ``replace`` is False.

        Examples:

            >>> from riko.runtime._workflow_stores import MappingStore
            >>>
            >>> resolver = WorkflowResolver()
            >>> resolver.register(module_store=MappingStore({}))
            >>> resolver.register(module_store=MappingStore({}), replace=True)
            >>> resolver.register(module_store=MappingStore({}))
            Traceback (most recent call last):
            ...
            ValueError: workflow module store already registered

        """
        resolve_store = partial(self._resolve_store, replace=replace)
        margs = (self._module_store, module_store)
        dargs = (self._document_store, document_store)

        self._module_store = resolve_store(*margs, "module store")
        self._document_store = resolve_store(*dargs, "document store")
        self._resolved_documents.clear()

    def reset(self) -> None:
        """
        Clears the registered ``ModuleStore`` and ``DocumentStore``.

        Chiefly used for test isolation.

        Examples:

            >>> from types import ModuleType
            >>> from riko.runtime._workflow_stores import MappingStore
            >>>
            >>> store = MappingStore({"pipe_demo": ModuleType("pipe_demo")})
            >>> resolver = WorkflowResolver(module_store=store)
            >>> resolver.reset()
            >>> resolver.load("pipe_demo") is None
            True

        """
        self._module_store = None
        self._document_store = None
        self._resolved_documents.clear()

    def is_compatible(self, name: str) -> bool:
        """
        Checks whether ``name`` names a stored workflow.

        Args:

            name: A module name such as ``fetch``, or a stored workflow's ``pipe_<id>``
                name or ``pipe:<id>`` alias.

        Returns:

            Whether this resolver handles ``name`` (otherwise ``ModuleRegistry`` does).

        Examples:

            >>> resolver = WorkflowResolver()
            >>> resolver.is_compatible("pipe:demo"), resolver.is_compatible("fetch")
            (True, False)

        """
        return is_pipe_id(name)

    def _load_resolved_document(self, name: str) -> ResolvedWorkflow | None:
        module = self._resolved_documents.get(name)
        document_store = self._document_store
        flow = None

        if module is None and document_store is not None:
            flow = document_store.load(name)

        if flow is not None:
            dispatcher = self._require_dispatcher(name)
            module = _build_resolved_workflow(name, flow, dispatcher)
            self._resolved_documents[name] = module

        return module

    def load(self, name: str) -> ResolvedWorkflow | None:
        """
        Loads the ``ResolvedWorkflow`` for ``name``.

        For a ``DocumentStore``, the ``ResolvedWorkflow`` is created on first use and
        reused afterward, but not run.

        Args:

            name: The stored workflow's ``pipe_<id>`` name (``pipe:<id>`` is accepted
                and read as ``pipe_<id>``).

        Returns:

            The ``ResolvedWorkflow``, or ``None`` if no store supplies ``name``.

        Raises:

            InvalidPipelineError: If the ``DocumentStore`` holds a malformed
                ``WorkflowDocument`` named ``name``.

            UnsupportedWorkflowError: If the ``DocumentStore`` supplies ``name`` but no
                dispatcher is registered to run it.

        Examples:

            >>> from types import ModuleType
            >>> from riko.runtime._workflow_stores import MappingStore
            >>>
            >>> store = MappingStore({"pipe_demo": ModuleType("pipe_demo")})
            >>> resolver = WorkflowResolver(module_store=store)
            >>> resolver.load("pipe:demo").__name__
            'pipe_demo'
            >>> resolver.load("pipe_other") is None
            True

        """
        pipe_id = pythonise(name)
        store = self._module_store
        module = None if store is None else store.load(pipe_id)
        return self._load_resolved_document(pipe_id) if module is None else module

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
        Finds a stored workflow's pipe by its ``pipe_<id>`` name, or raises.

        Args:

            name: The stored workflow's ``pipe_<id>`` name (``pipe:<id>`` is accepted
                and read as ``pipe_<id>``).

            is_async: Whether to find ``async_pipe`` instead of ``pipe``.

        Returns:

            The pipe, tagged as a stored workflow's pipe, which lets ``loop`` run it
            without the ``conf`` and ``emit`` it passes other embeds.

        Raises:

            InvalidPipelineError: If the ``DocumentStore`` holds a malformed
                ``WorkflowDocument`` named ``name``.

            UnsupportedWorkflowError: If no store supplies ``name``, its
                ``ResolvedWorkflow`` lacks ``pipe`` (or ``async_pipe`` when
                ``is_async``), or the ``DocumentStore`` supplies it but no dispatcher
                is registered to run it.

        Examples:

            >>> from types import ModuleType
            >>> from riko.runtime._workflow_stores import MappingStore
            >>>
            >>> module = ModuleType("pipe_demo")
            >>> module.pipe = lambda item=None, **kwargs: iter([{"x": 1}])
            >>> store = MappingStore({"pipe_demo": module})
            >>> resolver = WorkflowResolver(module_store=store)
            >>> pipe = resolver.require("pipe:demo")
            >>> pipe.type, list(pipe())
            ('pipe', [{'x': 1}])

        """
        kwargs = {"is_async": is_async, "builtin": False}
        pipe = require_interface(pythonise(name), loader=self.load, **kwargs)

        if is_subpipe(pipe):
            tagged = pipe
        else:
            subtype = cast("ModuleSubtype", getattr(pipe, "subtype", "source"))
            loopable = cast("bool", getattr(pipe, "loopable", True))
            tag = workflow(subtype=subtype, loopable=loopable, isasync=is_async)
            tagged = tag(pipe)

        return tagged

    def require_interfaces(self, name: str) -> frozenset[Interface]:
        """
        Finds which of a stored workflow's sync and async interfaces are defined.

        Args:

            name: The stored workflow's ``pipe_<id>`` name to inspect
                (``pipe:<id>`` is accepted and read as ``pipe_<id>``).

        Returns:

            The subset of ``pipe``/``async_pipe`` its ``ResolvedWorkflow`` exposes.

        Raises:

            InvalidPipelineError: If the ``DocumentStore`` holds a malformed
                ``WorkflowDocument`` named ``name``.

            UnsupportedWorkflowError: If no store supplies ``name``, or the
                ``DocumentStore`` supplies it but no dispatcher is registered to run it.

        Examples:

            >>> from types import ModuleType
            >>> from riko.runtime._workflow_stores import MappingStore
            >>>
            >>> module = ModuleType("pipe_demo")
            >>> module.pipe = lambda item=None, **kwargs: iter([])
            >>> store = MappingStore({"pipe_demo": module})
            >>> resolver = WorkflowResolver(module_store=store)
            >>> sorted(resolver.require_interfaces("pipe_demo"))
            ['pipe']

        """
        return load_interfaces(pythonise(name), builtin=False, loader=self.load)

    def load_workflow(self, name: str, *, directory: Path | None = None) -> Workflow:
        """
        Loads ``name``'s ``Workflow`` from a ``DocumentStore`` without running it.

        Args:

            name: The stored workflow's ``pipe_<id>`` name (``pipe:<id>`` is accepted
                and read as ``pipe_<id>``).

            directory: A directory of ``WorkflowDocument`` files to read from instead of
                the registered ``DocumentStore``.

        Returns:

            The ``Workflow`` the ``WorkflowDocument`` (serialized ``Workflow``)
            describes.

        Raises:

            InvalidPipelineError: If the ``WorkflowDocument`` named ``name`` is
                malformed.

            UnsupportedWorkflowError: If no ``DocumentStore`` is registered (and no
                ``directory`` is given), or it has no ``WorkflowDocument`` named
                ``name``.

        Examples:

            >>> from pathlib import Path
            >>> from tempfile import TemporaryDirectory
            >>>
            >>> document = '{"nodes": [{"name": "forever"}]}'
            >>> resolver = WorkflowResolver()
            >>> with TemporaryDirectory() as tmp:
            ...     directory = Path(tmp)
            ...     _ = (directory / "pipe_demo.json").write_text(document)
            ...     flow = resolver.load_workflow("pipe:demo", directory=directory)
            >>> [node.name for node in flow.nodes.values()]
            ['forever']

        """
        pipe_id = pythonise(name)
        store = self._document_store if directory is None else DirectoryStore(directory)

        if store is None:
            raise UnsupportedWorkflowError(pipe_id, "no document store is registered")

        if (flow := store.load(pipe_id)) is None:
            raise UnsupportedWorkflowError(pipe_id, "no WorkflowDocument has that name")

        return flow


workflow_resolver: WorkflowResolver = WorkflowResolver()


def register_workflow_store(
    *,
    package: str | ModuleType | None = None,
    directory: Path | None = None,
    replace: bool = False,
) -> None:
    """
    Registers workflow stores (``WorkflowStore``) on the process-global resolver.

    Args:

        package: A package, or its import path, whose ``pipe_<id>.py`` files are each
            imported as a ``ResolvedWorkflow`` (a module exposing ``pipe`` and/or
            ``async_pipe``).

        directory: A directory of ``WorkflowDocument`` (serialized ``Workflow``) files,
            each stored as ``pipe_<id>.json``.

        replace: Whether to replace a store of the same kind that is already
            registered.

    Raises:

        ModuleNotFoundError: If ``package`` is an import path that does not exist.
        ValueError: If ``package`` is a module rather than a package, or a store of
            the same kind is already registered and ``replace`` is False.

    Examples:

        >>> import riko.modules
        >>>
        >>> reset_workflow_resolver()
        >>> register_workflow_store(package="riko.modules")
        >>> register_workflow_store(package=riko.modules, replace=True)
        >>> reset_workflow_resolver()

    """
    module_store = None if package is None else PackageStore(package)
    document_store = None if directory is None else DirectoryStore(directory)
    workflow_resolver.register(
        module_store=module_store, document_store=document_store, replace=replace
    )


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
    "WorkflowResolver",
    "register_workflow_store",
    "reset_workflow_resolver",
    "workflow_resolver",
]
