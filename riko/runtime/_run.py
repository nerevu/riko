# vim: sw=4:ts=4:expandtab
"""Runs a pipeline definition in a fresh one-shot execution, sync or async."""

from __future__ import annotations

import warnings
from collections.abc import AsyncGenerator, Generator
from typing import TYPE_CHECKING, Never, Self

from attrs import define, field

from riko.bado._util import maybe_aclosing
from riko.base._exceptions import PipelineStateError
from riko.execution._async_execution import AsyncExecution
from riko.execution._prepared import ExecutionPlan
from riko.execution._sync_execution import SyncExecution

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator
    from types import NotImplementedType

    from riko.definitions._pipeline_definition import PipelineDefinition
    from riko.types._streams import InputLike, PipelineStream
    from riko.types._wrappers import Dispatcher

_SUBJECT = "pipeline run"


def run_pipeline[T](
    definition: PipelineDefinition[T],
    dispatcher: Dispatcher,
    *,
    seed: InputLike | None = None,
) -> Generator[T, None]:
    """
    Synchronously runs a pipeline definition in a fresh one-shot execution.

    The execution owns the run's resources for the lifetime of the returned iterator.

    Args:

        definition: The pipeline definition to run, with its context and settings.

        dispatcher: Finds each node's pipe by name, whether a module such as ``fetch``
            or a stored workflow's ``pipe_<id>``.

        seed: Items for the definition's open input: one item, an item stream, an async
            item stream, or an awaitable resolving to one of those. Omit it when the
            definition is self-starting (default: None).

    Yields:

        The items produced at the definition's default output.

    Raises:

        InvalidPipelineError: If the definition's workflow cannot be planned, or no
            ``seed`` is given and the definition is not self-starting.

    Examples:

        >>> from riko.definitions._pipeline_definition import PipelineDefinition
        >>> from riko.runtime._resolver import dispatcher
        >>>
        >>> definition = PipelineDefinition.from_module("count")
        >>> list(run_pipeline(definition, dispatcher, seed=[{"x": 1}]))
        [{'count': 1}]

    """
    plan = ExecutionPlan.from_workflow(definition.workflow, dispatcher)

    with SyncExecution(definition.context, settings=definition.settings) as execution:
        yield from execution.run(plan, seed=seed)


