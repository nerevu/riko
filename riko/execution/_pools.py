# vim: sw=4:ts=4:expandtab
"""
Worker pools for per-item work in synchronous executions.

An execution opens a thread or process pool to map items across workers and sized
from the source length. Each pool is held by a handle that records whether riko
opened it. A handle releases only a pool it opened, and one borrowed from a
caller stays open for that caller to close.

Examples:

    Basic usage::

        >>> from riko.execution._pools import open_pool
        >>> from riko.types._enums import Executor
        >>>
        >>> handle = open_pool(Executor.THREAD, 2)
        >>> handle.pool
        <multiprocessing.pool.ThreadPool state=RUN pool_size=2>
        >>> handle.close()
        >>> handle.pool is None
        True

"""

from __future__ import annotations

from multiprocessing import Pool as CPUPool
from multiprocessing import cpu_count
from multiprocessing.dummy import Pool as ThreadPool
from multiprocessing.pool import Pool as CPUPoolType
from multiprocessing.pool import ThreadPool as ThreadPoolType
from typing import TYPE_CHECKING, Any

from riko.types._enums import Executor

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

type AnyPool = ThreadPoolType | CPUPoolType
type PoolFactory = Callable[..., AnyPool]
type PoolMap = Callable[..., Iterable[Any]]

__all__ = [
    "AnyPool",
    "PoolFactory",
    "PoolHandle",
    "PoolMap",
    "borrow_pool",
    "get_chunksize",
    "get_worker_cnt",
    "open_pool",
]


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


def get_chunksize(length: int, workers: int) -> int:
    """
    Computes items per worker task, targeting four batches per worker.

    Args:

        length: The number of items to spread across the pool.
        workers: The pool size.

    Returns:

        The batch size, never less than one.

    """
    return (length // (workers * 4)) or 1


class PoolHandle:
    """
    Shared pool state, including whether riko owns the pool.

    An owned pool is released by the first ``close``/``terminate`` call and the
    handle goes falsy; a borrowed one is left untouched for its owner to
    release.

    Examples:

        Basic usage::

            >>> from riko.execution._pools import open_pool
            >>> from riko.types._enums import Executor
            >>>
            >>> handle = open_pool(Executor.THREAD, 2)
            >>> list(handle.map(True)(str, [1, 2]))
            ['1', '2']
            >>> handle.close()
            >>> bool(handle)
            False

    """

    def __init__(self, pool: AnyPool, *, owned: bool) -> None:
        self.pool: AnyPool | None = pool
        self.owned = owned

    def __bool__(self) -> bool:
        return self.pool is not None

    def close(self) -> None:
        """Waits out the pending work, then releases an owned pool."""
        if self.owned and (pool := self.pool):
            pool.close()
            pool.join()
            self.pool = None

    def terminate(self) -> None:
        """Stops the pending work at once, then releases an owned pool."""
        if self.owned and (pool := self.pool):
            pool.terminate()
            pool.join()
            self.pool = None

    def map(self, ordered: bool) -> PoolMap:
        """
        Selects the pool's mapping function.

        Args:

            ordered: Whether results keep source order.

        Returns:

            The pool's ``map`` when ``ordered``, otherwise its
            ``imap_unordered``.

        Raises:

            RuntimeError: If the pool was already released.

        """
        if not (pool := self.pool):
            raise RuntimeError("Cannot reuse a closed worker pool")

        return pool.map if ordered else pool.imap_unordered


def open_pool(executor: Executor, workers: int) -> PoolHandle:
    """
    Builds a worker pool that its handle owns and releases.

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
            >>> handle.owned
            True
            >>> handle.pool
            <multiprocessing.pool.ThreadPool state=RUN pool_size=2>
            >>> handle.close()

    """
    if not (factory := _POOLS.get(executor)):
        raise ValueError(f"The {executor.value} executor has no worker pool")

    return PoolHandle(factory(workers), owned=True)


def borrow_pool(pool: AnyPool) -> PoolHandle:
    """
    Wraps a caller-supplied pool that riko never closes.

    Args:

        pool: The pool to borrow.

    Returns:

        A handle that leaves ``pool`` open when released.

    """
    return PoolHandle(pool, owned=False)
