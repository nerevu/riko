# vim: sw=4:ts=4:expandtab
"""Provides internal tests for teeing one stream into several branches."""

from __future__ import annotations

import threading
from functools import partial
from itertools import count
from typing import TYPE_CHECKING

import pytest

from riko.bado._backend import (
    CancelScope,
    Event,
    checkpoint,
    create_task_group,
    fail_after,
)
from riko.bado.itertools import AsyncTee, AsyncTeeBranch, alist
from riko.base._exceptions import PipelineError, PipelineStateError
from riko.base._iterutils import Tee
from tests import async_test, skipif_sync
from tests._streams import AsyncPullLog, PullLog, gen_items

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable


_PULL_CLOSE = ["pull", "close"]


class _Uncopyable:
    """Deep-copies once, then raises ``failure`` from every later ``deepcopy``."""

    def __init__(self, failure: BaseException) -> None:
        self.failure, self.copies = failure, 0

    def __deepcopy__(self, memo: dict[int, object]) -> _Uncopyable:
        self.copies += 1

        if self.copies > 1:
            raise self.failure

        return _Uncopyable(self.failure)


class _Source:
    """Yields ``items``, raising any exception among them, and logs pulls and closes."""

    def __init__(
        self,
        items: list[object],
        log: list[str],
        *,
        gate: threading.Event | None = None,
        close_error: BaseException | None = None,
    ):
        self.items, self.log, self.gate = iter(items), log, gate
        self.close_error = close_error
        self.reached = threading.Event()

    def __iter__(self) -> _Source:
        return self

    def __next__(self) -> object:
        self.log.append("pull")

        if self.gate is not None:
            self.reached.set()
            self.gate.wait(timeout=5)

        item = next(self.items)

        if isinstance(item, BaseException):
            raise item

        return item

    def close(self) -> None:
        self.log.append("close")

        if self.close_error is not None:
            raise self.close_error


class _ASource:
    """Yields ``items`` asynchronously, raising any exception among them, with a log."""

    def __init__(
        self,
        items: list[object],
        log: list[str],
        *,
        gate: Event | None = None,
        close_gate: Event | None = None,
        close_error: BaseException | None = None,
    ):
        self.items, self.log, self.gate = iter(items), log, gate
        self.close_gate, self.close_error = close_gate, close_error
        self.reached, self.closing = Event(), Event()

    def __aiter__(self) -> _ASource:
        return self

    async def __anext__(self) -> object:
        self.log.append("pull")

        if self.gate is not None:
            self.reached.set()
            await self.gate.wait()

        try:
            item = next(self.items)
        except StopIteration:
            raise StopAsyncIteration from None

        if isinstance(item, BaseException):
            raise item

        return item

    async def aclose(self) -> None:
        self.closing.set()

        if self.close_gate is not None:
            await self.close_gate.wait()

        self.log.append("close")

        if self.close_error is not None:
            raise self.close_error


async def _aclose_each(branches: Iterable[AsyncTeeBranch[object]]) -> None:
    for branch in branches:
        await branch.aclose()


async def _until_waiting(tee: AsyncTee[object]) -> None:
    while tee._read_done is None:
        await checkpoint()


class _WatchedCondition(threading.Condition):
    """Sets ``waiting`` whenever a thread starts waiting on the condition."""

    def __init__(self, lock: threading.Lock, waiting: threading.Event):
        super().__init__(lock)
        self.waiting = waiting

    def wait(self, timeout: float | None = None) -> bool:
        self.waiting.set()
        return super().wait(timeout)


def _start(func: Callable[[], object], results: list[object]) -> threading.Thread:
    def target() -> None:
        try:
            results.append(func())
        except BaseException as error:  # noqa: BLE001 (the test inspects it)
            results.append(error)

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return thread


_LATE_BRANCHES = [
    pytest.param("reading", lambda _, first: next(first), id="after-read"),
    pytest.param("closed", lambda tee, _: tee.close(), id="after-close"),
    pytest.param("done", lambda _, first: list(first), id="after-exhaustion"),
]


_REENTRANT_READS = [
    pytest.param(True, id="buffered"),
    pytest.param(False, id="advancing"),
]


_DEFERRED_CLOSES = [
    pytest.param(lambda tee, _: tee.close(), id="tee"),
    pytest.param(lambda _, branches: [b.close() for b in branches], id="last"),
]


_ALATE_BRANCHES = [
    pytest.param("reading", lambda _, first: anext(first), id="after-read"),
    pytest.param("closed", lambda tee, _: tee.aclose(), id="after-close"),
    pytest.param("done", lambda _, first: alist(first), id="after-exhaustion"),
]


