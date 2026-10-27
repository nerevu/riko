# vim: sw=4:ts=4:expandtab
"""Runs a pipeline definition in a fresh one-shot execution, sync or async."""

from __future__ import annotations

from typing import TYPE_CHECKING

from riko.bado._util import maybe_aclosing
from riko.execution._async_execution import AsyncExecution
from riko.execution._prepared import ExecutionPlan
from riko.execution._sync_execution import SyncExecution

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator

    from riko.definitions._pipeline_definition import PipelineDefinition
    from riko.types._wrappers import Dispatcher


def run_pipeline[T](
    definition: PipelineDefinition[T], dispatcher: Dispatcher
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

        >>> from riko.definitions._pipeline_definition import PipelineDefinition
        >>> from riko.runtime._resolver import dispatcher
        >>>
        >>> definition = PipelineDefinition(source=[{"x": 1}]).count()
        >>> list(run_pipeline(definition, dispatcher))
        [{'count': 1}]

    """
    plan = ExecutionPlan.from_workflow(definition.workflow, dispatcher)

    with SyncExecution(definition.context, settings=definition.settings) as execution:
        yield from execution.run(plan, source=definition.source)


async def arun_pipeline[T](
    definition: PipelineDefinition[T], dispatcher: Dispatcher
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
        >>> from riko.definitions._pipeline_definition import PipelineDefinition
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
    plan = ExecutionPlan.from_workflow(definition.workflow, dispatcher)
    execution = AsyncExecution(definition.context, settings=definition.settings)

    async with execution:
        stream = await execution.arun(plan, source=definition.source)

        async with maybe_aclosing(stream) as items:
            async for item in items:
                yield item


__all__ = ["arun_pipeline", "run_pipeline"]
