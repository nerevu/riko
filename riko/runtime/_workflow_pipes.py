# vim: sw=4:ts=4:expandtab
"""
Provides the pipes that run a stored workflow.

A stored workflow is a workflow store entry looked up by its ``pipe_<id>`` name. Its
pipes are tagged so that ``loop`` runs them without the ``conf`` and ``emit`` it
passes other embeds. This is because a stored workflow's nodes carry their own conf.

Examples:

    Basic usage::

        >>> from riko.ext import workflow
        >>>
        >>> @workflow(subtype="source", input_schemas={"q": "string"})
        ... def pipe(item=None, **kwargs):
        ...     return iter([{"q": "riko"}])
        >>>
        >>> list(pipe())
        [{'q': 'riko'}]
        >>> dict(pipe.input_schemas["q"])
        {'type': 'string'}

"""

from __future__ import annotations

from collections.abc import Iterable
from functools import partial, update_wrapper
from inspect import isasyncgenfunction
from typing import TYPE_CHECKING, Literal, NamedTuple, Protocol, overload

from riko.base._config import SUBPIPE_TYPE
from riko.base._guards import is_async_callable
from riko.base._iterutils import sort_stably
from riko.base._require_guards import normalize_strs
from riko.definitions._normalize import normalize_input_schemas
from riko.definitions._pipeline_definition import PipelineDefinition
from riko.definitions._workflow_definition import input_schemas_converter
from riko.definitions._wrapping import stamp_wrapper_meta, validate_call_keywords
from riko.execution._prepared import ExecutionPlan
from riko.types._wrappers import require_subpipe

from ._run import arun_pipeline, run_pipeline

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Iterator

    from riko.definitions._context import Context
    from riko.definitions._workflow_definition import Workflow
    from riko.types._frozendict import FrozenInputSchemas, InputSchemasLike
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
        >>> pipes = build_workflow_pipes(Workflow(), dispatcher)
        >>> pipes.sync_pipe.type, pipes.async_pipe.subtype
        ('pipe', 'transformer')

    """

    sync_pipe: SyncSubPipe
    async_pipe: AsyncSubPipe


class _WorkflowTagger(Protocol):
    @overload
    def __call__(  # pyright: ignore[reportOverlappingOverload]
        self, pipe: AsyncFunc[object]
    ) -> AsyncSubPipe: ...
    @overload
    def __call__(self, pipe: Func[object]) -> SyncSubPipe: ...


def _normalize_dependencies(value: Iterable[str] | None) -> tuple[str, ...] | None:
    """Normalizes declared dependency names to a sorted, duplicate-free tuple."""
    if value is None:
        names = None
    else:
        is_many = isinstance(value, Iterable) and not isinstance(value, str)
        unique = dict.fromkeys(value) if is_many else value
        what = "workflow 'dependencies'"
        names = sort_stably(normalize_strs(unique, what=what))

    return names


@overload
def workflow(  # pyright: ignore[reportOverlappingOverload]
    *,
    subtype: ModuleSubtype = ...,
    loopable: bool = ...,
    isasync: Literal[True],
    input_schemas: InputSchemasLike | None = ...,
    dependencies: Iterable[str] | None = ...,
) -> Callable[[Func[object]], AsyncSubPipe]: ...
@overload
def workflow(
    *,
    subtype: ModuleSubtype = ...,
    loopable: bool = ...,
    isasync: bool | None = ...,
    input_schemas: InputSchemasLike | None = ...,
    dependencies: Iterable[str] | None = ...,
) -> _WorkflowTagger: ...
def workflow(
    *args: object,
    subtype: ModuleSubtype = "transformer",
    loopable: bool = True,
    isasync: bool | None = None,
    input_schemas: InputSchemasLike | None = None,
    dependencies: Iterable[str] | None = None,
) -> Callable[[Func[object]], SubPipe]:
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

        isasync: Whether the pipe is an ``async_pipe``. Defaults to ``True`` for an
            async function or an async generator function.

        input_schemas: The input schemas the workflow reads (each a type name or JSON
            Schema), keyed by input name. What ``describe_module`` reports.

        dependencies: The module and stored-workflow names the workflow runs. What
            ``describe_module`` reports.

    Returns:

        A decorator that returns a tagged copy of the pipe it is given.

    Raises:

        TypeError: If any positional argument is passed.

        InvalidPipelineError: If an input's schema is not a mapping, or a dependency
            is not a non-empty string.

    Examples:

        >>> @workflow(subtype="source", dependencies=["fetch", "count", "fetch"])
        ... def pipe(item=None, **kwargs):
        ...     return iter([])
        >>>
        >>> pipe.type, pipe.subtype, pipe.isasync
        ('pipe', 'source', False)
        >>> pipe.dependencies
        ('count', 'fetch')
        >>> pipe.input_schemas

    """
    if args:
        msg = "workflow() takes keyword options only, e.g. @workflow(subtype=...); "
        raise TypeError(msg + "to run a Workflow, pass it to Pipeline")

    if input_schemas is None:
        schemas: FrozenInputSchemas | None = None
    else:
        schemas = input_schemas_converter(normalize_input_schemas(input_schemas))

    names = _normalize_dependencies(dependencies)

    def tag(pipe: Func[object]) -> SubPipe:
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
            input_schemas=schemas,
            dependencies=names,
        )

        return require_subpipe(tagged)

    return tag


