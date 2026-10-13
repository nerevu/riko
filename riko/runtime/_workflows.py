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

from functools import partial, update_wrapper
from importlib import import_module
from inspect import isasyncgenfunction
from types import ModuleType
from typing import TYPE_CHECKING, Literal, NamedTuple, Protocol, cast, overload

from riko.bado.itertools import as_async
from riko.base._config import SUBPIPE_TYPE
from riko.base._imports import import_or_else
from riko.base._strutils import pythonise
from riko.base.exceptions import UnsupportedWorkflowError
from riko.definitions._composition import PipelineDefinition
from riko.definitions._nodes import ModuleNode
from riko.definitions._workflow import Workflow
from riko.types._compiler import is_pipe_id
from riko.types._enums import DocumentShape, ExecutionMode
from riko.types._guards import is_async_callable
from riko.types._workflow import ResolvedWorkflow
from riko.types._wrappers import is_subpipe, stamp_wrapper_meta

from ._execution_plan import arun_pipeline, run_pipeline
from ._importutils import load_interfaces, require_interface

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator, Mapping
    from pathlib import Path

    from riko.definitions._context import Context
    from riko.types._streams import SourceLike
    from riko.types._wrappers import (
        AsyncFunc,
        AsyncModuleWrapper,
        AsyncSubPipe,
        Func,
        Interface,
        ModuleWrapper,
        SubPipe,
        SyncModuleWrapper,
        SyncSubPipe,
    )
    from riko.types.modules import ModuleSubtype

    from ._resolver import ResolverDispatcher


class SubPipes(NamedTuple):
    """
    Pairs the sync and async pipes ``build_workflow_pipes`` builds for one workflow.

    Attributes:

        sync_pipe: The sync pipe.

        async_pipe: The async pipe.

    Examples:

        >>> from riko.definitions._workflow import Workflow
        >>> from riko.runtime._resolver import dispatcher
        >>>
        >>> pipes = build_workflow_pipes(Workflow(), dispatcher, subtype="source")
        >>> pipes.sync_pipe.type, pipes.async_pipe.type
        ('pipe', 'pipe')

    """

    sync_pipe: SyncSubPipe
    async_pipe: AsyncSubPipe


@overload
def mark_subpipe(  # noqa: E704  # pyright: ignore[reportOverlappingOverload]
    pipe: AsyncFunc,
    *,
    subtype: ModuleSubtype = ...,
    loopable: bool = ...,
    isasync: bool | None = ...,
) -> AsyncSubPipe: ...
@overload  # noqa: E302
def mark_subpipe(  # noqa: E704
    pipe: Func,
    *,
    subtype: ModuleSubtype = ...,
    loopable: bool = ...,
    isasync: bool | None = ...,
) -> SyncSubPipe: ...
def mark_subpipe(  # noqa: E302
    pipe: Func,
    *,
    subtype: ModuleSubtype = "transformer",
    loopable: bool = True,
    isasync: bool | None = None,
) -> SubPipe:
    """
    Tags ``pipe`` as a stored workflow's pipe.

    ``loop`` runs a tagged pipe without the ``conf`` and ``emit`` it passes other embeds
    (a stored workflow's nodes carry their own conf). Workflow modules
    (``WorkflowModule``) tag their pipes like this either directly or through
    ``build_workflow_pipes``.

    Args:

        pipe: The callable to tag.

        subtype: How the pipe is tagged. E.g., "source" (needs no input) or
            "transformer" (takes an item).

        loopable: The pipe's ``loopable`` discovery flag. ``loop`` embeds a tagged pipe
            either way.

        isasync: Whether ``pipe`` is the async interface. Defaults to ``True`` for an
            async function or an async generator function.

    Returns:

        A tagged ``pipe``. The tags are set on ``pipe`` without copying.

    Examples:

        >>> def pipe(item=None, **kwargs):
        ...     return iter([])
        >>>
        >>> subpipe = mark_subpipe(pipe, subtype="source")
        >>> subpipe is pipe, subpipe.type, subpipe.subtype
        (True, 'pipe', 'source')

    """
    name: str = getattr(pipe, "__name__", SUBPIPE_TYPE)

    if isasync is None:
        isasync = is_async_callable(pipe) or isasyncgenfunction(pipe)

    stamp_wrapper_meta(
        pipe,
        name=name,
        module_type=SUBPIPE_TYPE,
        subtype=subtype,
        subtypes={subtype},
        pollable=False,
        loopable=loopable,
        isasync=isasync,
    )

    return cast("SubPipe", pipe)


