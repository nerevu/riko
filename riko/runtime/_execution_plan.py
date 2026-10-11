# vim: sw=4:ts=4:expandtab
"""
Builds and runs a ``Workflow``'s immutable execution plan.

The build boundary validates the graph, indexes it, and looks up the pipe each node
names: a module such as ``fetch``, or a stored workflow's ``pipe_<id>``. The returned
plan carries those pipes. Building it runs no node and acquires no resources. The
sync/async executions run the plan without re-looking anything up.
"""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from riko.bado._util import maybe_aclosing
from riko.base._iterutils import map_values
from riko.definitions._workflow import ModuleNode, require_module_node
from riko.execution._execution import AsyncExecution, SyncExecution
from riko.execution._prepared import ExecutionPlan, ResolvedModule

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable, Generator

    from riko.definitions._workflow import PipelineDefinition, Workflow
    from riko.types._compiler import Embed

    from ._resolver import ResolverDispatcher


def _build_module_resolver(
    dispatcher: ResolverDispatcher,
) -> Callable[[ModuleNode | Embed], ResolvedModule]:
    def resolve(module: ModuleNode | Embed) -> ResolvedModule:
        if isinstance(module, ModuleNode):
            name, conf = module.name, module.conf
        else:
            name, conf = module["name"], module["conf"]

        dispatcher.validate(name)
        resolve = partial(dispatcher.resolve, name)
        sync_pipe, async_pipe = resolve(), resolve(is_async=True)
        return ResolvedModule(name, conf, sync_pipe=sync_pipe, async_pipe=async_pipe)

    return resolve


def build_execution_plan(
    workflow: Workflow, dispatcher: ResolverDispatcher
) -> ExecutionPlan:
    """
    Builds an executable snapshot of ``workflow`` with every node resolved once.

    Args:

        workflow: The ``Workflow`` to prepare.

        dispatcher: Finds each node's pipe by name, whether a module such as ``fetch``
            or a stored workflow's ``pipe_<id>``.

    Returns:

        The prepared plan: its graph index and resolved nodes. No node runs and
        no resource is acquired here.

    Raises:

        InvalidPipelineError: If the graph is invalid, a source port fans out to more
            than one edge, a node isn't a module node (write, action, cache, or
            subscribe), or a node runs a multi-output splitter.

        UnsupportedModuleError: If no module has the name a node gives.

        UnsupportedWorkflowError: If no stored workflow has the ``pipe_<id>`` name a
            node gives.

    Examples:

        >>> from riko.definitions._workflow import ModuleNode, Workflow
        >>> from riko.runtime._resolver import dispatcher
        >>> from riko.types._workflow import Endpoint
        >>>
        >>> workflow = Workflow(
        ...     nodes=[ModuleNode(id="count-1", name="count")],
        ...     outputs={"default": Endpoint("count-1", "out")},
        ... )
        >>> plan = build_execution_plan(workflow, dispatcher)
        >>> sorted(plan.nodes)
        ['count-1']

    """
    if not workflow.is_empty:
        workflow.validate()

    workflow.require_executable()
    nodes = map_values(require_module_node, workflow.nodes)
    embeds = {key: node.embed for key, node in nodes.items() if node.embed is not None}
    modules = map_values(_build_module_resolver(dispatcher=dispatcher), nodes)
    resolved_embeds = map_values(_build_module_resolver(dispatcher=dispatcher), embeds)
    return ExecutionPlan(workflow=workflow, modules=modules, embeds=resolved_embeds)


def run_pipeline[T](
    definition: PipelineDefinition[T], dispatcher: ResolverDispatcher
) -> Generator[T, None]:
    """
    Synchronously runs a pipeline definition in a fresh one-shot execution.

    The execution owns the run's resources for the lifetime of the returned iterator.

    Args:

        definition: The pipeline definition to run, with its context and settings.

        dispatcher: Finds each node's pipe by name, whether a module such as ``fetch``
            or a stored workflow's ``pipe_<id>``.

    Yields:

        The items produced at the definition's default output.

    Raises:

        InvalidPipelineError: If the definition's workflow cannot be planned.

    Examples:

        >>> from riko.definitions._workflow import PipelineDefinition
        >>> from riko.runtime._resolver import dispatcher
        >>>
        >>> definition = PipelineDefinition(source=[{"x": 1}]).count()
        >>> list(run_pipeline(definition, dispatcher))
        [{'count': 1}]

    """
    plan = build_execution_plan(definition.workflow, dispatcher)

    with SyncExecution(definition.context, settings=definition.settings) as execution:
        yield from execution.run(plan, source=definition.source)


async def arun_pipeline[T](
    definition: PipelineDefinition[T], dispatcher: ResolverDispatcher
) -> AsyncGenerator[T, None]:
    """
    Asynchronously runs a pipeline definition in a fresh one-shot execution.

    The execution owns the run's resources for the lifetime of the returned async
    iterator. Closing an abandoned iterator closes its stream before the execution
    exits.

    Args:

        definition: The pipeline definition to run, with its context and settings.

        dispatcher: Finds each node's pipe by name, whether a module such as ``fetch``
            or a stored workflow's ``pipe_<id>``.

    Yields:

        The items produced at the definition's default output.

    Raises:

        InvalidPipelineError: If the definition's workflow cannot be planned.

    Examples:

        >>> from riko import run
        >>> from riko.definitions._workflow import PipelineDefinition
        >>> from riko.runtime._resolver import dispatcher
        >>>
        >>> definition = PipelineDefinition(source=[{"x": 1}]).count()
        >>>
        >>> async def main():
        ...     print([item async for item in arun_pipeline(definition, dispatcher)])
        >>>
        >>> run(main)
        [{'count': 1}]

    """
    plan = build_execution_plan(definition.workflow, dispatcher)
    execution = AsyncExecution(definition.context, settings=definition.settings)

    async with execution:
        stream = await execution.arun(plan, source=definition.source)

        async with maybe_aclosing(stream) as items:
            async for item in items:
                yield item


__all__ = ["arun_pipeline", "build_execution_plan", "run_pipeline"]