async def arun_pipeline[T](
    definition: PipelineDefinition[T],
    dispatcher: Dispatcher,
    *,
    seed: InputLike | None = None,
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

        seed: Items for the definition's open input: one item, an item stream, an async
            item stream, or an awaitable resolving to one of those. Omit it when the
            definition is self-starting (default: None).

    Yields:

        The items produced at the definition's default output.

    Raises:

        InvalidPipelineError: If the definition's workflow cannot be planned, or no
            ``seed`` is given and the definition is not self-starting.

    Examples:

        >>> from riko import run
        >>> from riko.definitions._pipeline_definition import PipelineDefinition
        >>> from riko.runtime._resolver import dispatcher
        >>>
        >>> definition = PipelineDefinition.from_module("count")
        >>>
        >>> async def main():
        ...     stream = arun_pipeline(definition, dispatcher, seed=[{"x": 1}])
        ...     print([item async for item in stream])
        >>>
        >>> run(main)
        [{'count': 1}]

    """
    plan = ExecutionPlan.from_workflow(definition.workflow, dispatcher)
    execution = AsyncExecution(definition.context, settings=definition.settings)

    async with execution:
        stream = await execution.arun(plan, seed=seed)

        async with maybe_aclosing(stream) as items:
            async for item in items:
                yield item


@define(eq=False)
class _PipelineStream[T]:
    """
    One single-use pipeline run that can be iterated with ``for`` or ``async for``.

    The stream is its own (a)sync iterator: once consumed or closed, another ``for``
    loop yields nothing and ``next(stream, default)`` returns ``default``. A stream that
    started but was neither consumed nor closed warns when it is garbage collected.

    Attributes:

        definition: The pipeline definition to run.
        dispatcher: Finds each node's pipe by name.
        seed: Items for the definition's open input.

    Examples:

        >>> from riko.definitions._pipeline_definition import PipelineDefinition
        >>> from riko.runtime._resolver import dispatcher
        >>>
        >>> definition = PipelineDefinition.from_module("count")
        >>> list(_PipelineStream(definition, dispatcher, [{"x": 1}]))
        [{'count': 1}]

    """

    definition: PipelineDefinition[T]
    dispatcher: Dispatcher
    seed: InputLike | None = None
    _iteration: Generator[T, None] | AsyncGenerator[T, None] | None = field(
        default=None, init=False
    )
    _started: bool = field(default=False, init=False)
    _finished: bool = field(default=False, init=False)

    def _require_sync(self) -> Generator[T, None]:
        if isinstance(self._iteration, AsyncGenerator):
            state, action = "asynchronous", "synchronously iterate"
            raise PipelineStateError(state, action, subject=_SUBJECT)
        elif self._iteration is None:
            definition, seed = self.definition, self.seed
            self._iteration = run_pipeline(definition, self.dispatcher, seed=seed)

        return self._iteration

    def _require_async(self) -> AsyncGenerator[T, None]:
        if isinstance(self._iteration, Generator):
            state, action = "synchronous", "asynchronously iterate"
            raise PipelineStateError(state, action, subject=_SUBJECT)
        elif self._iteration is None:
            definition, seed = self.definition, self.seed
            self._iteration = arun_pipeline(definition, self.dispatcher, seed=seed)

        return self._iteration

    def __or__(self, other: object) -> NotImplementedType:
        """
        Refuses a module name after a stream.

        ``items | pipeline | "sort"`` groups as ``(items | pipeline) | "sort"``. This
        chains ``"sort"`` onto a stream, not the pipeline. Use
        ``items | (pipeline | "sort")`` instead. A pipeline after a stream
        (``items | pipeline | other``), however, is valid.

        Args:

            other: The value on the right of ``|``.

        Returns:

            ``NotImplemented`` so a pipeline on the right takes the stream as its seed.

        Raises:

            TypeError: If ``other`` is a module name, with a hint to compose first.

        Examples:

            >>> from riko.definitions._pipeline_definition import PipelineDefinition
            >>> from riko.runtime._resolver import dispatcher
            >>>
            >>> definition = PipelineDefinition.from_module("count")
            >>> stream = _PipelineStream(definition, dispatcher, [])
            >>> stream | "sort"
            Traceback (most recent call last):
            TypeError: compose the pipeline first: items | (pipeline | 'sort')

        """
        if isinstance(other, str):
            msg = f"compose the pipeline first: items | (pipeline | {other!r})"
            raise TypeError(msg)

        return NotImplemented

    def __iter__(self) -> Self:
        """
        Starts synchronous iteration.

        Returns:

            This stream.

        Raises:

            PipelineStateError: If the stream is iterated asynchronously.

        """
        if not self._finished:
            self._require_sync()

        return self

    def __next__(self) -> T:
        """
        Synchronously reads the run's next item.

        Returns:

            The next item at the pipeline's default output.

        Raises:

            StopIteration: When the run is consumed or closed, and on every later call.
            PipelineStateError: If the stream is iterated asynchronously.

        """
        if self._finished:
            raise StopIteration

        stream = self._require_sync()
        self._started = True

        try:
            item = next(stream)
        except BaseException:
            self._finished = True
            raise

        return item

    def close(self) -> None:
        """
        Stops the run and releases its resources (closing again does nothing).

        Raises:

            PipelineStateError: If the stream is being iterated asynchronously. Use
                ``aclose`` instead.

        """
        if isinstance(self._iteration, AsyncGenerator):
            if not self._finished:
                state, action = "asynchronous", "synchronously close"
                raise PipelineStateError(state, action, subject=_SUBJECT)
        elif self._iteration is not None:
            self._iteration.close()

        self._finished = True

    def __aiter__(self) -> Self:
        """
        Starts asynchronous iteration.

        Returns:

            This stream.

        Raises:

            PipelineStateError: If the stream is iterated synchronously.

        """
        if not self._finished:
            self._require_async()

        return self

    async def __anext__(self) -> T:
        """
        Asynchronously reads the run's next item.

        Returns:

            The next item at the pipeline's default output.

        Raises:

            StopAsyncIteration: When the run is consumed or closed, and on every later
                call.

            PipelineStateError: If the stream is iterated synchronously.

        """
        if self._finished:
            raise StopAsyncIteration

        stream = self._require_async()
        self._started = True

        try:
            item = await anext(stream)
        except BaseException:
            self._finished = True
            raise

        return item

    async def aclose(self) -> None:
        """Stops the run and releases its resources (closing again does nothing)."""
        if isinstance(self._iteration, AsyncGenerator):
            await self._iteration.aclose()
        elif self._iteration is not None:
            self._iteration.close()

        self._finished = True

    def __enter__(self) -> Never:
        """
        Refuses ``with`` since a stream is not a context manager.

        Raises:

            TypeError: Always. ``pipeline.open(items)`` returns a context manager.

        """
        msg = "a pipeline stream is not a context manager. "
        msg += "Use `with pipeline.open(items)`, which returns one"
        raise TypeError(msg)

    def __exit__(self, *exc: object) -> None:
        """Does nothing; ``__enter__`` always raises."""

    async def __aenter__(self) -> Never:
        """
        Refuses ``async with`` since a stream is not an async context manager.

        Raises:

            TypeError: Always. ``pipeline.open(items)`` returns a context manager.

        """
        msg = "a pipeline stream is not an async context manager. "
        msg += "Use `async with pipeline.open(items)`, which returns one"
        raise TypeError(msg)

    async def __aexit__(self, *exc: object) -> None:
        """Does nothing; ``__aenter__`` always raises."""

    def __del__(self) -> None:
        """Warns when a started run is garbage collected before it finishes."""
        if getattr(self, "_started", False) and not getattr(self, "_finished", True):
            msg = f"unclosed {_SUBJECT}. Iterate it to the end, close it, or "
            msg += "iterate it inside `with pipeline.open(items)`"
            warnings.warn(msg, ResourceWarning, source=self, stacklevel=1)


@define(eq=False)
class _PipelineRun[T]:
    """
    A context manager over one pipeline run that closes the run on exit.

    ``with`` yields a synchronous iterator and ``async with`` an asynchronous one.
    Leaving the block closes the run in the task that opened it.

    Attributes:

        stream: The run's stream.

    Examples:

        >>> from riko.definitions._pipeline_definition import PipelineDefinition
        >>> from riko.runtime._resolver import dispatcher
        >>>
        >>> definition = PipelineDefinition.from_module("count")
        >>> stream = _PipelineStream(definition, dispatcher, [{"x": 1}])
        >>>
        >>> with _PipelineRun(stream) as items:
        ...     print(next(items))
        {'count': 1}

    """

    stream: PipelineStream[T]

    def __enter__(self) -> Iterator[T]:
        """
        Starts the run synchronously.

        Returns:

            An iterator over the items at the pipeline's default output.

        """
        return iter(self.stream)

    def __exit__(self, *exc: object) -> None:
        """Closes the run."""
        self.stream.close()

    async def __aenter__(self) -> AsyncIterator[T]:
        """
        Starts the run asynchronously.

        Returns:

            An async iterator over the items at the pipeline's default output.

        """
        return aiter(self.stream)

    async def __aexit__(self, *exc: object) -> None:
        """Closes the run."""
        await self.stream.aclose()


__all__ = ["arun_pipeline", "run_pipeline"]