def _as_subpipe(pipe: ModuleWrapper, *, isasync: bool) -> SubPipe:
    """
    Tags ``pipe`` as a stored workflow's pipe so that ``loop`` runs it as is.

    A stored workflow's nodes carry their own conf, so when ``loop`` finds a pipe whose
    ``type`` is ``"pipe"``, it runs it without the ``conf`` and ``emit`` it passes other
    embeds.

    Args:

        pipe: The stored workflow's interface.
        isasync: Whether ``pipe`` is the async interface.

    Returns:

        ``pipe`` when it is already tagged, otherwise a tagged copy that keeps its
        ``subtype`` and ``loopable`` flags.

    """
    if is_subpipe(pipe):
        subpipe = pipe
    else:
        subpipe = cast("SubPipe", partial(pipe))
        update_wrapper(subpipe, pipe)
        subtype = cast("ModuleSubtype", getattr(pipe, "subtype", "source"))
        loopable = cast("bool", getattr(pipe, "loopable", True))
        mark_subpipe(subpipe, subtype=subtype, loopable=loopable, isasync=isasync)

    return subpipe


def build_workflow_pipes(
    workflow: Workflow,
    dispatcher: ResolverDispatcher,
    *dependencies: str,
    subtype: ModuleSubtype,
    inputs: Mapping[str, object] | None = None,
) -> SubPipes:
    """
    Builds the ``pipe`` and ``async_pipe`` callables that run a ``Workflow``.

    Each callable takes one item, a stream, or nothing. Normally the callable runs a
    ``workflow`` and yield its default output. When the ``Context`` asks to describe
    the workflow instead, nothing runs.

    With ``describe_input``, ``pipe`` returns the input declarations and ``async_pipe``
    yields them as a single item. With ``describe_dependencies``, ``pipe`` returns the
    ``dependencies`` names as a list and ``async_pipe`` yields each name. With both,
    ``pipe`` returns ``{"inputs": ..., "dependencies": [...]}`` and ``async_pipe``
    yields it as a single item.

    Args:

        workflow: The ``Workflow`` the pipes run.

        dispatcher: Finds each node's pipe by name, whether a module such as
            ``fetch`` or a stored workflow's ``pipe_<id>``.

        dependencies: The names of the modules and stored workflows, such as ``fetch``
            or a ``pipe_<id>``, that the workflow's nodes use. Reported when describing
            dependencies.

        subtype: How the pipe callables are tagged. E.g., ``"source"`` (needs no input)
            or ``"transformer"`` (takes an item).

        inputs: The workflow's input declarations. Reported when describing inputs.

    Returns:

        The sync and async callables. Each is tagged as a stored workflow's pipe, which
        lets ``loop`` run it without the ``conf`` and ``emit`` it passes other embeds.

    Examples:

        >>> from riko.definitions._workflow import Workflow
        >>> from riko.runtime._resolver import dispatcher
        >>>
        >>> pipe = build_workflow_pipes(
        ...     Workflow(), dispatcher, subtype="transformer",
        ... ).sync_pipe
        >>> list(pipe([{"x": 1}]))
        [{'x': 1}]

    """
    inputs = {} if inputs is None else dict(inputs)
    description = {"inputs": inputs, "dependencies": list(dependencies)}

    def pipe(
        item: SourceLike | None = None, context: Context | None = None, **_: object
    ) -> Iterator[object] | dict[str, object] | list[str]:
        if context is None or context.mode is ExecutionMode.RUN:
            definition = PipelineDefinition(workflow, source=item, context=context)
            result: Iterator[object] | dict[str, object] | list[str]
            result = run_pipeline(definition, dispatcher)
        elif context.mode is ExecutionMode.DESCRIBE:
            result = description
        elif context.describe_input:
            result = inputs
        else:
            result = list(dependencies)

        return result

    def async_pipe(
        item: SourceLike | None = None, context: Context | None = None, **_: object
    ) -> AsyncIterator[object]:
        if context is None or context.mode is ExecutionMode.RUN:
            definition = PipelineDefinition(workflow, source=item, context=context)
            result: AsyncIterator[object] = arun_pipeline(definition, dispatcher)
        elif context.mode is ExecutionMode.DESCRIBE:
            result = as_async([description])
        elif context.describe_input:
            result = as_async([inputs])
        else:
            result = as_async(dependencies)

        return result

    sync_pipe = mark_subpipe(pipe, subtype=subtype)
    _async_pipe = mark_subpipe(async_pipe, subtype=subtype, isasync=True)
    return SubPipes(sync_pipe, cast("AsyncSubPipe", _async_pipe))


