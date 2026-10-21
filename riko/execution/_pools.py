# vim: sw=4:ts=4:expandtab
"""
Worker pool lifetime for per-item work in synchronous executions.

An execution maps a loopable node's items across one shared thread or process pool. It
pulls its source no further ahead than the pool can take.
"""

from __future__ import annotations

from collections import deque
from multiprocessing.pool import Pool as CPUPoolType
from multiprocessing.pool import ThreadPool as ThreadPoolType
from queue import SimpleQueue
from typing import TYPE_CHECKING, Self

from attrs import define, field

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator
    from multiprocessing.pool import ApplyResult
    from types import TracebackType

type AnyPool = ThreadPoolType | CPUPoolType

__all__ = ["AnyPool"]


@define(frozen=True, slots=True)
class _Failure:
    """Carries a worker's error back to the consuming thread."""

    error: BaseException


def _map_ordered[T, R](
    pool: AnyPool, func: Callable[[T], R], source: Iterable[T], window: int
) -> Iterator[R]:
    """Unlike ``Pool.imap``, maps in source order and pulls at most ``window`` ahead."""
    pending: deque[ApplyResult[R]] = deque()

    for item in source:
        pending.append(pool.apply_async(func, (item,)))

        if len(pending) >= window:
            yield pending.popleft().get()

    while pending:
        yield pending.popleft().get()


def _map_unordered[T, R](
    pool: AnyPool, func: Callable[[T], R], source: Iterable[T], window: int
) -> Iterator[R]:
    """Unlike ``imap``, maps in completion order and pulls at most ``window`` ahead."""
    done: SimpleQueue[R | _Failure] = SimpleQueue()
    pending = 0

    def take() -> R:
        if isinstance(value := done.get(), _Failure):
            raise value.error

        return value

    def submit(item: T) -> None:
        pool.apply_async(
            func,
            (item,),
            callback=done.put,
            error_callback=lambda error: done.put(_Failure(error)),
        )

    for item in source:
        submit(item)
        pending += 1

        if pending >= window:
            pending -= 1
            yield take()

    for _ in range(pending):
        yield take()


@define(eq=False)
class _PoolLifetime:
    """
    Owns an execution's shared worker pool and decides how it is released.

    The pool waits out its pending work only when every mapped stream ran to exhaustion
    and no error is propagating. Otherwise in-flight and read-ahead work is immediately
    stopped, so an early-closed or failed run never waits on it.

    Examples:

        Basic usage::

            >>> from multiprocessing.pool import ThreadPool
            >>> from riko.execution._pools import _PoolLifetime
            >>>
            >>> with _PoolLifetime(ThreadPool(2), 2) as lifetime:
            ...     list(lifetime.flat_map(lambda x: [x, x], [1, 2], ordered=True))
            [1, 1, 2, 2]

    """

    pool: AnyPool
    window: int
    abandoned: bool = field(default=False, init=False)
    _active: int = field(default=0, init=False)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if exc_type is None and not self.abandoned and not self._active:
            self.close()
        else:
            self.terminate()

    def close(self) -> None:
        """Waits out the pending work, then releases the pool."""
        self.pool.close()
        self.pool.join()

    def terminate(self) -> None:
        """Stops the pending work at once, then releases the pool."""
        self.pool.terminate()
        self.pool.join()

    def flat_map[T](
        self, func: Callable[[T], list[T]], source: Iterable[T], *, ordered: bool
    ) -> Iterator[T]:
        """
        Maps ``func`` over ``source`` on the pool and flattens each item's results.

        The source is pulled by the consumer, never ahead of it by more than the pool's
        width. Mapped nodes can share one pool and chain freely.

        Args:

            func: Collects one item's results.
            source: The items to map.
            ordered: Whether results keep source order.

        Yields:

            Each result item, in source order when ``ordered`` and in
            completion order otherwise.

        """
        mapper = _map_ordered if ordered else _map_unordered
        self._active += 1

        try:
            for results in mapper(self.pool, func, source, self.window):
                yield from results
        except GeneratorExit:
            self.abandoned = True
            raise
        else:
            self._active -= 1
