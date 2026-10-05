# vim: sw=4:ts=4:expandtab
"""
The stable, runnable ``Pipeline``.

A ``Pipeline`` is a ``PipelineDefinition`` that runs. Iterating it, synchronously or
asynchronously, executes its workflow and yields the items at its default output.
Composing a ``Pipeline`` yields another ``Pipeline``, so a chain stays runnable.

Examples:

    Basic usage::

        >>> from riko import Pipeline
        >>>
        >>> source = [{"x": 2}, {"x": 1}]
        >>> pipeline = Pipeline(source=source).sort(conf={"rule": {"field": "x"}})
        >>> list(pipeline)
        [{'x': 1}, {'x': 2}]

"""

from __future__ import annotations

from contextlib import aclosing, closing
from typing import TYPE_CHECKING, Any

from attrs import define
from typing_extensions import TypeVar

from riko.bado._util import maybe_aclosing
from riko.base.exceptions import EmptyPipelineError
from riko.definitions._workflow import PipelineDefinition
from riko.execution._execution import AsyncExecution, SyncExecution
from riko.types._sentinels import MISSING, MissingType

from ._execution_plan import build_execution_plan

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator

T = TypeVar("T", default=Any)


@define(frozen=True, slots=True)
class Pipeline(PipelineDefinition[T]):
    """
    A runnable ``PipelineDefinition``: iterating it yields its default output.

    Examples:

        >>> items = [{"x": 1}, {"x": 2}, {"x": 3}]
        >>> pipeline = Pipeline(source=items).tail(conf={"count": 2})
        >>> for item in pipeline:
        ...     print(item)
        {'x': 2}
        {'x': 3}

    """

    def __iter__(self) -> Generator[T, None]:
        """
        Synchronously runs the pipeline with its context and execution settings.

        Each iteration creates a fresh one-shot execution that owns the run's
        resources for the lifetime of the returned iterator.

        Yields:

            The items produced at the pipeline's default output.

        """
        plan = build_execution_plan(self.workflow)

        with SyncExecution(self.context, settings=self.settings) as execution:
            yield from execution.run(plan, source=self.source)

    def __aiter__(self) -> AsyncGenerator[T, None]:
        """
        Asynchronously runs the pipeline with its context and execution settings.

        Each iteration creates a fresh one-shot execution that owns the run's
        resources for the lifetime of the returned async iterator.

        Yields:

            The items produced at the pipeline's default output.

        """

        async def _run() -> AsyncGenerator[T, None]:
            plan = build_execution_plan(self.workflow)
            execution = AsyncExecution(self.context, settings=self.settings)

            async with execution:
                stream = await execution.arun(plan, source=self.source)

                # An abandoned stream must close before the execution exits.
                async with maybe_aclosing(stream) as items:
                    async for item in items:
                        yield item

        return _run()

    def first(self, default: T | MissingType = MISSING) -> T:
        """
        Runs the pipeline just long enough to read its first item.

        The run is closed as soon as the item is read.

        Args:

            default: The value returned when the pipeline produces no items.

        Returns:

            The first item at the pipeline's default output, or ``default``.

        Raises:

            EmptyPipelineError: If the pipeline produces no items and no
                ``default`` is given.

        Examples:

            >>> Pipeline(source=[{"x": 1}, {"x": 2}]).first()
            {'x': 1}
            >>> print(Pipeline(source=[]).first(default=None))
            None

        """
        with closing(iter(self)) as stream:
            item = next(stream, default)

        if isinstance(item, MissingType):
            raise EmptyPipelineError

        return item

    async def afirst(self, default: T | MissingType = MISSING) -> T:
        """
        Asynchronously runs the pipeline just long enough to read its first item.

        The run is closed as soon as the item is read.

        Args:

            default: The value returned when the pipeline produces no items.

        Returns:

            The first item at the pipeline's default output, or ``default``.

        Raises:

            EmptyPipelineError: If the pipeline produces no items and no
                ``default`` is given.

        Examples:

            >>> from riko import run
            >>>
            >>> async def main():
            ...     print(await Pipeline(source=[{"x": 1}]).afirst())
            >>>
            >>> run(main)
            {'x': 1}

        """
        async with aclosing(aiter(self)) as stream:
            item = await anext(stream, default)

        if isinstance(item, MissingType):
            raise EmptyPipelineError

        return item


__all__ = ["Pipeline"]