def _build_resolved_workflow(
    name: str, workflow: Workflow, dispatcher: ResolverDispatcher
) -> ResolvedWorkflow:
    """
    Builds a ``ResolvedWorkflow`` whose ``pipe``/``async_pipe`` run ``workflow``.

    ``workflow`` is the ``Workflow`` a ``WorkflowDocument`` (serialized ``Workflow``)
    describes. Building the module runs nothing. Its ``pipe`` runs ``workflow`` when
    called.

    Args:

        name: The stored workflow's ``pipe_<id>`` name.

        workflow: The ``Workflow`` to run.

        dispatcher: Finds each node's pipe by name, whether a module such as ``fetch``
            or a stored workflow's ``pipe_<id>``.

    Returns:

        The ``ResolvedWorkflow`` (a module exposing ``pipe`` and ``async_pipe``).

    Examples:

        >>> from riko.runtime._resolver import dispatcher
        >>> from riko import Workflow
        >>>
        >>> workflow = Workflow.parse('{"nodes": [{"name": "forever"}]}')
        >>> resolved = _build_resolved_workflow("pipe_demo", workflow, dispatcher)
        >>> resolved.DEPENDENCIES
        ['forever']
        >>> next(iter(resolved.pipe()))
        {'forever': True}

    """
    inputs: dict[str, object] = dict(workflow.inputs)
    nodes = workflow.nodes.values()
    dependencies = sorted({node.name for node in nodes if isinstance(node, ModuleNode)})
    subtype: ModuleSubtype = "transformer" if inputs else "source"
    args = (workflow, dispatcher)
    pipes = build_workflow_pipes(*args, *dependencies, inputs=inputs, subtype=subtype)
    module = ModuleType(name, f"Pipe {name} built from its workflow document.")
    resolved = ResolvedWorkflow(module)
    vars(resolved).update(
        INPUTS=inputs,
        DEPENDENCIES=dependencies,
        workflow=workflow,
        pipe=pipes.sync_pipe,
        async_pipe=pipes.async_pipe,
    )
    return resolved


class WorkflowStore[T](Protocol):
    """
    Loads a stored workflow (an entry looked up by its ``pipe_<id>`` name).

    ``T`` is what ``load`` returns: a ``ResolvedWorkflow`` (a module exposing ``pipe``
    and/or ``async_pipe``) for a ``ModuleStore``, or a ``Workflow`` (the in-memory
    graph) for a ``DocumentStore``. A store returns ``None`` when it has nothing of
    that name.

    Examples:

        >>> class EmptyStore:
        ...     def load(self, name):
        ...         return None
        >>>
        >>> resolver = WorkflowResolver(module_store=EmptyStore())
        >>> resolver.load("pipe_demo") is None
        True

    """

    def load(self, name: str) -> T | None:
        """
        Loads the stored workflow named ``name``.

        Args:

            name: The stored workflow's ``pipe_<id>`` name.

        Returns:

            What the store holds under ``name``, or ``None`` if it has nothing of that
            name.

        """
        ...


type ModuleStore = WorkflowStore[ResolvedWorkflow]
type DocumentStore = WorkflowStore[Workflow]


class PackageStore:
    """
    Imports a package's ``pipe_<id>.py`` file as a ``ResolvedWorkflow`` on lookup.

    Each file must define ``pipe`` and/or ``async_pipe`` functions that take an item or
    a stream plus a ``context``. The package itself is imported when the store is
    built, so a mistyped import path fails there rather than looking like a missing
    workflow.

    Args:

        package: The package or its import path.

    Raises:

        ModuleNotFoundError: If ``package`` is an import path that does not exist.
        ValueError: If ``package`` is a module rather than a package.

    Examples:

        >>> store = PackageStore("examples.pyworkflows")
        >>> store.load("pipe_timezone").__name__
        'examples.pyworkflows.pipe_timezone'
        >>> store.load("pipe_missing") is None
        True

    """

    def __init__(self, package: str | ModuleType) -> None:
        module = import_module(package) if isinstance(package, str) else package

        if not hasattr(module, "__path__"):
            raise ValueError(f"{module.__name__!r} is a module, not a package")

        self._package = module.__name__

    def load(self, name: str) -> ResolvedWorkflow | None:
        """
        Imports the package's file named ``name``.

        Args:

            name: The stored workflow's ``pipe_<id>`` name.

        Returns:

            The imported ``ResolvedWorkflow``, or ``None`` if the package has no such
            file.

        Raises:

            ModuleNotFoundError: If the file exists but imports a module that does not.

        """
        module = import_or_else(f"{self._package}.{name}", strict=True)
        return None if module is None else ResolvedWorkflow(module)


