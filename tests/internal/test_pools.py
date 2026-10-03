# vim: sw=4:ts=4:expandtab
"""Tests for the private synchronous worker-pool machinery."""

from multiprocessing import cpu_count
from multiprocessing.dummy import Pool as ThreadPool

import pytest

from riko.execution._pools import borrow_pool, get_chunksize, get_worker_cnt, open_pool
from riko.types._enums import Executor


class TestWorkerCnt:
    def test_zero_length_uses_the_maximum(self) -> None:
        assert get_worker_cnt(0) == cpu_count() * 2
        assert get_worker_cnt(0, False) == cpu_count()

    def test_small_length_caps_at_the_length(self) -> None:
        assert get_worker_cnt(1) == 1
        assert get_worker_cnt(1, False) == 1

    def test_huge_length_caps_at_the_maximum(self) -> None:
        assert get_worker_cnt(10_000) == cpu_count() * 2
        assert get_worker_cnt(10_000, False) == cpu_count()


class TestChunksize:
    def test_four_batches_per_worker(self) -> None:
        assert get_chunksize(80, 4) == 5
        assert get_chunksize(100, 5) == 5

    def test_floors_at_one(self) -> None:
        assert get_chunksize(0, 4) == 1
        assert get_chunksize(3, 4) == 1


@pytest.mark.slow
class TestOwnedPool:
    def test_close_releases_the_pool(self) -> None:
        handle = open_pool(Executor.THREAD, 2)
        assert handle.owned
        assert handle

        handle.close()
        assert handle.pool is None
        assert not handle
        assert handle.owned

    def test_close_is_idempotent(self) -> None:
        handle = open_pool(Executor.THREAD, 2)
        handle.close()
        handle.close()
        assert handle.pool is None

    def test_terminate_releases_the_pool(self) -> None:
        handle = open_pool(Executor.THREAD, 2)
        handle.terminate()
        assert handle.pool is None
        assert not handle
        assert handle.owned

    def test_terminate_is_idempotent(self) -> None:
        handle = open_pool(Executor.THREAD, 2)
        handle.terminate()
        handle.terminate()
        assert handle.pool is None

    def test_map_after_release_raises(self) -> None:
        handle = open_pool(Executor.THREAD, 2)
        handle.close()

        with pytest.raises(RuntimeError, match="closed worker pool"):
            handle.map(True)


@pytest.mark.slow
class TestBorrowedPool:
    def test_close_leaves_the_pool_open(self) -> None:
        pool = ThreadPool(2)

        try:
            handle = borrow_pool(pool)
            assert not handle.owned

            handle.close()
            assert handle.pool is pool
            assert pool.map(lambda x: x, [1, 2]) == [1, 2]
        finally:
            pool.close()
            pool.join()

    def test_terminate_leaves_the_pool_open(self) -> None:
        pool = ThreadPool(2)

        try:
            handle = borrow_pool(pool)
            handle.terminate()
            assert handle.pool is pool
            assert pool.map(lambda x: x, [1, 2]) == [1, 2]
        finally:
            pool.close()
            pool.join()


@pytest.mark.slow
class TestPoolMap:
    def test_ordered_selects_map(self) -> None:
        handle = open_pool(Executor.THREAD, 2)

        try:
            assert handle.map(True).__name__ == "map"
            assert handle.map(False).__name__ == "imap_unordered"
        finally:
            handle.close()

    def test_mapped_call_works(self) -> None:
        handle = open_pool(Executor.THREAD, 2)

        try:
            assert list(handle.map(True)(str, [1, 2, 3])) == ["1", "2", "3"]
            assert sorted(handle.map(False)(str, [1, 2, 3])) == ["1", "2", "3"]
        finally:
            handle.close()


class TestOpenPool:
    @pytest.mark.slow
    @pytest.mark.parametrize("executor", [Executor.THREAD, Executor.PROCESS])
    def test_builds_an_owned_pool(self, executor: Executor) -> None:
        handle = open_pool(executor, 2)

        try:
            assert handle.owned
            assert handle
            assert getattr(handle.pool, "_processes") == 2  # noqa: B009
        finally:
            handle.close()

    @pytest.mark.parametrize("executor", [Executor.INLINE, Executor.AUTO])
    def test_poolless_executors_have_no_pool(self, executor: Executor) -> None:
        with pytest.raises(ValueError, match=executor.value):
            open_pool(executor, 2)
