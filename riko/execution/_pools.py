# vim: sw=4:ts=4:expandtab
"""
Worker pool lifetime for per-item work in synchronous executions.

An execution maps a loopable node's items across one shared thread or process pool. It
pulls its source no further ahead than the pool can take. A worker process that dies
fails the run with ``BrokenProcessPool`` rather than leaving it waiting.
"""

from __future__ import annotations

from collections import deque
from concurrent.futures import Executor, Future, ProcessPoolExecutor
from queue import SimpleQueue
from typing import TYPE_CHECKING, Self

from attrs import define, field

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator
    from types import TracebackType

type AnyPool = Executor

__all__ = ["AnyPool"]


def _map_ordered[T, R](
    pool: AnyPool, func: Callable[[T], R], source: Iterable[T], window: int
) -> Iterator[R]:
    """Unlike ``Executor.map``, maps lazily and pulls at most ``window`` ahead."""
    pending: deque[Future[R]] = deque()

    for item in source:
        pending.append(pool.submit(func, item))

        if len(pending) >= window:
            yield pending.popleft().result()

    while pending:
        yield pending.popleft().result()


def _map_unordered[T, R](
    pool: AnyPool, func: Callable[[T], R], source: Iterable[T], window: int
) -> Iterator[R]:
    """Unlike ``as_completed``, maps lazily and pulls at most ``window`` ahead."""
    done: SimpleQueue[Future[R]] = SimpleQueue()
    pending = 0

    for item in source:
        pool.submit(func, item).add_done_callback(done.put)
        pending += 1

        if pending >= window:
            pending -= 1
            yield done.get().result()

    for _ in range(pending):
        yield done.get().result()


@define(eq=False)
class _PoolLifetime:
    """
    Owns an execution's shared worker pool and decides how it is released.

    The pool waits out its pending work only when every mapped stream ran to exhaustion
    and no error is propagating. Otherwise read-ahead work is cancelled and busy worker
    processes are stopped. Busy threads cannot be stopped, only waited on.

    Examples:

        Basic usage::

            >>> from concurrent.futures import ThreadPoolExecutor
            >>> from riko.execution._pools import _PoolLifetime
            >>>
            >>> with _PoolLifetime(ThreadPoolExecutor(2), 2) as lifetime:
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
        self.pool.shutdown(wait=True)

    def terminate(self) -> None:
        """Cancels the pending work and stops or waits out the running workers."""
        pool = self.pool
        isprocess = isinstance(pool, ProcessPoolExecutor)
        # `cancel_futures` drops only queued work, so busy processes are stopped below
        processes = pool._processes if isprocess else None
        workers = [] if processes is None else list(processes.values())
        pool.shutdown(wait=not isprocess, cancel_futures=True)

        for worker in workers:
            worker.terminate()

        for worker in workers:
            worker.join()

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
