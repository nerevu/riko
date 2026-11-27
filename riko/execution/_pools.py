# vim: sw=4:ts=4:expandtab
"""
Worker pool lifetime for per-item work in synchronous executions.

An execution spreads a mappable node's items across one shared thread or process pool.
It pulls its source no further ahead than the pool can take. A worker process that dies
fails the run with ``BrokenProcessPool`` rather than leaving it waiting.
"""

from __future__ import annotations

from collections import deque
from concurrent.futures import Executor, Future, ProcessPoolExecutor
from contextlib import contextmanager
from math import inf
from queue import SimpleQueue
from typing import TYPE_CHECKING, Self

from attrs import define, field

from riko.base._dateutils import Deadline

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Iterable, Iterator
    from types import TracebackType

    from riko.types._wrappers import Func

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
    Holds an execution's shared worker pool and decides how it is released.

    The pool waits out its pending work only when every mapped stream ran to exhaustion
    and no error is propagating. Otherwise read-ahead work is cancelled and busy worker
    processes are stopped. Any still running ``grace`` seconds after the first is
    stopped are killed. An infinite ``grace`` waits for them. Busy threads cannot be
    stopped, only waited on.

    Examples:

        >>> from concurrent.futures import ThreadPoolExecutor
        >>>
        >>> with _PoolLifetime(ThreadPoolExecutor(2), 2) as lifetime:
        ...     with lifetime.track():
        ...         lifetime.pool.submit(abs, -1).result()
        1

    """

    pool: AnyPool
    window: int
    grace: float = field(default=inf, kw_only=True)
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

        deadline = Deadline.from_timeout(self.grace)

        for worker in workers:
            worker.join(deadline.remaining)

            if worker.is_alive():
                worker.kill()
                worker.join()

    @contextmanager
    def track(self) -> Generator[None]:
        """
        Counts a mapped stream as active while the block runs.

        A stream closed before it ends marks the pool abandoned, and one that fails
        stays counted, so either way the pool is terminated rather than waited out.
        """
        self._active += 1

        try:
            yield
        except GeneratorExit:
            self.abandoned = True
            raise
        else:
            self._active -= 1


# TODO: make generic over an Executor and move to the iterator helpers (owned by the
# planned streaming of a mapped node's per-item output)
def flat_map[T, S](
    func: Callable[[T], Iterable[S]],
    source: Iterable[T],
    *,
    ordered: bool,
    opener: Func[_PoolLifetime],
) -> Iterator[S]:
    """
    Maps ``func`` over ``source`` on a worker pool and flattens the per-item results.

    Opens the pool on the first pull through ``opener``. Pulls the source no more ahead
    than the pool's window. Mapped nodes can share one pool and chain freely.

    Args:

        func: Collects a node's per-item results.
        source: The items to map.

    Kwargs:

        ordered: Whether items keep source order.
        opener: Opens the shared pool, or returns it once open.

    Yields:

        Each result item, in source order when ``ordered`` and in completion order
        otherwise.

    Examples:

        >>> from concurrent.futures import ThreadPoolExecutor
        >>>
        >>> with _PoolLifetime(ThreadPoolExecutor(2), 2) as lifetime:
        ...     opener = lambda: lifetime
        ...     list(flat_map(lambda x: [x, x], [1, 2], ordered=True, opener=opener))
        [1, 1, 2, 2]

    """
    lifetime = opener()
    mapper = _map_ordered if ordered else _map_unordered

    with lifetime.track():
        for results in mapper(lifetime.pool, func, source, lifetime.window):
            yield from results
