# vim: sw=4:ts=4:expandtab
"""
Provides the pipes that run a stored workflow.

A stored workflow is a workflow store entry looked up by its ``pipe_<id>`` name. Its
pipes are tagged so that ``loop`` runs them without the ``conf`` and ``emit`` it
passes other embeds. This is because a stored workflow's nodes carry their own conf.
"""

from __future__ import annotations

from functools import partial, update_wrapper
from inspect import isasyncgenfunction
from typing import TYPE_CHECKING, Literal, NamedTuple, Protocol, cast, overload

from riko.bado.itertools import as_async
from riko.base._config import SUBPIPE_TYPE
from riko.base._guards import is_async_callable
from riko.definitions._pipeline_definition import PipelineDefinition
from riko.definitions._wrapping import stamp_wrapper_meta
from riko.types._enums import ExecutionMode
from riko.types._frozendict import normalize_mapping

from ._run import arun_pipeline, run_pipeline

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Iterator, Mapping

    from riko.definitions._context import Context
    from riko.definitions._workflow_definition import Workflow
    from riko.types._streams import InputLike
    from riko.types._wrappers import (
        AsyncFunc,
        AsyncSubPipe,
        Dispatcher,
        Func,
        SubPipe,
        SyncSubPipe,
    )
    from riko.types.modules import ModuleSubtype


class SubPipes(NamedTuple):
    """
    Pairs the sync and async pipes ``build_workflow_pipes`` builds for one workflow.

    Attributes:

        sync_pipe: The sync pipe.
        async_pipe: The async pipe.

    Examples:

        >>> from riko import Workflow
        >>> from riko.runtime._resolver import dispatcher
        >>>
        >>> pipes = build_workflow_pipes(Workflow(), dispatcher, subtype="source")
        >>> pipes.sync_pipe.type, pipes.async_pipe.type
        ('pipe', 'pipe')

    """

    sync_pipe: SyncSubPipe
    async_pipe: AsyncSubPipe


class _WorkflowTagger(Protocol):
    @overload
    def __call__(  # pyright: ignore[reportOverlappingOverload]
        self, pipe: AsyncFunc
    ) -> AsyncSubPipe: ...
    @overload
    def __call__(self, pipe: Func) -> SyncSubPipe: ...


@overload
def workflow(  # pyright: ignore[reportOverlappingOverload]
    *, subtype: ModuleSubtype = ..., loopable: bool = ..., isasync: Literal[True]
) -> Callable[[Func], AsyncSubPipe]: ...
@overload
def workflow(
    *, subtype: ModuleSubtype = ..., loopable: bool = ..., isasync: bool | None = ...
) -> _WorkflowTagger: ...
def workflow(
    *args: object,
    subtype: ModuleSubtype = "transformer",
    loopable: bool = True,
    isasync: bool | None = None,
) -> Callable[[Func], SubPipe]:
    """
    Tags a hand-written workflow module's pipe as a stored workflow's pipe.

    ``loop`` runs a tagged pipe without the ``conf`` and ``emit`` it passes other embeds
    (a stored workflow's nodes carry their own conf). Workflow modules
    (``WorkflowModule``) tag their pipes like this either directly or through
    ``build_workflow_pipes``. The decorated name is bound to a tagged copy, and the
    original function is left untouched.

    Args:

        args: Not accepted. Options are keyword-only, and a ``Workflow`` runs through
            ``Pipeline`` instead.

    Kwargs:

        subtype: How the pipe is tagged. E.g., ``"source"`` (needs no input) or
            ``"transformer"`` (takes an item).

        loopable: The pipe's ``loopable`` discovery flag. ``loop`` embeds a tagged pipe
            either way.

        isasync: Whether the pipe is the async interface. Defaults to ``True`` for an
            async function or an async generator function.

    Returns:

        A decorator that returns a tagged copy of the pipe it is given.

    Raises:

        TypeError: If any positional argument is passed.

    Examples:

        >>> @workflow(subtype="source")
        ... def pipe(item=None, **kwargs):
        ...     return iter([])
        >>>
        >>> pipe.type, pipe.subtype, pipe.isasync
        ('pipe', 'source', False)

    """
    if args:
        msg = "workflow() takes keyword options only, e.g. @workflow(subtype=...); "
        msg += "to run a Workflow, pass it to Pipeline"
        raise TypeError(msg)

    def tag(pipe: Func) -> SubPipe:
        tagged = partial(pipe)
        update_wrapper(tagged, pipe)

        if isasync is None:
            resolved = is_async_callable(pipe) or isasyncgenfunction(pipe)
        else:
            resolved = isasync

        stamp_wrapper_meta(
            tagged,
            name=getattr(pipe, "__name__", SUBPIPE_TYPE),
            module_type=SUBPIPE_TYPE,
            subtype=subtype,
            subtypes={subtype},
            pollable=False,
            loopable=loopable,
            isasync=resolved,
        )

        return cast("SubPipe", tagged)

    return tag


