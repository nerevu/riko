# vim: sw=4:ts=4:expandtab
"""Provides internal tests for mapping, merging, and closing streams."""

from __future__ import annotations

import threading
import warnings
from functools import partial
from inspect import iscoroutinefunction
from time import perf_counter, sleep
from typing import TYPE_CHECKING
from unittest.mock import ANY, patch

import pytest

from riko.bado import as_async, run
from riko.bado._backend import (
    CancelScope,
    CapacityLimiter,
    Semaphore,
    async_sleep,
    fail_after,
    lowlevel,
)
from riko.bado._backend import asyncify as backend_asyncify
from riko.bado._util import (
    as_awaitable,
    async_partial,
    async_return,
    asyncify,
    gather_results,
    maybe_async,
    maybe_closing,
)
from riko.bado.itertools import (
    aauto_close,
    aislice,
    alist,
    amap,
    async_iter,
    async_map,
    async_map_ordered_stream,
    async_map_stream,
    async_merge,
)
from riko.base._exceptions import InvalidPipelineError
from riko.base._guards import is_async_callable
from riko.base._iterutils import auto_close
from riko.base._sentinels import MISSING
from riko.types._io import require_closer
from tests import async_test, skipif_sync
from tests._resources import AsyncConnection, Connection
from tests._streams import AcloseOnlyClosable, BrokenClosable, Closable, gen_items

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, Iterator

    from riko.types._wrappers import AsyncFunc


async def _double(x: int) -> int:
    return x * 2


_MAP = partial(async_map_stream, _double, range(3))
_ORDERED = partial(async_map_ordered_stream, _double, range(3))
_MERGE = partial(async_merge, [])


def _as_async_from_sync(source: Closable) -> AsyncIterator[int]:
    return as_async(auto_close(iter(()), source))


OWNING_ADAPTERS = [
    pytest.param(partial(amap, str), id="amap"),
    pytest.param(async_iter, id="async_iter"),
    pytest.param(_as_async_from_sync, id="as_async-sync-source"),
    pytest.param(partial(aislice, stop=2), id="aislice"),
]


async def _agen_tracked(closes: list[str]) -> AsyncIterator[int]:
    try:
        for value in (1, 2):
            yield value
    finally:
        closes.append("agen")


class TestAsyncMap:
    @async_test
    async def test_a_missing_result_keeps_its_slot(self):
        """A function returning the missing sentinel still gets its slot."""

        async def missing(_):
            return MISSING

        assert await async_map(missing, [1, 2]) == [MISSING, MISSING]

    @async_test
    async def test_amap_failure_closes_its_source(self):
        closes = []

        def fail(_):
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            await anext(amap(fail, _agen_tracked(closes)))

        assert closes == ["agen"]

    @pytest.mark.parametrize("adapt", OWNING_ADAPTERS)
    @async_test
    async def test_closing_before_the_first_read_closes_the_source_once(self, adapt):
        closes = []
        stream = adapt(Closable("source", closes))
        await stream.aclose()
        await stream.aclose()
        assert closes == ["source"]


def _close_sync(stream: Closable, *closables: object, times: int = 1) -> None:
    wrapper = auto_close(stream, *closables)

    for _ in range(times):
        wrapper.close()


def _close_async(stream: Closable, *closables: object, times: int = 1) -> None:
    async def main() -> None:
        wrapper = aauto_close(stream, *closables)

        for _ in range(times):
            await wrapper.aclose()

    run(main)


def _drain_sync(stream: Closable, *closables: object) -> list[int]:
    return list(auto_close(stream, *closables))


def _drain_async(stream: Closable, *closables: object) -> list[int]:
    return run(alist, aauto_close(stream, *closables))


def _start_sync(closes: list[str], *, finish: bool) -> None:
    wrapper = auto_close(iter([1, 2]), Closable("a", closes))
    next(wrapper)

    if finish:
        wrapper.close()


def _start_async(closes: list[str], *, finish: bool) -> None:
    async def main() -> None:
        wrapper = aauto_close(as_async([1, 2]), Closable("a", closes))
        await anext(wrapper)

        if finish:
            await wrapper.aclose()

    run(main)