def build_workflow_pipes(
    flow: Workflow, dispatcher: Dispatcher, *, name: str = "anonymous"
) -> SubPipes:
    """
    Builds the ``pipe`` and ``async_pipe`` callables that run a ``Workflow``.

    Each callable takes its input (one item, a stream, or nothing), runs ``flow``, and
    yields its items. The callables are tagged ``"source"`` when they can run without a
    seed, and ``"transformer"`` otherwise. They carry ``flow``'s input schemas and
    dependencies for ``describe_module`` to report.

    Args:

        flow: The ``Workflow`` the pipes run.

        dispatcher: Finds each node's pipe by name, whether a module such as
            ``fetch`` or a stored workflow's ``pipe_<id>``.

    Kwargs:

        name: The stored workflow's ``pipe_<id>`` name, used in errors.

    Returns:

        The sync and async callables. Each is tagged as a stored workflow's pipe, which
        lets ``loop`` run it without the ``conf`` and ``emit`` it passes other embeds.

    Raises:

        InvalidPipelineError: If ``flow`` cannot be planned.

        TypeError: If a callable is passed ``mode``; a pipe only runs.

    Examples:

        >>> from riko import Workflow
        >>> from riko.runtime._resolver import dispatcher
        >>>
        >>> pipe = build_workflow_pipes(Workflow(), dispatcher).sync_pipe
        >>> list(pipe([{"x": 1}]))
        [{'x': 1}]
        >>> pipe.dependencies
        ()

    """
    plan = ExecutionPlan.from_workflow(flow, dispatcher)
    self_starting = plan.is_self_starting_output()
    subtype: ModuleSubtype = "source" if self_starting else "transformer"

    def pipe(
        item: InputLike | None = None, context: Context | None = None, **kwargs: object
    ) -> Iterator[object]:
        validate_call_keywords(name, kwargs)
        definition = PipelineDefinition(flow, context=context)
        return run_pipeline(definition, dispatcher, seed=item)

    def async_pipe(
        item: InputLike | None = None, context: Context | None = None, **kwargs: object
    ) -> AsyncIterator[object]:
        validate_call_keywords(name, kwargs)
        definition = PipelineDefinition(flow, context=context)
        return arun_pipeline(definition, dispatcher, seed=item)

    schemas, names = flow.input_schemas, flow.dependencies
    sync_tag = workflow(
        subtype=subtype, isasync=False, input_schemas=schemas, dependencies=names
    )
    async_tag = workflow(
        subtype=subtype, isasync=True, input_schemas=schemas, dependencies=names
    )
    return SubPipes(sync_tag(pipe), async_tag(async_pipe))
