# vim: sw=4:ts=4:expandtab
"""
Worker pools for per-item work in synchronous executions.

An execution opens a thread or process pool to map items across workers and sized
from the source length. Each pool is held by a handle that releases it once.
"""

from __future__ import annotations

from multiprocessing import Pool as CPUPool
from multiprocessing import cpu_count
from multiprocessing.dummy import Pool as ThreadPool
from multiprocessing.pool import Pool as CPUPoolType
from multiprocessing.pool import ThreadPool as ThreadPoolType
from typing import TYPE_CHECKING

from riko.base.exceptions import PipelineStateError
from riko.types._enums import Executor

if TYPE_CHECKING:
    from collections.abc import Callable

type AnyPool = ThreadPoolType | CPUPoolType
type PoolFactory = Callable[..., AnyPool]

__all__ = ["AnyPool", "PoolFactory", "PoolHandle", "get_worker_cnt", "open_pool"]


_POOLS: dict[Executor, PoolFactory] = {
    Executor.THREAD: ThreadPool,
    Executor.PROCESS: CPUPool,
}


def get_worker_cnt(length: int, threads: bool | None = True) -> int:
    """
    Computes a pool size, capped at the core count (doubled for threads).

    Args:

        length: The number of items to spread across the pool, or zero when
            unknown.
        threads: Whether the pool uses threads rather than processes.

    Returns:

        The worker count.

    """
    multiplier = 2 if threads else 1
    maximum = cpu_count() * multiplier
    return min(length, maximum) if length else maximum


class PoolHandle:
    """
    Holds a worker pool until its first ``close``/``terminate`` releases it.

    A released handle goes falsy, and a repeated release does nothing.

    Examples:

        Basic usage::

            >>> from riko.execution._pools import open_pool
            >>> from riko.types._enums import Executor
            >>>
            >>> handle = open_pool(Executor.THREAD, 2)
            >>> handle.require_pool().map(str, [1, 2])
            ['1', '2']
            >>> handle.close()
            >>> bool(handle)
            False

    """

    def __init__(self, pool: AnyPool) -> None:
        self.pool: AnyPool | None = pool

    def __bool__(self) -> bool:
        return self.pool is not None

    def _release(self, stop: Callable[[AnyPool], None]) -> None:
        if pool := self.pool:
            stop(pool)
            pool.join()
            self.pool = None

    def close(self) -> None:
        """Waits out the pending work, then releases the pool."""
        self._release(CPUPoolType.close)

    def terminate(self) -> None:
        """Stops the pending work at once, then releases the pool."""
        self._release(CPUPoolType.terminate)

    def require_pool(self) -> AnyPool:
        """
        Requires the pool the handle still holds.

        Returns:

            The live pool.

        Raises:

            PipelineStateError: If the pool was already released.

        """
        if (pool := self.pool) is None:
            raise PipelineStateError("closed", "reuse", subject="worker pool")

        return pool


def open_pool(executor: Executor, workers: int) -> PoolHandle:
    """
    Builds a worker pool behind a handle that releases it.

    Args:

        executor: The thread or process executor to open a pool for.
        workers: The pool size.

    Returns:

        A handle over the new pool.

    Raises:

        ValueError: If ``executor`` is ``INLINE`` or ``AUTO``, which have no worker
            pool.

    Examples:

        Basic usage::

            >>> from riko.execution._pools import open_pool
            >>> from riko.types._enums import Executor
            >>>
            >>> handle = open_pool(Executor.THREAD, 2)
            >>> handle.pool
            <multiprocessing.pool.ThreadPool state=RUN pool_size=2>
            >>> handle.close()

    """
    if not (factory := _POOLS.get(executor)):
        raise ValueError(f"The {executor.value} executor has no worker pool")

    return PoolHandle(factory(workers))