def _gen_tracked(closes: list[str]) -> Iterator[int]:
    try:
        yield from (1, 2)
    finally:
        closes.append("gen")


def _drop_sync_streams(closes: list[str]) -> None:
    next(auto_close(_gen_tracked(closes), (x for x in "ab")))


def _drop_async_streams(closes: list[str]) -> None:
    async def main() -> None:
        await anext(aauto_close(_agen_tracked(closes), _gen_tracked(closes)))

    run(main)


AUTO_CLOSERS = [
    pytest.param(_close_sync, id="sync"),
    pytest.param(_close_async, id="async", marks=skipif_sync),
]


AUTO_CLOSE_STARTERS = [
    pytest.param(_start_sync, "auto_close", id="sync"),
    pytest.param(_start_async, "aauto_close", id="async", marks=skipif_sync),
]


AUTO_CLOSE_UNCLOSED = [
    pytest.param(_start_sync, "auto_close", ["a"], id="sync-closes"),
    pytest.param(_start_async, "aauto_close", [], id="async", marks=skipif_sync),
]


AUTO_CLOSE_STREAMS_ONLY = [
    pytest.param(_drop_sync_streams, ["gen"], id="sync"),
    pytest.param(_drop_async_streams, ["agen"], id="async", marks=skipif_sync),
]


AUTO_CLOSE_DRAINS = [
    pytest.param(_drain_sync, id="sync"),
    pytest.param(_drain_async, id="async", marks=skipif_sync),
]


class _ClosableHandle(Closable):
    """Stands in for a closable handle that hands out a distinct closable cursor."""

    def __iter__(self) -> Closable:
        return Closable("cursor", self.closes)

    def __aiter__(self) -> Closable:
        return Closable("cursor", self.closes)


def _handle(closes: list[str]) -> tuple[Closable, ...]:
    return (_ClosableHandle("handle", closes),)


def _handle_also_closable(closes: list[str]) -> tuple[Closable, ...]:
    handle = _ClosableHandle("handle", closes)
    return handle, handle


def _self_iterating(closes: list[str]) -> tuple[Closable, ...]:
    return (Closable("stream", closes),)


# A wrapper's source and closables, and the closes one wrapper close makes.
OWNED_SOURCES = [
    pytest.param(_handle, ["cursor", "handle"], id="distinct-cursor"),
    pytest.param(_handle_also_closable, ["cursor", "handle"], id="handle-closable"),
    pytest.param(_self_iterating, ["stream"], id="self-iterating"),
]


def _async_only_source(closes: list[str]) -> tuple[Closable, ...]:
    return (AcloseOnlyClosable("stream", closes),)


def _async_only_closable(closes: list[str]) -> tuple[Closable, ...]:
    return Closable("stream", closes), AcloseOnlyClosable("a", closes)


# A wrapper's source and closables, one of which only closes asynchronously.
ASYNC_ONLY_OWNED = [
    pytest.param(_async_only_source, id="source"),
    pytest.param(_async_only_closable, id="closable"),
]


class _CancellingClosable(Closable):
    """Stands in for a value whose async close records itself, then is cancelled."""

    def __init__(self, name: str, closes: list[str], scope: CancelScope) -> None:
        super().__init__(name, closes)
        self.scope = scope

    async def aclose(self) -> None:
        self.closes.append(self.name)
        self.scope.cancel()
        await lowlevel.checkpoint()


class _FinallyClosable(AcloseOnlyClosable):
    """Stands in for a value whose async close awaits, then records itself anyway."""

    async def aclose(self) -> None:
        try:
            await lowlevel.checkpoint()
        finally:
            self.closes.append(self.name)


# Whether sync closes run on the event loop, and the closes a cancelled aclose makes.
CANCELLED_CLOSES = [
    pytest.param(True, ["first", "later", "sync"], id="inline"),
    pytest.param(
        False,
        ["first", "later", "sync"],
        id="worker",
        marks=pytest.mark.xfail(
            strict=True,
            raises=AssertionError,
            reason=(
                "handing a cancelled close's remaining worker closes to the execution "
                "is not yet implemented"
            ),
        ),
    ),
]