_ADEFERRED_CLOSES = [
    pytest.param(lambda tee, _: tee.aclose(), id="tee"),
    pytest.param(lambda _, branches: _aclose_each(branches), id="last"),
]


_BAD_LAGS = [
    pytest.param(0, ValueError, "at least 1", id="zero"),
    pytest.param(2.5, TypeError, "an integer or math.inf", id="fraction"),
]


class TestTee:
    def test_branches_in_any_order_see_every_item_once_pulled(self):
        """Every branch sees each item in order however reads interleave."""
        source = PullLog(range(4))
        tee = Tee(source)
        first, second, third = tee.branch(), tee.branch(), tee.branch()
        assert list(second) == [0, 1, 2, 3]
        assert [next(third), next(first), next(first), next(third)] == [0, 0, 1, 1]
        assert (list(first), list(third)) == ([2, 3], [2, 3])
        assert len(source.pulled) == 4
        assert source.closes == 1

    def test_isolate_copies_for_every_branch_but_the_puller(self):
        """The puller gets the original; siblings get a deep copy."""
        items = [{"n": [1]}]
        tee = Tee(items, isolate=True)
        first, second = tee.branch(), tee.branch()
        original, duplicate = next(first), next(second)
        duplicate["n"].append(2)
        assert original is items[0]
        assert duplicate is not original
        assert original == {"n": [1]}
        tee.close()

    def test_max_lag_overflow_discards_every_buffer_and_keeps_raising(self):
        """An overflow empties every queue, closes the source, and fails each read."""
        log: list[str] = []
        tee = Tee(_Source(list(range(5)), log), max_lag=2)
        first, second = tee.branch(), tee.branch()
        assert [next(first), next(first)] == [0, 1]

        with pytest.raises(
            PipelineError, match=r"2 items.*RIKO_BRANCH_BUFFER"
        ) as raised:
            next(first)

        assert not any(tee._buffers.values())
        assert log == ["pull", "pull", "close"]

        for branch in (second, first):
            with pytest.raises(PipelineError) as again:
                next(branch)

            assert again.value is raised.value

    def test_closing_branches_frees_buffers_then_closes_source_once(self):
        """A closed branch drops its queue; the last close closes the source once."""
        source = PullLog(range(3))
        tee = Tee(source)
        first, second, third = tee.branch(), tee.branch(), tee.branch()
        next(first)
        second.close()
        assert len(tee._buffers) == 2
        assert list(first) == [1, 2]
        third.close()
        tee.close()
        assert len(source.pulled) == 3
        assert source.closes == 1

    def test_upstream_error_reaches_every_branch(self):
        """The puller raises first; a sibling drains its queue, then re-raises."""
        error, log = ValueError("boom"), []
        tee = Tee(_Source([1, error], log))
        first, second = tee.branch(), tee.branch()
        assert next(first) == 1

        with pytest.raises(ValueError, match="boom") as pulled:
            next(first)

        assert log == ["pull", "pull", "close"]
        assert next(second) == 1

        for branch in (second, first):
            with pytest.raises(ValueError, match="boom") as again:
                next(branch)

            assert again.value is pulled.value is error

    def test_copy_failure_on_the_second_branch_commits_nothing(self):
        """A failed copy queues the item for no branch and fails every branch."""
        log: list[str] = []
        failure = TypeError("uncopyable")
        source = _Source([_Uncopyable(failure), 2], log)
        tee = Tee(source, isolate=True)
        first, second, third = tee.branch(), tee.branch(), tee.branch()

        with pytest.raises(PipelineError, match="could not deepcopy") as raised:
            next(first)

        assert raised.value.__cause__ is failure
        assert not any(tee._buffers.values())
        assert log == _PULL_CLOSE

        for branch in (second, third):
            with pytest.raises(PipelineError) as again:
                next(branch)

            assert again.value is raised.value

    def test_buffered_read_does_not_wait_for_a_blocked_upstream(self):
        """A branch with queued items reads them while another thread is blocked."""
        gate, log, results, buffered = threading.Event(), [], [], []
        source = _Source([0, 1], log, gate=gate)
        tee = Tee(source)
        first, second = tee.branch(), tee.branch()
        gate.set()
        assert next(first) == 0
        gate.clear()
        source.reached.clear()
        thread = _start(partial(next, first), results)

        try:
            assert source.reached.wait(timeout=1)
            waiter = _start(partial(next, second), buffered)
            waiter.join(timeout=1)
            assert not waiter.is_alive()
            assert buffered == [0]
        finally:
            gate.set()

        thread.join(timeout=1)
        tee.close()
        assert not thread.is_alive()
        assert results == [1]

    @pytest.mark.parametrize("queued", _REENTRANT_READS)
    def test_reentrant_advance_raises_and_reentrant_buffered_read_is_allowed(
        self, queued
    ):
        """Reading a branch from inside the source works only when it has a queue."""
        seen: list[int] = []

        def gen_items():
            yield 0
            seen.append(next(second))
            yield 1

        tee = Tee(gen_items())
        first, second = tee.branch(), tee.branch()

        if queued:
            assert [next(first), next(first)] == [0, 1]
            assert seen == [0]
        else:
            next(second)
            assert next(first) == 0

            with pytest.raises(PipelineStateError, match="advancing"):
                next(first)

        tee.close()

    @pytest.mark.parametrize("close", _DEFERRED_CLOSES)
    def test_closing_the_last_branch_mid_read_defers_the_source_close(self, close):
        """The close returns at once; the blocked reader closes the source after."""
        gate, log, results = threading.Event(), [], []
        source = _Source([0, 1], log, gate=gate)
        tee = Tee(source)
        first, second = tee.branch(), tee.branch()
        thread = _start(partial(list, first), results)

        try:
            assert source.reached.wait(timeout=1)
            close(tee, (second, first))
            assert log == ["pull"]
        finally:
            gate.set()

        thread.join(timeout=1)
        assert not thread.is_alive()
        assert (results, log) == ([[]], _PULL_CLOSE)

    def test_a_failing_deferred_close_is_logged_not_raised(self, riko_warnings):
        """The blocked reader logs the source close failure and still ends normally."""
        gate, log, results = threading.Event(), [], []
        failure = OSError("close failed")
        source = _Source([0, 1], log, gate=gate, close_error=failure)
        tee = Tee(source)
        first, _ = tee.branch(), tee.branch()

        thread = _start(partial(list, first), results)

        try:
            assert source.reached.wait(timeout=1)
            tee.close()
        finally:
            gate.set()

        thread.join(timeout=1)

        assert not thread.is_alive()
        assert (results, log) == ([[]], _PULL_CLOSE)
        assert [(r.getMessage(), r.exc_info[1]) for r in riko_warnings.records] == [
            ("closing the source failed", failure)
        ]

    def test_closing_a_waiting_branch_ends_it_promptly(self):
        """A branch waiting on another thread's read ends as soon as it is closed."""
        log, results = [], []
        gate, waiting = threading.Event(), threading.Event()
        source = _Source([0, 1], log, gate=gate)
        tee = Tee(source)
        tee._ready = _WatchedCondition(tee._lock, waiting)
        first, second = tee.branch(), tee.branch()
        reader = _start(partial(list, first), results)

        try:
            assert source.reached.wait(timeout=1)
            waiter = _start(partial(list, second), results)
            assert waiting.wait(timeout=1)
            second.close()
            waiter.join(timeout=1)
            assert not waiter.is_alive()
            assert results == [[]]
        finally:
            gate.set()

        reader.join(timeout=1)
        assert not reader.is_alive()
        assert results == [[], [0, 1]]

    def test_branches_closed_during_the_read_get_no_copy(self):
        """Branches closed while another thread reads upstream get no copy of it."""
        gate, log, results = threading.Event(), [], []
        item = _Uncopyable(TypeError("uncopyable"))
        source = _Source([item, 1], log, gate=gate)
        tee = Tee(source, isolate=True)
        first, second, third = tee.branch(), tee.branch(), tee.branch()
        thread = _start(partial(next, first), results)

        try:
            assert source.reached.wait(timeout=1)
            second.close()
            third.close()
        finally:
            gate.set()

        thread.join(timeout=1)
        assert not thread.is_alive()
        assert (results, item.copies) == ([item], 0)
        tee.close()

    def test_cleanup_failure_at_eof_is_raised_after_the_drain(self):
        """A source that fails to close fails each branch once it has drained."""
        failure = OSError("close failed")
        tee = Tee(_Source([1], [], close_error=failure))
        first, second = tee.branch(), tee.branch()
        assert next(first) == 1

        with pytest.raises(OSError, match="close failed") as raised:
            next(first)

        assert raised.value is failure
        assert next(second) == 1

        for branch in (second, second, first):
            with pytest.raises(OSError, match="close failed"):
                next(branch)

    def test_cleanup_failure_beside_a_read_error_keeps_the_primary(self, riko_warnings):
        """The read error stays primary and notes and logs the close failure."""
        error, failure = ValueError("boom"), OSError("close failed")
        tee = Tee(_Source([error], [], close_error=failure))
        first = tee.branch()

        with pytest.raises(ValueError, match="boom") as raised:
            next(first)

        assert raised.value.__notes__ == [
            f"closing the stream also failed: {failure!r}"
        ]
        assert [record.exc_info[1] for record in riko_warnings.records] == [failure]

    def test_cleanup_failure_beside_an_overflow_keeps_the_overflow(self, riko_warnings):
        """The overflow stays primary and notes and logs the close failure."""
        failure = OSError("close failed")
        tee = Tee(_Source([0, 1], [], close_error=failure), max_lag=1)
        first, _ = tee.branch(), tee.branch()
        assert next(first) == 0

        with pytest.raises(PipelineError, match="1 items") as raised:
            next(first)

        assert raised.value.__notes__ == [
            f"closing the source also failed: {failure!r}"
        ]
        assert [record.exc_info[1] for record in riko_warnings.records] == [failure]

    def test_interrupted_cleanup_beside_an_overflow_keeps_the_overflow(
        self, riko_warnings
    ):
        """The overflow stays primary and discards when its cleanup is interrupted."""
        interrupt = KeyboardInterrupt()
        tee = Tee(_Source([0, 1], [], close_error=interrupt), max_lag=1)
        first, second = tee.branch(), tee.branch()
        assert next(first) == 0

        with pytest.raises(KeyboardInterrupt) as raised:
            next(first)

        assert raised.value is interrupt
        assert not any(tee._buffers.values())

        with pytest.raises(PipelineError, match="1 items") as again:
            next(second)

        assert again.value.__notes__ == [
            f"closing the source also failed: {interrupt!r}"
        ]
        assert [record.exc_info[1] for record in riko_warnings.records] == [interrupt]

    def test_infinite_stream_reads_incrementally(self):
        """Branches over an endless source pull only what is asked for."""
        source = PullLog(count())
        tee = Tee(source)
        first, second = tee.branch(), tee.branch()
        assert [next(first), next(first), next(second)] == [0, 1, 0]
        assert len(source.pulled) == 2
        assert not source.closed
        tee.close()

    def test_interrupted_read_reraises_and_fails_siblings_after_the_drain(self):
        """The reader gets the interrupt; siblings drain, then get a chained error."""
        interrupt, log = KeyboardInterrupt(), []
        tee = Tee(_Source([0, interrupt], log))
        first, second = tee.branch(), tee.branch()
        assert next(first) == 0

        with pytest.raises(KeyboardInterrupt) as raised:
            next(first)

        assert raised.value is interrupt
        assert log == ["pull", "pull", "close"]
        assert next(second) == 0

        with pytest.raises(PipelineError, match="interrupted") as chained:
            next(second)

        assert chained.value.__cause__ is interrupt

    def test_interrupted_copy_reraises_and_fails_siblings_after_the_drain(self):
        """The copier gets the interrupt; siblings drain, then get a chained error."""
        interrupt, log = KeyboardInterrupt(), []
        tee = Tee(_Source([0, _Uncopyable(interrupt), 2], log), isolate=True)
        first, second, third = tee.branch(), tee.branch(), tee.branch()
        assert next(first) == 0

        with pytest.raises(KeyboardInterrupt) as raised:
            next(first)

        assert raised.value is interrupt
        assert log == ["pull", "pull", "close"]

        for branch in (second, third):
            assert next(branch) == 0

            with pytest.raises(PipelineError, match="interrupted") as chained:
                next(branch)

            assert chained.value.__cause__ is interrupt

    def test_interrupted_copy_notes_a_failed_close_on_the_interrupt(
        self, riko_warnings
    ):
        """The interrupt carries the close failure; siblings reach it via the cause."""
        interrupt, failure = KeyboardInterrupt(), OSError("close failed")
        source = _Source([_Uncopyable(interrupt)], [], close_error=failure)
        tee = Tee(source, isolate=True)
        first, second, third = tee.branch(), tee.branch(), tee.branch()

        with pytest.raises(KeyboardInterrupt) as raised:
            next(first)

        assert raised.value is interrupt

        for branch in (second, third):
            with pytest.raises(PipelineError, match="interrupted") as chained:
                next(branch)

            assert chained.value.__cause__ is interrupt
            assert not hasattr(chained.value, "__notes__")

        assert interrupt.__notes__ == [f"closing the source also failed: {failure!r}"]
        assert [record.exc_info[1] for record in riko_warnings.records] == [failure]

    def test_second_interrupt_while_handling_the_first_releases_the_read(
        self, monkeypatch
    ):
        """A second interrupt during interrupt handling still frees waiting siblings."""

        def interrupt_again(*_):
            raise KeyboardInterrupt

        tee = Tee(_Source([0, KeyboardInterrupt()], []))
        first, _ = tee.branch(), tee.branch()
        assert next(first) == 0
        monkeypatch.setattr("riko.base._iterutils.PipelineError", interrupt_again)

        with pytest.raises(KeyboardInterrupt):
            next(first)

        assert tee._advancer is None

    @pytest.mark.parametrize(("max_lag", "error", "message"), _BAD_LAGS)
    def test_rejects_an_invalid_max_lag(self, max_lag, error, message):
        with pytest.raises(error, match=f"max_lag must be {message}"):
            Tee([], max_lag=max_lag)

    @pytest.mark.parametrize(("state", "act"), _LATE_BRANCHES)
    def test_branch_after_first_read_or_close_raises(self, state, act):
        """A late branch would miss items, so the tee refuses it."""
        tee = Tee(range(3))
        first, _ = tee.branch(), tee.branch()
        act(tee, first)

        with pytest.raises(PipelineStateError, match=state):
            tee.branch()

        tee.close()


