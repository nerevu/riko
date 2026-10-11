# vim: sw=4:ts=4:expandtab
"""Tests for the private synchronous worker-pool machinery."""

from multiprocessing import cpu_count

import pytest

from riko.base.exceptions import PipelineStateError
from riko.execution._pools import get_worker_cnt, open_pool
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


@pytest.mark.slow
class TestPoolHandle:
    def test_close_releases_the_pool(self) -> None:
        handle = open_pool(Executor.THREAD, 2)
        assert handle

        handle.close()
        assert handle.pool is None
        assert not handle

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

    def test_terminate_is_idempotent(self) -> None:
        handle = open_pool(Executor.THREAD, 2)
        handle.terminate()
        handle.terminate()
        assert handle.pool is None

    def test_require_pool_after_release_raises(self) -> None:
        handle = open_pool(Executor.THREAD, 2)
        handle.close()

        match = "cannot reuse the worker pool in state 'closed'"
        with pytest.raises(PipelineStateError, match=match):
            handle.require_pool()


class TestOpenPool:
    @pytest.mark.slow
    @pytest.mark.parametrize("executor", [Executor.THREAD, Executor.PROCESS])
    def test_builds_a_pool(self, executor: Executor) -> None:
        handle = open_pool(executor, 2)

        try:
            assert handle
            assert getattr(handle.pool, "_processes") == 2  # noqa: B009
        finally:
            handle.close()

    @pytest.mark.parametrize("executor", [Executor.INLINE, Executor.AUTO])
    def test_poolless_executors_have_no_pool(self, executor: Executor) -> None:
        with pytest.raises(ValueError, match=executor.value):
            open_pool(executor, 2)