class _BlockingClosable:
    """Stands in for a value whose close blocks until *release* is set."""

    def __init__(self, release: threading.Event, closes: list[str]) -> None:
        self.release = release
        self.closes = closes

    def close(self) -> None:
        self.release.wait(3)
        self.closes.append("closed")


class TestAutoClose:
    """Test the wrappers that close a stream's backing values when iteration ends."""

    @pytest.mark.parametrize("close", AUTO_CLOSERS)
    def test_close_before_read_closes_everything(self, close):
        closes = []
        close(Closable("stream", closes), Closable("a", closes), Closable("b", closes))
        assert closes == ["stream", "a", "b"]

    @pytest.mark.parametrize(("build", "expected"), OWNED_SOURCES)
    @pytest.mark.parametrize("close", AUTO_CLOSERS)
    def test_close_closes_the_source_and_its_iterator_once(
        self, close, build, expected
    ):
        closes = []
        close(*build(closes), times=2)
        assert closes == expected

    @pytest.mark.parametrize("drain", AUTO_CLOSE_DRAINS)
    def test_stream_error_closes_and_propagates(self, drain):
        closes = []
        stream = Closable("stream", closes, ValueError("boom"))

        with pytest.raises(ValueError, match="boom"):
            drain(stream, Closable("a", closes))

        assert closes == ["stream", "a"]

    @pytest.mark.parametrize("close", AUTO_CLOSERS)
    def test_several_failed_closes_raise_together(self, close):
        closes = []
        broken = (BrokenClosable("a", closes), BrokenClosable("b", closes))

        with pytest.raises(ExceptionGroup, match="multiple errors") as info:
            close(Closable("stream", closes), *broken)

        assert closes == ["stream", "a", "b"]
        assert len(info.value.exceptions) == 2

    @pytest.mark.parametrize("close", AUTO_CLOSERS)
    def test_single_failed_close_raises_after_every_close(self, close):
        closes = []
        values = (BrokenClosable("a", closes), Closable("b", closes))

        with pytest.raises(OSError, match="a close failed"):
            close(Closable("stream", closes), *values)

        assert closes == ["stream", "a", "b"]

    @pytest.mark.parametrize("drain", AUTO_CLOSE_DRAINS)
    def test_close_failure_after_a_read_error_is_noted_on_it(self, drain):
        closes = []
        stream = Closable("stream", closes, ValueError("boom"))

        with pytest.raises(ValueError, match="boom") as info:
            drain(stream, BrokenClosable("a", closes))

        failure = OSError("a close failed")
        assert info.value.__notes__ == [f"closing the stream also failed: {failure!r}"]
        assert closes == ["stream", "a"]

    @pytest.mark.parametrize("drain", AUTO_CLOSE_DRAINS)
    def test_close_failure_after_exhaustion_raises(self, drain):
        closes = []

        with pytest.raises(OSError, match="a close failed"):
            drain(Closable("stream", closes), BrokenClosable("a", closes))

        assert closes == ["stream", "a"]

    @pytest.mark.parametrize("close", AUTO_CLOSERS)
    def test_second_close_does_nothing(self, close):
        closes = []
        close(Closable("stream", closes), Closable("a", closes), times=2)
        assert closes == ["stream", "a"]

    @pytest.mark.parametrize("build", ASYNC_ONLY_OWNED)
    def test_a_value_it_can_only_close_asynchronously_is_refused(self, build):
        closes: list[str] = []

        with pytest.raises(InvalidPipelineError, match="only close is async"):
            auto_close(*build(closes))

        assert closes == []

    @skipif_sync
    @pytest.mark.parametrize("build", ASYNC_ONLY_OWNED)
    def test_a_bridge_closes_a_value_it_can_only_close_asynchronously(self, build):
        closes: list[str] = []
        values = build(closes)
        assert list(auto_close(*values, bridge=partial(run, as_awaitable))) == []
        assert closes == [value.name for value in values]

    def test_maybe_closing_refuses_a_value_it_can_only_close_asynchronously(self):
        closes: list[str] = []

        with pytest.raises(InvalidPipelineError, match="only close is async"):
            maybe_closing(*_async_only_source(closes))

        assert closes == []

    def test_none_closable_is_skipped(self):
        closes = []
        _close_sync(Closable("stream", closes), None, Closable("a", closes))
        assert closes == ["stream", "a"]

    @pytest.mark.parametrize(("start", "name", "closed"), AUTO_CLOSE_UNCLOSED)
    def test_dropping_a_started_unclosed_wrapper_warns(self, start, name, closed):
        closes = []

        with pytest.warns(ResourceWarning, match=f"unclosed {name} stream"):
            start(closes, finish=False)

        assert closes == closed

    @pytest.mark.parametrize(("start", "name"), AUTO_CLOSE_STARTERS)
    def test_dropping_a_closed_wrapper_does_not_warn(self, start, name):
        closes = []

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            start(closes, finish=True)

        assert closes == ["a"]
        assert caught == []

    @pytest.mark.parametrize(("drop", "closed"), AUTO_CLOSE_STREAMS_ONLY)
    def test_dropping_an_unclosed_wrapper_of_streams_does_not_warn(self, drop, closed):
        closes = []

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            drop(closes)

        assert closes == closed
        assert caught == []

    @pytest.mark.timeout(10)
    @skipif_sync
    def test_a_cancelled_aclose_stops_waiting_for_a_worker_close(self) -> None:
        release = threading.Event()
        closes: list[str] = []

        async def main() -> None:
            blocking = _BlockingClosable(release, closes)
            wrapper = aauto_close(as_async([1]), blocking, inline=False)
            await anext(wrapper)

            with pytest.raises(TimeoutError), fail_after(1):
                await wrapper.aclose()

        start = perf_counter()
        run(main)
        assert perf_counter() - start < 2
        release.set()
        deadline = perf_counter() + 1

        while not closes and perf_counter() < deadline:
            sleep(0.01)

        assert closes == ["closed"]

    @pytest.mark.parametrize(("inline", "expected"), CANCELLED_CLOSES)
    @async_test
    async def test_a_cancelled_aclose_still_calls_every_later_close(
        self, inline: bool, expected: list[str]
    ) -> None:
        closes: list[str] = []
        scope = CancelScope()
        first = _CancellingClosable("first", closes, scope)
        later = _CancellingClosable("later", closes, scope)
        wrapper = aauto_close(first, later, Closable("sync", closes), inline=inline)

        with scope:
            await wrapper.aclose()

        with fail_after(1):
            await wrapper.aclose()

        assert scope.cancelled_caught
        assert closes == expected

    @async_test
    async def test_a_cancelled_aclose_releases_a_close_that_awaits_first(self) -> None:
        closes: list[str] = []
        scope = CancelScope()
        first = _CancellingClosable("first", closes, scope)
        wrapper = aauto_close(first, _FinallyClosable("later", closes))

        with scope, fail_after(1):
            await wrapper.aclose()

        assert scope.cancelled_caught
        assert closes == ["first", "later"]