class TestAsyncTee:
    @async_test
    async def test_branches_in_any_order_see_every_item_once_pulled(self):
        """Every branch sees each item in order however reads interleave."""
        source = AsyncPullLog(range(4))
        tee = AsyncTee(source)
        first, second, third = tee.branch(), tee.branch(), tee.branch()
        assert await alist(second) == [0, 1, 2, 3]
        pulled = [await anext(b) for b in (third, first, first, third)]
        assert pulled == [0, 0, 1, 1]
        assert (await alist(first), await alist(third)) == ([2, 3], [2, 3])
        assert len(source.pulled) == 4
        assert source.closes == 1

    @async_test
    async def test_isolate_copies_for_every_branch_but_the_puller(self):
        """The puller gets the original; siblings get a deep copy."""
        items = [{"n": [1]}]
        tee = AsyncTee(gen_items(items), isolate=True)
        first, second = tee.branch(), tee.branch()
        original, duplicate = await anext(first), await anext(second)
        duplicate["n"].append(2)
        assert original is items[0]
        assert duplicate is not original
        assert original == {"n": [1]}
        await tee.aclose()

    @async_test
    async def test_max_lag_overflow_discards_every_buffer_and_keeps_raising(self):
        """An overflow empties every queue, closes the source, and fails each read."""
        log: list[str] = []
        tee = AsyncTee(_ASource(list(range(5)), log), max_lag=2)
        first, second = tee.branch(), tee.branch()
        assert [await anext(first), await anext(first)] == [0, 1]

        with pytest.raises(
            PipelineError, match=r"2 items.*RIKO_BRANCH_BUFFER"
        ) as raised:
            await anext(first)

        assert not any(tee._buffers.values())
        assert log == ["pull", "pull", "close"]

        for branch in (second, first):
            with pytest.raises(PipelineError) as again:
                await anext(branch)

            assert again.value is raised.value

    @async_test
    async def test_closing_branches_frees_buffers_then_closes_source_once(self):
        """A closed branch drops its queue; the last close closes the source once."""
        source = AsyncPullLog(range(3))
        tee = AsyncTee(source)
        first, second, third = tee.branch(), tee.branch(), tee.branch()
        await anext(first)
        await second.aclose()
        assert len(tee._buffers) == 2
        assert await alist(first) == [1, 2]
        await third.aclose()
        await tee.aclose()
        assert len(source.pulled) == 3
        assert source.closes == 1

    @async_test
    async def test_upstream_error_reaches_every_branch(self):
        """The puller raises first; a sibling drains its queue, then re-raises."""
        error, log = ValueError("boom"), []
        tee = AsyncTee(_ASource([1, error], log))
        first, second = tee.branch(), tee.branch()
        assert await anext(first) == 1

        with pytest.raises(ValueError, match="boom") as pulled:
            await anext(first)

        assert log == ["pull", "pull", "close"]
        assert await anext(second) == 1

        for branch in (second, first):
            with pytest.raises(ValueError, match="boom") as again:
                await anext(branch)

            assert again.value is pulled.value is error

    @async_test
    async def test_copy_failure_on_the_second_branch_commits_nothing(self):
        """A failed copy queues the item for no branch and fails every branch."""
        log: list[str] = []
        failure = TypeError("uncopyable")
        source = _ASource([_Uncopyable(failure), 2], log)
        tee = AsyncTee(source, isolate=True)
        first, second, third = tee.branch(), tee.branch(), tee.branch()

        with pytest.raises(PipelineError, match="could not deepcopy") as raised:
            await anext(first)

        assert raised.value.__cause__ is failure
        assert not any(tee._buffers.values())
        assert log == _PULL_CLOSE

        for branch in (second, third):
            with pytest.raises(PipelineError) as again:
                await anext(branch)

            assert again.value is raised.value

    @async_test
    async def test_buffered_read_does_not_wait_for_a_blocked_upstream(self):
        """A branch with queued items reads them while another task is blocked."""
        log, results = [], []
        source = _ASource([0, 1], log)
        tee = AsyncTee(source)
        first, second = tee.branch(), tee.branch()
        assert await anext(first) == 0
        source.gate = gate = Event()

        async def read_first() -> None:
            results.append(await anext(first))

        with fail_after(1):
            async with create_task_group() as tg:
                tg.start_soon(read_first)
                await source.reached.wait()
                assert await anext(second) == 0
                gate.set()

        assert results == [1]
        await tee.aclose()

    @pytest.mark.parametrize("queued", _REENTRANT_READS)
    @async_test
    async def test_reentrant_advance_raises_and_reentrant_buffered_read_is_allowed(
        self, queued
    ):
        """Reading a branch from inside the source works only when it has a queue."""
        seen: list[int] = []

        async def gen_items():
            yield 0
            seen.append(await anext(second))
            yield 1

        tee = AsyncTee(gen_items())
        first, second = tee.branch(), tee.branch()

        if queued:
            assert [await anext(first), await anext(first)] == [0, 1]
            assert seen == [0]
        else:
            await anext(second)
            assert await anext(first) == 0

            with pytest.raises(PipelineStateError, match="advancing"):
                await anext(first)

        await tee.aclose()

    @pytest.mark.parametrize("close", _ADEFERRED_CLOSES)
    @async_test
    async def test_closing_the_last_branch_mid_read_defers_the_source_close(
        self, close
    ):
        """The close returns at once; the blocked reader closes the source after."""
        gate, log, results = Event(), [], []
        source = _ASource([0, 1], log, gate=gate)
        tee = AsyncTee(source)
        first, second = tee.branch(), tee.branch()

        async def read_first() -> None:
            results.append(await alist(first))

        with fail_after(1):
            async with create_task_group() as tg:
                tg.start_soon(read_first)
                await source.reached.wait()
                await close(tee, (second, first))
                assert log == ["pull"]
                gate.set()

        assert (results, log) == ([[]], _PULL_CLOSE)

    @async_test
    async def test_branches_closed_during_the_read_get_no_copy(self):
        """Branches closed while another task reads upstream get no copy of it."""
        gate, log, results = Event(), [], []
        item = _Uncopyable(TypeError("uncopyable"))
        source = _ASource([item, 1], log, gate=gate)
        tee = AsyncTee(source, isolate=True)
        first, second, third = tee.branch(), tee.branch(), tee.branch()

        async def read_first() -> None:
            results.append(await anext(first))

        with fail_after(1):
            async with create_task_group() as tg:
                tg.start_soon(read_first)
                await source.reached.wait()
                await second.aclose()
                await third.aclose()
                gate.set()

        assert (results, item.copies) == ([item], 0)
        await tee.aclose()

    @async_test
    async def test_a_failing_deferred_close_is_logged_not_raised(self, riko_warnings):
        """The blocked reader logs the source close failure and still ends normally."""
        gate, log, results = Event(), [], []
        failure = OSError("close failed")
        source = _ASource([0, 1], log, gate=gate, close_error=failure)
        tee = AsyncTee(source)
        first, _ = tee.branch(), tee.branch()

        async def read_first() -> None:
            results.append(await alist(first))

        with fail_after(1):
            async with create_task_group() as tg:
                tg.start_soon(read_first)
                await source.reached.wait()
                await tee.aclose()
                gate.set()

        assert (results, log) == ([[]], _PULL_CLOSE)
        assert [(r.getMessage(), r.exc_info[1]) for r in riko_warnings.records] == [
            ("closing the source failed", failure)
        ]

    @async_test
    async def test_cancelling_a_waiting_consumer_leaves_siblings_reading(self):
        """A consumer cancelled while waiting on a sibling's read leaves no trace."""
        gate, log, results = Event(), [], []
        source = _ASource([0, 1], log, gate=gate)
        tee = AsyncTee(source)
        first, second = tee.branch(), tee.branch()
        waiter = CancelScope()

        async def read_first() -> None:
            results.append(await anext(first))

        async def read_second() -> None:
            with waiter:
                results.append(await anext(second))

        with fail_after(1):
            async with create_task_group() as tg:
                tg.start_soon(read_first)
                await source.reached.wait()
                tg.start_soon(read_second)
                await _until_waiting(tee)
                waiter.cancel()
                gate.set()

            assert results == [0]
            assert (await alist(second), await alist(first)) == ([0, 1], [1])

    @async_test
    async def test_every_waiter_on_one_read_wakes_with_the_item(self):
        """Waiters share one event for the read, and every one gets the item."""
        gate, log, results = Event(), [], []
        source = _ASource([0], log, gate=gate)
        tee = AsyncTee(source)
        branches = [tee.branch() for _ in range(4)]

        async def read(branch: AsyncTeeBranch[object]) -> None:
            results.append(await anext(branch))

        with fail_after(1):
            async with create_task_group() as tg:
                tg.start_soon(read, branches[0])
                await source.reached.wait()

                for branch in branches[1:]:
                    tg.start_soon(read, branch)

                while (done := tee._read_done) is None or (
                    done.statistics().tasks_waiting < 3
                ):
                    await checkpoint()

                gate.set()

        assert (results, tee._read_done, tee._advancer) == ([0] * 4, None, None)
        await _aclose_each(branches)
        assert log == _PULL_CLOSE

    @async_test
    async def test_cancelling_a_waiter_leaves_the_owed_close_to_the_reader(self):
        """The reader still closes the source once after a waiting sibling cancels."""
        gate, log, results = Event(), [], []
        source = _ASource([0, 1], log, gate=gate)
        tee = AsyncTee(source)
        first, second = tee.branch(), tee.branch()
        waiter = CancelScope()

        async def read_first() -> None:
            results.append(await alist(first))

        async def read_second() -> None:
            with waiter:
                await anext(second)

        with fail_after(1):
            async with create_task_group() as tg:
                tg.start_soon(read_first)
                await source.reached.wait()
                tg.start_soon(read_second)
                await _until_waiting(tee)
                await _aclose_each((first, second))
                waiter.cancel()
                await checkpoint()
                assert log == ["pull"]
                gate.set()

        assert results == [[]]
        assert waiter.cancelled_caught
        assert log == _PULL_CLOSE

    @async_test
    async def test_cancelling_the_advancer_latches_for_survivors(self):
        """Survivors drain, then raise an error caused by the reader's cancellation."""
        log, caught, close_gate = [], [], Event()
        source = _ASource([0, 1], log, close_gate=close_gate)
        tee = AsyncTee(source)
        first, second = tee.branch(), tee.branch()
        assert await anext(first) == 0
        source.gate = Event()
        reader = CancelScope()

        async def read_first() -> None:
            with reader:
                try:
                    await anext(first)
                except BaseException as exc:
                    caught.append(exc)
                    raise

        with fail_after(1):
            async with create_task_group() as tg:
                tg.start_soon(read_first)
                await source.reached.wait()
                reader.cancel()
                await source.closing.wait()
                close_gate.set()

        assert log == ["pull", "pull", "close"]
        assert await anext(second) == 0

        with pytest.raises(PipelineError, match="interrupted") as chained:
            await anext(second)

        assert chained.value.__cause__ is caught[0]

    @async_test
    async def test_interrupted_copy_reraises_and_fails_siblings_after_the_drain(self):
        """The copier gets the interrupt; siblings drain, then get a chained error."""
        interrupt, log = KeyboardInterrupt(), []
        tee = AsyncTee(_ASource([0, _Uncopyable(interrupt), 2], log), isolate=True)
        first, second, third = tee.branch(), tee.branch(), tee.branch()
        assert await anext(first) == 0

        with pytest.raises(KeyboardInterrupt) as raised:
            await anext(first)

        assert raised.value is interrupt
        assert log == ["pull", "pull", "close"]

        for branch in (second, third):
            assert await anext(branch) == 0

            with pytest.raises(PipelineError, match="interrupted") as chained:
                await anext(branch)

            assert chained.value.__cause__ is interrupt

    @async_test
    async def test_interrupted_copy_notes_a_failed_close_on_the_interrupt(
        self, riko_warnings
    ):
        """The interrupt carries the close failure; siblings reach it via the cause."""
        interrupt, failure = KeyboardInterrupt(), OSError("close failed")
        source = _ASource([_Uncopyable(interrupt)], [], close_error=failure)
        tee = AsyncTee(source, isolate=True)
        first, second, third = tee.branch(), tee.branch(), tee.branch()

        with pytest.raises(KeyboardInterrupt) as raised:
            await anext(first)

        assert raised.value is interrupt

        for branch in (second, third):
            with pytest.raises(PipelineError, match="interrupted") as chained:
                await anext(branch)

            assert chained.value.__cause__ is interrupt
            assert not hasattr(chained.value, "__notes__")

        assert interrupt.__notes__ == [f"closing the source also failed: {failure!r}"]
        assert [record.exc_info[1] for record in riko_warnings.records] == [failure]

    @async_test
    async def test_second_interrupt_while_handling_the_first_releases_the_read(
        self, monkeypatch
    ):
        """A second interrupt during interrupt handling still frees waiting siblings."""

        def interrupt_again(*_):
            raise KeyboardInterrupt

        tee = AsyncTee(_ASource([0, KeyboardInterrupt()], []))
        first, _ = tee.branch(), tee.branch()
        assert await anext(first) == 0
        monkeypatch.setattr("riko.base._iterutils.PipelineError", interrupt_again)

        with pytest.raises(KeyboardInterrupt):
            await anext(first)

        assert tee._advancer is None

    @async_test
    async def test_cleanup_failure_at_eof_is_raised_after_the_drain(self):
        """A source that fails to close fails each branch once it has drained."""
        failure = OSError("close failed")
        tee = AsyncTee(_ASource([1], [], close_error=failure))
        first, second = tee.branch(), tee.branch()
        assert await anext(first) == 1

        with pytest.raises(OSError, match="close failed") as raised:
            await anext(first)

        assert raised.value is failure
        assert await anext(second) == 1

        for branch in (second, second, first):
            with pytest.raises(OSError, match="close failed"):
                await anext(branch)

    @async_test
    async def test_cleanup_failure_beside_a_read_error_keeps_the_primary(
        self, riko_warnings
    ):
        """The read error stays primary and notes and logs the close failure."""
        error, failure = ValueError("boom"), OSError("close failed")
        tee = AsyncTee(_ASource([error], [], close_error=failure))
        first = tee.branch()

        with pytest.raises(ValueError, match="boom") as raised:
            await anext(first)

        assert raised.value.__notes__ == [
            f"closing the stream also failed: {failure!r}"
        ]
        assert [record.exc_info[1] for record in riko_warnings.records] == [failure]

    @async_test
    async def test_cleanup_failure_beside_an_overflow_keeps_the_overflow(
        self, riko_warnings
    ):
        """The overflow stays primary and notes and logs the close failure."""
        failure = OSError("close failed")
        tee = AsyncTee(_ASource([0, 1], [], close_error=failure), max_lag=1)
        first, _ = tee.branch(), tee.branch()
        assert await anext(first) == 0

        with pytest.raises(PipelineError, match="1 items") as raised:
            await anext(first)

        assert raised.value.__notes__ == [
            f"closing the source also failed: {failure!r}"
        ]
        assert [record.exc_info[1] for record in riko_warnings.records] == [failure]

    @async_test
    async def test_interrupted_cleanup_beside_an_overflow_keeps_the_overflow(
        self, riko_warnings
    ):
        """The overflow stays primary and discards when its cleanup is interrupted."""
        interrupt = KeyboardInterrupt()
        tee = AsyncTee(_ASource([0, 1], [], close_error=interrupt), max_lag=1)
        first, second = tee.branch(), tee.branch()
        assert await anext(first) == 0

        with pytest.raises(KeyboardInterrupt) as raised:
            await anext(first)

        assert raised.value is interrupt
        assert not any(tee._buffers.values())

        with pytest.raises(PipelineError, match="1 items") as again:
            await anext(second)

        assert again.value.__notes__ == [
            f"closing the source also failed: {interrupt!r}"
        ]
        assert [record.exc_info[1] for record in riko_warnings.records] == [interrupt]

    @async_test
    async def test_infinite_stream_reads_incrementally(self):
        """Branches over an endless source pull only what is asked for."""
        source = AsyncPullLog(count())
        tee = AsyncTee(source)
        first, second = tee.branch(), tee.branch()
        assert [await anext(first), await anext(first), await anext(second)] == [
            0,
            1,
            0,
        ]
        assert len(source.pulled) == 2
        assert not source.closed
        await tee.aclose()

    @skipif_sync
    @pytest.mark.parametrize(("max_lag", "error", "message"), _BAD_LAGS)
    def test_rejects_an_invalid_max_lag(self, max_lag, error, message):
        with pytest.raises(error, match=f"max_lag must be {message}"):
            AsyncTee(_ASource([], []), max_lag=max_lag)

    @pytest.mark.parametrize(("state", "act"), _ALATE_BRANCHES)
    @async_test
    async def test_branch_after_first_read_or_close_raises(self, state, act):
        """A late branch would miss items, so the tee refuses it."""
        tee = AsyncTee(gen_items(range(3)))
        first, _ = tee.branch(), tee.branch()
        await act(tee, first)

        with pytest.raises(PipelineStateError, match=state):
            tee.branch()

        await tee.aclose()