class MappingStore:
    """
    Looks up a ``ResolvedWorkflow`` in a mapping its caller supplies.

    Nothing is imported. Each ``ResolvedWorkflow`` (a module exposing ``pipe`` and/or
    ``async_pipe``) is returned as given.

    Args:

        modules: Each resolved workflow (a ``types.ModuleType``), keyed by its stored
            workflow's ``pipe_<id>`` name.

    Examples:

        >>> module = ModuleType("pipe_demo")
        >>> store = MappingStore({"pipe_demo": module})
        >>> store.load("pipe_demo") is module
        True
        >>> store.load("pipe_other") is None
        True

    """

    def __init__(self, modules: Mapping[str, ModuleType]) -> None:
        self._modules = {k: ResolvedWorkflow(v) for k, v in modules.items()}

    def load(self, name: str) -> ResolvedWorkflow | None:
        """
        Looks up ``name`` in the mapping.

        Args:

            name: The stored workflow's ``pipe_<id>`` name.

        Returns:

            The ``ResolvedWorkflow``, or ``None`` if the mapping has no such key.

        """
        return self._modules.get(name)


class CompositeStore:
    """
    Combines several ``ModuleStore`` objects into one.

    ``load`` returns the ``ResolvedWorkflow`` (a module exposing ``pipe`` and/or
    ``async_pipe``) from the first store that has the name.

    Args:

        *stores: The ``ModuleStore`` objects, in priority order.

    Examples:

        >>> first = MappingStore({"pipe_a": ModuleType("pipe_a")})
        >>> second = MappingStore({"pipe_b": ModuleType("pipe_b")})
        >>> store = CompositeStore(first, second)
        >>> store.load("pipe_b").__name__
        'pipe_b'

    """

    def __init__(self, *stores: ModuleStore) -> None:
        self._stores = stores

    def load(self, name: str) -> ResolvedWorkflow | None:
        """
        Loads ``name`` from the first store that has it.

        Args:

            name: The stored workflow's ``pipe_<id>`` name.

        Returns:

            The ``ResolvedWorkflow``, or ``None`` if no store has ``name``.

        """
        found = None

        for store in self._stores:
            if (found := store.load(name)) is not None:
                break

        return found


class DirectoryStore:
    """
    Reads a ``WorkflowDocument``, stored as a ``pipe_<id>.json`` file, on lookup.

    As a ``DocumentStore``, ``load`` returns the ``Workflow`` a ``WorkflowDocument``
    (serialized ``Workflow``) describes. The ``Workflow`` has no ``pipe`` to call.
    Instead, ``WorkflowResolver`` creates a ``ResolvedWorkflow`` from it.

    Args:

        directory: The directory holding the ``pipe_<id>.json`` files.

    Examples:

        >>> from pathlib import Path
        >>> from tempfile import TemporaryDirectory
        >>>
        >>> document = '{"nodes": [{"name": "forever"}]}'
        >>> with TemporaryDirectory() as tmp:
        ...     _ = (Path(tmp) / "pipe_demo.json").write_text(document)
        ...     store = DirectoryStore(Path(tmp))
        ...     workflow = store.load("pipe_demo")
        ...     missing = store.load("pipe_missing")
        >>> [node.name for node in workflow.nodes.values()], missing
        (['forever'], None)

    """

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def load(self, name: str) -> Workflow | None:
        """
        Reads the ``Workflow`` stored as ``<name>.json``.

        Args:

            name: The stored workflow's ``pipe_<id>`` name.

        Returns:

            The ``Workflow``, or ``None`` if the file does not exist.

        Raises:

            InvalidPipelineError: If the file is not a valid ``WorkflowDocument``.

        """
        try:
            text = (self._directory / f"{name}.json").read_text()
        except FileNotFoundError:
            parsed = None
        else:
            parsed = Workflow.parse(text, shape=DocumentShape.V2)

        return parsed


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
        workflow = None

        if module is None and document_store is not None:
            workflow = document_store.load(name)

        if workflow is not None:
            dispatcher = self._require_dispatcher(name)
            module = _build_resolved_workflow(name, workflow, dispatcher)
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
        return _as_subpipe(pipe, isasync=is_async)

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
            ...     workflow = resolver.load_workflow("pipe:demo", directory=directory)
            >>> [node.name for node in workflow.nodes.values()]
            ['forever']

        """
        pipe_id = pythonise(name)
        store = self._document_store if directory is None else DirectoryStore(directory)

        if store is None:
            raise UnsupportedWorkflowError(pipe_id, "no document store is registered")

        if (workflow := store.load(pipe_id)) is None:
            raise UnsupportedWorkflowError(pipe_id, "no WorkflowDocument has that name")

        return workflow


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
    "DirectoryStore",
    "MappingStore",
    "PackageStore",
    "WorkflowResolver",
    "register_workflow_store",
    "reset_workflow_resolver",
    "workflow_resolver",
]