ACLOSE_CASES = [
    pytest.param(Connection, Connection.close, id="sync-cleanup"),
    pytest.param(Connection, None, id="sync-close"),
    pytest.param(AsyncConnection, AsyncConnection.aclose, id="async-cleanup"),
    pytest.param(AsyncConnection, None, id="async-close"),
]


class TestRequireCloser:
    """Test the closer a value or its cleanup resolves to."""

    @pytest.mark.parametrize(("client_class", "cleanup"), ACLOSE_CASES)
    @async_test
    async def test_closer_closes_the_value(self, client_class, cleanup) -> None:
        client = client_class()
        closer = require_closer(client, cleanup, is_async=True)
        assert closer is not None
        await maybe_async(closer)
        assert client.closed is True


def _budgeted_probe() -> tuple[dict[str, int], Callable[[int], Awaitable[int]]]:
    state = {"current": 0, "peak": 0}

    async def leaf(x: int) -> int:
        state["current"] += 1
        state["peak"] = max(state["peak"], state["current"])
        await async_sleep(0.01)
        state["current"] -= 1
        return x

    return state, leaf


def _sync_forever(closed: list[bool]):
    index = 0

    try:
        while True:
            yield index
            index += 1
    finally:
        closed.append(True)


MAP_STREAMS = [
    pytest.param(async_map_stream, id="unordered"),
    pytest.param(async_map_ordered_stream, id="ordered"),
]