def build_workflow_pipes(
    flow: Workflow,
    dispatcher: Dispatcher,
    *dependencies: str,
    subtype: ModuleSubtype,
    inputs: Mapping[str, object] | None = None,
) -> SubPipes:
    """
    Builds the ``pipe`` and ``async_pipe`` callables that run a ``Workflow``.

    Each callable takes one item, a stream, or nothing. Normally the callable runs
    ``flow`` and yields its default output. When the ``Context`` asks to describe the
    workflow, nothing runs.

    With ``describe_input``, ``pipe`` returns the input declarations and ``async_pipe``
    yields them as a single item. With ``describe_dependencies``, ``pipe`` returns the
    ``dependencies`` names as a list and ``async_pipe`` yields each name. With both,
    ``pipe`` returns ``{"inputs": ..., "dependencies": [...]}`` and ``async_pipe``
    yields it as a single item.

    Args:

        flow: The ``Workflow`` the pipes run.

        dispatcher: Finds each node's pipe by name, whether a module such as
            ``fetch`` or a stored workflow's ``pipe_<id>``.

        dependencies: The names of the modules and stored workflows, such as ``fetch``
            or a ``pipe_<id>``, that the workflow's nodes use. Reported when describing
            dependencies.

    Kwargs:

        subtype: How the pipe callables are tagged. E.g., ``"source"`` (needs no input)
            or ``"transformer"`` (takes an item).

        inputs: The workflow's input declarations. Reported when describing inputs.

    Returns:

        The sync and async callables. Each is tagged as a stored workflow's pipe, which
        lets ``loop`` run it without the ``conf`` and ``emit`` it passes other embeds.

    Examples:

        >>> from riko import Workflow
        >>> from riko.runtime._resolver import dispatcher
        >>>
        >>> pipe = build_workflow_pipes(
        ...     Workflow(), dispatcher, subtype="transformer",
        ... ).sync_pipe
        >>> list(pipe([{"x": 1}]))
        [{'x': 1}]

    """
    inputs = normalize_mapping(inputs)
    description = {"inputs": inputs, "dependencies": list(dependencies)}

    def pipe(
        item: InputLike | None = None, context: Context | None = None, **_: object
    ) -> Iterator[object] | dict[str, object] | list[str]:
        if context is None or context.mode is ExecutionMode.RUN:
            definition = PipelineDefinition(flow, context=context)
            result: Iterator[object] | dict[str, object] | list[str]
            result = run_pipeline(definition, dispatcher, seed=item)
        elif context.mode is ExecutionMode.DESCRIBE:
            result = description
        elif context.describe_input:
            result = inputs
        else:
            result = list(dependencies)

        return result

    def async_pipe(
        item: InputLike | None = None, context: Context | None = None, **_: object
    ) -> AsyncIterator[object]:
        if context is None or context.mode is ExecutionMode.RUN:
            definition = PipelineDefinition(flow, context=context)
            result: AsyncIterator[object]
            result = arun_pipeline(definition, dispatcher, seed=item)
        elif context.mode is ExecutionMode.DESCRIBE:
            result = as_async([description])
        elif context.describe_input:
            result = as_async([inputs])
        else:
            result = as_async(dependencies)

        return result

    sync_pipe = workflow(subtype=subtype, isasync=False)(pipe)
    _async_pipe = workflow(subtype=subtype, isasync=True)(async_pipe)
    return SubPipes(sync_pipe, _async_pipe)