INFLIGHT_BOUNDS = [
    pytest.param(async_map_stream, 3 + 2 + 2, id="unordered"),
    pytest.param(async_map_ordered_stream, 2 * (3 + 2), id="ordered"),
]


BUDGET_ARRANGEMENTS = [
    pytest.param(async_map_stream, sorted, id="unordered"),
    pytest.param(async_map_ordered_stream, list, id="ordered"),
]


EARLY_CLOSE_FIRSTS = [
    pytest.param(async_map_stream, {0, 2}, id="unordered"),
    pytest.param(async_map_ordered_stream, {0}, id="ordered"),
]


CROSS_TASK_CLOSES = [
    pytest.param(partial(async_map_stream, _double, limit=2), id="map"),
    pytest.param(lambda items: async_merge([items], limit=2), id="merge"),
]


STREAM_OPTION_REJECTIONS = [
    pytest.param({"limit": 0}, "limit must be at least 1", id="limit"),
    pytest.param({"buffer": -1}, "buffer cannot be negative", id="buffer"),
]


async def _forever(closed: list[bool]):
    index = 0

    try:
        while True:
            yield index
            index += 1
    finally:
        closed.append(True)


class TestAsyncMapStream:
    """
    Test the bounded-memory async map streams.

    ``async_map_stream`` is concurrent, order-independent, and bounded-memory;
    ``async_map_ordered_stream`` keeps the same bound while preserving source order.
    """

    @skipif_sync
    @pytest.mark.parametrize("stream", MAP_STREAMS)
    def test_empty_source_yields_nothing(self, stream):
        assert run(alist, stream(_double, [], limit=4)) == []

    @skipif_sync
    def test_accepts_async_source(self):
        async def gen():
            for i in range(5):
                yield i

        results = run(alist, async_map_stream(_double, gen(), limit=2))
        assert sorted(results) == [0, 2, 4, 6, 8]

    @pytest.mark.parametrize(("stream", "bound"), INFLIGHT_BOUNDS)
    @async_test
    async def test_backpressure_bounds_inflight(self, stream, bound):
        """An unbounded-ish source with a slow consumer must not run far ahead."""
        total = 200
        produced = 0

        async def gen():
            nonlocal produced
            for i in range(total):
                produced += 1
                yield i

        seen = 0

        async for _ in stream(_double, gen(), limit=3, buffer=2):
            seen += 1
            assert produced - seen <= bound
            await lowlevel.checkpoint()

        assert produced == total == seen

    @skipif_sync
    def test_ordered_preserves_source_order_under_skew(self):
        """The slowest item is first, so an unordered map would reorder it."""

        async def slow_first(i: int) -> int:
            await async_sleep((5 - i) * 0.01)
            return i

        result = run(alist, async_map_ordered_stream(slow_first, range(6), limit=3))
        assert result == list(range(6))

    @async_test
    async def test_shared_budget_caps_nested_fanout(self):
        """
        Share one concurrency budget across leaf maps.

        An outer fan-out of 4 items, each with 5 leaf operations, has 20 potential
        operations but never exceeds a budget of 3. The outer fan-out remains
        unbudgeted to avoid deadlock.
        """
        state, leaf = _budgeted_probe()
        budget = Semaphore(3)

        async def source(i: int) -> list[int]:
            leaves = async_map_stream(leaf, range(5), limit=10, budget=budget)
            return [r async for r in leaves]

        outer = async_map_stream(source, range(4), limit=10)
        results = [r async for r in outer]
        assert len(results) == 4
        assert state["peak"] <= 3

    @pytest.mark.parametrize(("stream", "arrange"), BUDGET_ARRANGEMENTS)
    @async_test
    async def test_shared_budget_caps_concurrent_streams(self, stream, arrange):
        """Two concurrent maps sharing a budget of 3 never exceed it."""
        state, leaf = _budgeted_probe()
        budget = Semaphore(3)

        async def collect() -> list[int]:
            mapped = stream(leaf, range(10), limit=4, budget=budget)
            return [r async for r in mapped]

        results = await gather_results([collect(), collect()])
        assert [arrange(result) for result in results] == [list(range(10))] * 2
        assert 1 < state["peak"] <= 3

    @pytest.mark.parametrize(("stream", "firsts"), EARLY_CLOSE_FIRSTS)
    @pytest.mark.parametrize(
        "source", [_forever, _sync_forever], ids=["async-source", "sync-source"]
    )
    @async_test
    async def test_early_close_stops_workers_and_closes_source(
        self, stream, firsts, source
    ):
        closed: list[bool] = []
        items = source(closed)

        with fail_after(1):
            mapped = stream(_double, items, limit=2)
            first = await anext(mapped)
            await mapped.aclose()

        assert first in firsts
        assert closed == [True]

    @skipif_sync
    @pytest.mark.parametrize(
        "build", [_MAP, _ORDERED, _MERGE], ids=["map", "ordered", "merge"]
    )
    @pytest.mark.parametrize(("kwargs", "match"), STREAM_OPTION_REJECTIONS)
    def test_rejects_bad_limit_or_buffer(self, build, kwargs, match):
        with pytest.raises(ValueError, match=match):
            run(alist, build(**kwargs))

    @pytest.mark.xfail(
        strict=True,
        raises=RuntimeError,
        reason="closing a concurrent map stream from another task is not yet "
        "implemented",
    )
    @pytest.mark.parametrize("build", CROSS_TASK_CLOSES)
    @async_test
    async def test_aclose_from_another_task_stops_the_stream(self, build):
        closed: list[bool] = []
        mapped = build(_forever(closed))
        await anext(mapped)
        await gather_results([mapped.aclose()])
        assert closed == [True]
        assert await anext(mapped, None) is None

    @pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason="sliding-window async ordered mapping is not yet implemented",
    )
    @async_test
    async def test_ordered_yields_ready_results_while_a_later_item_runs(self):
        """A slow second item never holds back the first result or the third start."""
        log: list[str] = []

        async def slow_second(i: int) -> int:
            log.append(f"start {i}")
            await async_sleep(0.05 if i == 1 else 0)
            log.append(f"done {i}")
            return i

        async for i in async_map_ordered_stream(slow_second, range(4), limit=2):
            log.append(f"yield {i}")

        assert log.index("yield 0") < log.index("done 1")
        assert log.index("start 2") < log.index("done 1")


class TestAsyncMerge:
    @async_test
    async def test_early_close_closes_every_source(self):
        """Closing the merge after one item closes every source cleanly."""
        closed: list[bool] = []

        with fail_after(1):
            merged = async_merge([_forever(closed), _forever(closed)], limit=2)
            await anext(merged)
            await merged.aclose()

        assert closed == [True, True]

    @skipif_sync
    def test_async_merge_yields_every_value(self):
        """More iterables than ``limit`` still merge in full."""
        iterables = [gen_items([1, 2]), gen_items([3, 4]), gen_items([5])]
        assert sorted(run(alist, async_merge(iterables, limit=2))) == [1, 2, 3, 4, 5]

    @async_test
    async def test_async_merge_interleaves_across_iterables(self):
        """A fast iterable's items surface before a slow one finishes (incremental)."""
        slow = gen_items(["slow1", "slow2"], delay=0.05)
        fast = gen_items(["fast1", "fast2"])
        out = [item async for item in async_merge([slow, fast], limit=2)]
        assert sorted(out) == ["fast1", "fast2", "slow1", "slow2"]
        assert out.index("fast2") < out.index("slow2")


class TestGatherResults:
    @async_test
    async def test_gather_results_preserves_none_positions(self):
        """A legitimate ``None`` result stays in place; output aligns with inputs."""
        awaitables = [async_return(None), async_return(1), async_return(None)]
        result = await gather_results(awaitables)
        assert result == [None, 1, None]


def _echo(value: int, **options: object) -> tuple[int, dict[str, object], int]:
    return value, options, threading.get_ident()


async def _aecho(value: int, **options: object) -> tuple[int, dict[str, object], int]:
    return _echo(value, **options)


def _echo_later(value: int, **options: object) -> Awaitable[tuple]:
    return _aecho(value, **options)


class _AsyncEcho:
    async def __call__(
        self, value: int, **options: object
    ) -> tuple[int, dict[str, object], int]:
        return _echo(value, **options)


RUNNER_CALLABLES = [
    pytest.param(_echo, id="sync"),
    pytest.param(_aecho, id="async"),
    pytest.param(_echo_later, id="sync-returns-awaitable"),
]


RUNNERS = [
    pytest.param(maybe_async, id="inline"),
    pytest.param(asyncify, id="worker"),
    pytest.param(asyncify.using(abandon_on_cancel=True), id="abandoning-worker"),
]


ASYNC_CALLABLES = [
    pytest.param(maybe_async, id="inline-runner"),
    pytest.param(asyncify, id="worker-runner"),
    pytest.param(partial(_AsyncEcho()), id="partial-of-async-instance"),
    pytest.param(partial(partial(_aecho)), id="nested-partial"),
    pytest.param(partial(partial(_AsyncEcho())), id="nested-partial-of-async-instance"),
]


RUNNER_PARTIALS = [
    pytest.param(async_partial, id="async_partial"),
    pytest.param(asyncify.partial, id="worker-partial"),
]


class TestAsyncRunner:
    """Test the runner that awaits a sync or async callable's result."""

    @pytest.mark.parametrize("runner", RUNNERS)
    @pytest.mark.parametrize("func", RUNNER_CALLABLES)
    @async_test
    async def test_runner_forwards_every_argument_to_the_callee(
        self, func, runner
    ) -> None:
        options = {"inline": 0, "limiter": 1, "abandon_on_cancel": 2, "mode": "fast"}
        value, received, _ = await runner(func, 1, **options)
        assert (value, received) == (1, options)

    @async_test
    async def test_a_worker_runner_using_inline_runs_on_the_loop(self) -> None:
        _, _, ident = await asyncify.using(inline=True)(_echo, 1)
        assert ident == threading.get_ident()

    @async_test
    async def test_using_keeps_the_settings_it_does_not_change(self) -> None:
        limiter = CapacityLimiter(1)
        limited = asyncify.using(abandon_on_cancel=True).using(limiter=limiter)
        cleared = limited.using(limiter=None)
        expected = [(False, limiter, True), (False, None, True), (False, None, False)]
        runners = [limited, cleared, asyncify]
        settings = [(r.inline, r.limiter, r.abandon_on_cancel) for r in runners]
        assert settings == expected
        assert await limited(_echo, 1, limiter=2) == (1, {"limiter": 2}, ANY)

    @pytest.mark.parametrize("build", RUNNER_PARTIALS)
    @async_test
    async def test_partial_binds_arguments_for_repeated_calls(self, build) -> None:
        call = build(_echo, mode="fast")
        assert is_async_callable(call)
        assert iscoroutinefunction(call)
        results = [(await call(value))[:2] for value in (1, 2)]
        assert results == [(1, {"mode": "fast"}), (2, {"mode": "fast"})]

    @async_test
    async def test_partial_awaits_an_async_instance_without_a_worker(self) -> None:
        call: AsyncFunc[tuple[int, dict[str, object], int]] = asyncify.partial(
            _AsyncEcho(), mode="fast"
        )

        with patch("riko.bado._util._asyncify", wraps=backend_asyncify) as worker:
            value, received, _ = await call(1)

        assert (value, received, worker.call_count) == (1, {"mode": "fast"}, 0)

    @pytest.mark.parametrize("func", ASYNC_CALLABLES)
    def test_is_async_callable_sees_through_runners_and_partials(self, func) -> None:
        assert is_async_callable(func)
