# vim: sw=4:ts=4:expandtab
"""Provides internal tests for executions and their result envelopes."""

from __future__ import annotations

import gc
from contextlib import aclosing, asynccontextmanager, contextmanager, nullcontext
from functools import partial
from itertools import count
from math import inf
from threading import Event as ThreadEvent
from time import perf_counter
from typing import TYPE_CHECKING

import pytest

from riko.bado._backend import (
    Event,
    async_sleep,
    create_task_group,
    fail_after,
    lowlevel,
)
from riko.bado.itertools import as_async
from riko.base._exceptions import PipelineStateError
from riko.base._sentinels import MISSING
from riko.coercion._canonical import IdentityAccumulator, IdentityDomain
from riko.definitions._nodes import CallableNode, ModuleNode, StreamEdge
from riko.definitions._settings import ExecutionSettings
from riko.definitions._workflow_definition import Workflow
from riko.execution._async_execution import AsyncExecution
from riko.execution._async_execution import _RunStream as _AsyncRunStream
from riko.execution._execution import _NullEventSink, _ThreadBudget
from riko.execution._prepared import ExecutionPlan
from riko.execution._provenance import (
    PLACEHOLDER,
    NodeProvenance,
    _TableProvenance,
    agen_result_envelopes,
    arun_tracked_item,
    gen_result_envelopes,
    run_tracked_item,
)
from riko.execution._sync_execution import SyncExecution, _RunStream
from riko.parsing._dotdict import DotDict
from riko.runtime._pipeline import Pipeline
from riko.runtime._resolver import dispatcher
from riko.types._enums import IdentityMode
from riko.types._feed import Metadata, _ItemEnvelope, build_generation
from riko.types._workflow import Endpoint, NodeId
from riko.types.modules import (
    FilterConf,
    FilterConfRule,
    ItemBuilderConf,
    SortConf,
    SortConfRule,
    TruncateConf,
)
from tests import ROUND_TRIPS, async_test, get_envelope_values, skipif_sync
from tests._execution import RecordingSink
from tests._streams import AsyncPullLog, PullLog

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Iterator, Sequence

    from riko.types._feed import Identity
    from riko.types._streams import Item, ItemOrValue

type _Result = tuple[Item, Identity]


_FEED_SEED: list[Item] = [
    {"i": index, "content": content}
    for index, content in enumerate(("a b", "c", "a", "d e"))
]

_SCALAR_SEED: list[ItemOrValue] = ["a b", "c", "a"]
_CONTAINS_A = FilterConfRule(field="content", op="contains", value="a")
_HASH = Pipeline.from_module("hash")
_FILTER = Pipeline.from_module("filter", conf=FilterConf({"rule": _CONTAINS_A}))
_TRUNCATE_2 = Pipeline.from_module("truncate", conf=TruncateConf(count=2))

_TOKENS = Pipeline.from_module(
    "tokenizer", conf={"delimiter": " "}, options={"emit": True}
)


async def _double(value: int) -> int:
    return value * 2


def _double_on_loop(value: int) -> int:
    lowlevel.current_token()
    return value * 2


def _double_later(value: int) -> Awaitable[int]:
    return _double(value)


def _scale(value: int, *, factor: int) -> int:
    lowlevel.current_token()
    return value * factor


def _double_if_bounded(value: int, *, bounded: bool) -> int:
    return value * 2 if bounded else value


# Portal work: an async callable, a sync callable, a sync callable returning an
# awaitable, a bare awaitable, and sync callables given keywords, one named like the
# bare awaitable's option.
PORTAL_WORK = [
    pytest.param(lambda ex: ex.run_async(_double, 21), id="async"),
    pytest.param(lambda ex: ex.run_async(_double_on_loop, 21), id="sync"),
    pytest.param(lambda ex: ex.run_async(_double_later, 21), id="returns-awaitable"),
    pytest.param(lambda ex: ex.run_async(_double(21)), id="awaitable"),
    pytest.param(lambda ex: ex.run_async(_scale, 21, factor=2), id="keyword"),
    pytest.param(
        lambda ex: ex.run_async(_double_if_bounded, 21, bounded=True),
        id="callee-bounded-keyword",
    ),
]


class TestSyncExecution:
    def test_sync_exit_stack_unwinds_on_error(self) -> None:
        events: list[str] = []

        @contextmanager
        def track(name: str):
            events.append(f"open {name}")
            try:
                yield name
            finally:
                events.append(f"close {name}")

        def fail() -> None:
            with SyncExecution() as execution:
                execution.enter_context(track("a"))
                raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            fail()

        assert events == ["open a", "close a"]

    def test_sync_resource_sees_primary_error(self) -> None:
        seen: list[str] = []

        @contextmanager
        def watcher():
            try:
                yield
            except RuntimeError:
                seen.append("saw RuntimeError")
                raise

        def run() -> None:
            with SyncExecution() as execution:
                execution.enter_context(watcher())
                raise RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            run()

        assert seen == ["saw RuntimeError"]

    def test_sync_resource_can_suppress_primary_error(self) -> None:
        reached: list[str] = []

        @contextmanager
        def swallow():
            try:
                yield
            except RuntimeError:
                pass

        with SyncExecution() as execution:
            execution.enter_context(swallow())
            raise RuntimeError("boom")

        reached.append("after")
        assert reached == ["after"]

    def test_sync_repeated_close_does_not_reraise_cleanup_error(self) -> None:
        calls: list[str] = []

        def boom() -> None:
            calls.append("cleanup")
            raise RuntimeError("cleanup failed")

        execution = SyncExecution()
        execution.queue_callback(boom)

        with pytest.raises(RuntimeError, match="cleanup failed"):
            execution.close()

        assert execution.close() is False
        assert calls == ["cleanup"]

    @skipif_sync
    @pytest.mark.parametrize("build", PORTAL_WORK)
    def test_sync_portal_runs_work_on_its_loop(self, build) -> None:
        result = None

        with SyncExecution() as execution:
            result = build(execution)

        assert result == 42

    @skipif_sync
    def test_sync_bounded_portal_work_runs_while_closing(self) -> None:
        results: list[int] = []

        with SyncExecution() as execution:
            execution.run_async(_double, 0)

            def cleanup() -> None:
                with pytest.raises(PipelineStateError, match="closing"):
                    execution.run_async(_double, 1)

                results.append(execution.run_async(_double(21), bounded=True))

            execution.queue_callback(cleanup)

        assert results == [42]

    def test_sync_default_event_sink_is_noop(self) -> None:
        with SyncExecution() as execution:
            execution.emit("ignored")
            assert isinstance(execution.events, _NullEventSink)

    def test_sync_execution_dispatches_to_event_sink(self) -> None:
        sink = RecordingSink()

        with SyncExecution(events=sink) as execution:
            execution.emit("a")
            execution.emit("b")

        assert sink.events == ["a", "b"]

    def test_each_execution_owns_its_event_sink(self) -> None:
        first = RecordingSink()
        second = RecordingSink()

        with (
            SyncExecution(events=first) as outer,
            SyncExecution(events=second) as inner,
        ):
            outer.emit("one")
            inner.emit("two")
            outer.emit("three")

        assert (first.events, second.events) == (["one", "three"], ["two"])

    def test_settings_supply_the_event_sink(self) -> None:
        sink, explicit = RecordingSink(), RecordingSink()
        settings = ExecutionSettings(event_sink=sink)
        assert SyncExecution(settings=settings).events is sink
        assert SyncExecution(events=explicit, settings=settings).events is explicit

    def test_a_run_whose_last_step_is_not_a_stream_cannot_be_read(self) -> None:
        run: _RunStream[_ItemEnvelope[object]] = _RunStream(None)
        run.output = object()

        with pytest.raises(TypeError, match="must be an iterator"):
            next(run)

    def test_a_port_whose_stream_has_no_close_is_rejected(self) -> None:
        run: _RunStream[_ItemEnvelope[object]] = _RunStream(None)

        with SyncExecution() as execution, pytest.raises(TypeError, match="closable"):
            execution._register_port({}, run, ("n", "_OUTPUT"), iter([]), 1)

    @skipif_sync
    @pytest.mark.filterwarnings("error::pytest.PytestUnraisableExceptionWarning")
    def test_sync_portal_work_refused_on_its_loop_leaves_no_coroutine(self) -> None:
        with SyncExecution() as execution:

            async def call_from_loop() -> None:
                execution.run_async(_double, 21)

            with pytest.raises(RuntimeError, match="event loop thread"):
                execution.run_async(call_from_loop)

        gc.collect()

    @skipif_sync
    def test_sync_bounded_portal_work_expires_at_the_shutdown_timeout(self) -> None:
        settings = ExecutionSettings(shutdown_timeout=0.05)

        with SyncExecution(settings=settings) as execution, pytest.raises(TimeoutError):
            execution.run_async(async_sleep(10), bounded=True)

    def test_sync_enter_after_close_raises(self) -> None:
        execution = SyncExecution()
        execution.close()

        with pytest.raises(
            PipelineStateError, match="the execution in state 'closing'"
        ):
            execution.enter_context(nullcontext(1))

    def test_sync_cleanup_error_is_noted_on_primary_error(self) -> None:
        # A plain cleanup callback cannot replace the execution's own error: the
        # primary is raised with the cleanup failure noted on it.
        def boom() -> None:
            raise RuntimeError("cleanup failed")

        def run() -> None:
            with SyncExecution() as execution:
                execution.queue_callback(boom)
                raise ValueError("primary")

        with pytest.raises(ValueError, match="primary") as info:
            run()

        assert "RuntimeError('cleanup failed')" in info.value.__notes__[0]

    def test_sync_native_context_manager_may_replace_primary_error(self) -> None:
        # A real __exit__ keeps its Python semantics: it may raise a different
        # exception in place of the primary one, and that replacement is raised bare.
        @contextmanager
        def replace():
            try:
                yield
            except ValueError as error:
                raise KeyError("replaced") from error

        def run() -> None:
            with SyncExecution() as execution:
                execution.enter_context(replace())
                raise ValueError("primary")

        with pytest.raises(KeyError, match="replaced") as info:
            run()

        assert isinstance(info.value.__cause__, ValueError)


class _UnclosableEnvelopes:
    def __aiter__(self) -> _UnclosableEnvelopes:
        return self

    async def __anext__(self) -> _ItemEnvelope[object]:
        raise StopAsyncIteration


class TestAsyncExecution:
    @async_test
    async def test_async_exit_stack_unwinds_lifo(self) -> None:
        events: list[str] = []

        @asynccontextmanager
        async def track(name: str):
            events.append(f"open {name}")
            try:
                yield name
            finally:
                events.append(f"close {name}")

        async with AsyncExecution() as execution:
            await execution.enter_async_context(track("a"))
            await execution.enter_async_context(track("b"))

        assert events == ["open a", "open b", "close b", "close a"]

    @async_test
    async def test_async_repeated_close_does_not_reraise_cleanup_error(self) -> None:
        calls: list[str] = []

        async def boom() -> None:
            calls.append("cleanup")
            raise RuntimeError("cleanup failed")

        execution = AsyncExecution()
        execution.queue_async_callback(boom)

        with pytest.raises(RuntimeError, match="cleanup failed"):
            await execution.aclose()

        await execution.aclose()
        assert calls == ["cleanup"]

    @async_test
    async def test_async_ambient_cancellation_still_unwinds(self) -> None:
        events: list[str] = []
        ready = Event()

        @contextmanager
        def resource():
            try:
                yield
            finally:
                events.append("resource-closed")

        async def body() -> None:
            async with AsyncExecution() as execution:
                execution.enter_context(resource())
                ready.set()
                await async_sleep(3600)

        with fail_after(1):
            async with create_task_group() as tg:
                tg.start_soon(body)
                await ready.wait()
                tg.cancel_scope.cancel()

        assert events == ["resource-closed"]

    @async_test
    async def test_async_sync_callback_runs_on_close(self) -> None:
        calls: list[str] = []

        async with AsyncExecution() as execution:
            execution.queue_callback(calls.append, "closed")

        assert calls == ["closed"]

    @async_test
    async def test_async_infinite_shutdown_timeout_waits_out_cleanup(self) -> None:
        done: list[bool] = []

        async def slow() -> None:
            await async_sleep(0.1)
            done.append(True)

        settings = ExecutionSettings(shutdown_timeout=inf)

        with fail_after(1):
            async with AsyncExecution(settings=settings) as execution:
                execution.queue_async_callback(slow)

        assert done == [True]

    @pytest.mark.timeout(2)
    @async_test
    async def test_async_shutdown_timeout_abandons_a_blocking_sync_cleanup(
        self, riko_warnings
    ) -> None:
        release = ThreadEvent()

        def fail_late(_value: object) -> None:
            release.wait(1)
            raise ValueError("late")

        settings = ExecutionSettings(shutdown_timeout=0.05)
        start = perf_counter()

        with pytest.raises(TimeoutError):
            async with AsyncExecution(settings=settings) as execution:
                execution.async_queue_close(object(), fail_late, inline=False)

        assert perf_counter() - start < 1
        release.set()

        with fail_after(1):
            while not riko_warnings.records:
                await async_sleep(0.01)

        assert "abandoned" in riko_warnings.records[0].getMessage()

    @async_test
    async def test_async_run_sync_bridges_to_worker(self) -> None:
        result = None

        async with AsyncExecution() as execution:
            result = await execution.run_sync(pow, 2, 10)

        assert result == 1024

    @async_test
    async def test_async_default_event_sink_is_noop(self) -> None:
        async with AsyncExecution() as execution:
            execution.emit("ignored")
            assert isinstance(execution.events, _NullEventSink)

    @async_test
    async def test_async_execution_dispatches_to_event_sink(self) -> None:
        sink = RecordingSink()

        async with AsyncExecution(events=sink) as execution:
            execution.emit("a")
            execution.emit("b")

        assert sink.events == ["a", "b"]

    @async_test
    async def test_a_run_whose_last_step_is_not_a_stream_cannot_be_read(self) -> None:
        reservation = await _ThreadBudget(1).reserve(1)
        run: _AsyncRunStream[object] = _AsyncRunStream(None, reservation)
        run.output = object()

        with pytest.raises(TypeError, match="must be an async iterator"):
            await anext(run)

        assert not reservation.held

    @async_test
    async def test_a_port_whose_stream_has_no_close_is_rejected(self) -> None:
        reservation = await _ThreadBudget(1).reserve(1)
        run: _AsyncRunStream[_ItemEnvelope[object]] = _AsyncRunStream(None, reservation)
        stream = _UnclosableEnvelopes()

        async with AsyncExecution() as execution:
            with pytest.raises(TypeError, match="closable"):
                execution._register_port({}, run, ("n", "_OUTPUT"), stream, 1)

        reservation.release()

    @async_test
    async def test_async_cleanup_error_is_noted_on_primary_error(self) -> None:
        async def boom() -> None:
            raise RuntimeError("cleanup failed")

        async def run() -> None:
            async with AsyncExecution() as execution:
                execution.queue_async_callback(boom)
                raise ValueError("primary")

        with pytest.raises(ValueError, match="primary") as info:
            await run()

        assert "RuntimeError('cleanup failed')" in info.value.__notes__[0]

    @async_test
    async def test_async_native_context_manager_may_replace_primary_error(self) -> None:
        @asynccontextmanager
        async def replace():
            try:
                yield
            except ValueError as error:
                raise KeyError("replaced") from error

        async def run() -> None:
            async with AsyncExecution() as execution:
                await execution.enter_async_context(replace())
                raise ValueError("primary")

        with pytest.raises(KeyError, match="replaced") as info:
            await run()

        assert isinstance(info.value.__cause__, ValueError)

    @async_test
    async def test_async_shutdown_timeout_expiry_is_noted_on_primary_error(
        self,
    ) -> None:
        # Exhausting the shutdown timeout during cleanup is a cleanup failure
        # noted on the execution's own error, not a replacement for it.
        async def slow() -> None:
            await async_sleep(1)

        async def run() -> None:
            settings = ExecutionSettings(shutdown_timeout=0.05)

            async with AsyncExecution(settings=settings) as execution:
                execution.queue_async_callback(slow)
                raise ValueError("primary")

        with pytest.raises(ValueError, match="primary") as info:
            await run()

        assert "TimeoutError" in info.value.__notes__[0]


def _chars(value: str) -> Iterator[str]:
    return iter(value)


def _achars(value: str) -> AsyncIterator[str]:
    return as_async(value)


def _root(index: int = 0, value: object = "a") -> _ItemEnvelope[object]:
    return _ItemEnvelope.from_parent(PLACEHOLDER, "source", value, index)


RESULT_ENVELOPE_RULES = [
    pytest.param(IdentityMode.PRESERVE, "xy", True, id="preserve-many"),
    pytest.param(IdentityMode.DERIVE, "x", False, id="derive-one"),
    pytest.param(IdentityMode.DERIVE, "xy", False, id="derive-many"),
    pytest.param(IdentityMode.COMBINE, "x", False, id="combine-one"),
    pytest.param(None, "x", False, id="undeclared-one"),
    pytest.param(None, "xy", False, id="undeclared-many"),
]


class TestResultEnvelopes:
    @pytest.mark.parametrize("values", ["a", "ab"])
    @pytest.mark.parametrize("identity", [*IdentityMode, None])
    def test_placeholder_results_are_roots(self, identity, values):
        envelopes = list(gen_result_envelopes("fetch", values, PLACEHOLDER, identity))
        expected = [("fetch", i) for i in range(len(values))]
        assert [env.generation for env in envelopes] == expected
        assert all(env.item_key is MISSING for env in envelopes)

    @pytest.mark.parametrize(("identity", "values", "preserves"), RESULT_ENVELOPE_RULES)
    def test_identity_rule_per_input_item(self, identity, values, preserves):
        parent = _root()
        envelopes = list(gen_result_envelopes("n", values, parent, identity))

        if preserves:
            expected = [parent.generation] * len(values)
        else:
            expected = [
                build_generation("n", parent.generation, i) for i in range(len(values))
            ]

        assert get_envelope_values(envelopes) == list(values)
        assert [env.generation for env in envelopes] == expected

    @pytest.mark.parametrize("identity", [*IdentityMode, None])
    def test_first_result_is_yielded_before_the_second_is_read(self, identity):
        values = PullLog(count())
        envelopes = gen_result_envelopes("n", values, _root(), identity)
        assert next(envelopes).value == 0
        assert values.pulled == (0,)

    @pytest.mark.parametrize("identity", [*IdentityMode, None])
    @async_test
    async def test_async_first_result_is_yielded_before_the_second_is_read(
        self, identity
    ):
        values = AsyncPullLog(count())
        results = agen_result_envelopes("n", values, _root(), identity)

        async with aclosing(results) as envelopes:
            assert (await anext(envelopes)).value == 0

        assert values.pulled == (0,)

    def test_preserve_keeps_the_input_identity(self):
        parent = _ItemEnvelope("a", "key", ("n", 0), Metadata({"seen": True}))
        [envelope] = gen_result_envelopes("upper", ["A"], parent, IdentityMode.PRESERVE)
        assert envelope == _ItemEnvelope("A", "key", ("n", 0), parent.observation)

    @pytest.mark.parametrize("identity", [IdentityMode.DERIVE, None])
    def test_derive_indexes_results_within_each_parent(self, identity):
        first, second = _root(0), _root(1)
        derived = [
            [
                env.generation
                for env in gen_result_envelopes("split", "xy", parent, identity)
            ]
            for parent in (first, second)
        ]
        assert derived == [
            [build_generation("split", parent.generation, i) for i in range(2)]
            for parent in (first, second)
        ]
        assert len({*derived[0], *derived[1]}) == 4

    def test_derived_results_keep_the_parent_observation(self):
        parent = _ItemEnvelope(
            "a", generation=("n", 0), observation=Metadata({"seen": True})
        )
        [envelope] = gen_result_envelopes("split", ["x"], parent, IdentityMode.DERIVE)
        assert envelope.item_key is MISSING
        assert envelope.observation is parent.observation

    @pytest.mark.parametrize("placeholder", [False, True])
    @pytest.mark.parametrize(("identity", "values", "preserves"), RESULT_ENVELOPE_RULES)
    @async_test
    async def test_async_results_match_sync_results(
        self, identity, values, preserves, placeholder
    ):
        parent = PLACEHOLDER if placeholder else _root()
        expected = list(gen_result_envelopes("n", values, parent, identity))
        envelopes = agen_result_envelopes("n", as_async(values), parent, identity)
        assert [env async for env in envelopes] == expected

    @pytest.mark.parametrize("round_trip", ROUND_TRIPS)
    def test_tracked_item_call_round_trips(self, round_trip):
        call = partial(run_tracked_item, _chars, "split", None)
        envelopes = round_trip(call)(_root(value="ab"))
        assert envelopes == list(gen_result_envelopes("split", "ab", _root(value="ab")))

    @async_test
    async def test_async_tracked_item_call_matches_sync(self):
        parent = _ItemEnvelope.from_parent(PLACEHOLDER, "fetch", "ab")
        expected = run_tracked_item(_chars, "split", None, parent)
        envelopes = await arun_tracked_item(_achars, "split", None, parent)
        assert envelopes == expected


def _dotdicts(count: int) -> list[_ItemEnvelope[object]]:
    return [_root(i, DotDict({"i": i})) for i in range(count)]


class TestNodeProvenance:
    def test_passed_through_values_keep_their_envelopes(self):
        envelopes = _dotdicts(3)
        provenance = NodeProvenance.from_identity("reverse", IdentityMode.PRESERVE)
        values = list(provenance.gen_values(envelopes))
        results = list(provenance.gen_envelopes(reversed(values)))
        assert results == envelopes[::-1]
        assert all(
            r.value is e.value for r, e in zip(results, envelopes[::-1], strict=True)
        )

    def test_a_value_read_twice_gets_its_envelopes_back_in_order(self):
        value = DotDict({"i": 0})
        envelopes = [_root(i, value) for i in range(2)]
        provenance = NodeProvenance.from_identity("filter", IdentityMode.PRESERVE)
        values = list(provenance.gen_values(envelopes))
        results = list(provenance.gen_envelopes(iter(values)))
        assert [env.generation for env in results] == [
            env.generation for env in envelopes
        ]

    def test_new_values_derive_from_the_last_input(self):
        envelopes = _dotdicts(2)
        provenance = NodeProvenance.from_identity("join", IdentityMode.PRESERVE)
        values = list(provenance.gen_values(envelopes))
        copies = [DotDict(v) for v in values if isinstance(v, DotDict)]
        results = list(provenance.gen_envelopes(iter(copies)))
        last = envelopes[-1].generation
        assert [env.generation for env in results] == [
            ("join", last, 0),
            ("join", last, 1),
        ]

    def test_new_values_before_any_input_are_roots(self):
        provenance = NodeProvenance.from_identity("join", None)
        [result] = provenance.gen_envelopes(iter([DotDict()]))
        assert result.generation == ("join", 0)

    def test_unreferenceable_values_derive_from_their_input(self):
        envelopes = [_root(i, f"v{i}") for i in range(2)]
        provenance = NodeProvenance.from_identity("upper", IdentityMode.PRESERVE)
        results = list(provenance.gen_envelopes(provenance.gen_values(envelopes)))
        assert get_envelope_values(results) == ["v0", "v1"]
        assert [env.generation for env in results] == [
            ("upper", env.generation, k) for k, env in enumerate(envelopes)
        ]

    def test_dropped_values_free_their_entries(self):
        provenance = _TableProvenance("filter")
        values = provenance.gen_values(_dotdicts(100))
        kept = [v for v in values if isinstance(v, DotDict) and v["i"] % 10 == 0]
        gc.collect()
        assert len(provenance._table) == len(kept) == 10

    def test_closing_the_output_frees_every_entry(self):
        provenance = _TableProvenance("filter")
        envelopes = _dotdicts(3)
        values = list(provenance.gen_values(envelopes))
        results = provenance.gen_envelopes(iter(values))
        next(results)
        results.close()
        assert not provenance._table

    def test_combine_ignores_passed_through_values(self):
        envelopes = _dotdicts(2)
        provenance = NodeProvenance.from_identity("count", IdentityMode.COMBINE)
        values = list(provenance.gen_values(envelopes))
        results = list(provenance.gen_envelopes(iter(values)))
        assert {env.generation for env in results}.isdisjoint(
            env.generation for env in envelopes
        )

    def test_combine_identity_folds_every_contributor(self):
        def combine(envelopes):
            provenance = NodeProvenance.from_identity("count", IdentityMode.COMBINE)
            values = list(provenance.gen_values(envelopes))
            return next(provenance.gen_envelopes(iter([len(values)]))).generation

        contributors = IdentityAccumulator(IdentityDomain.GENERATION)
        pair = (_root(0), _root(1))

        for env in pair:
            contributors.add(env.generation)

        assert combine(pair) == ("count", contributors.digest(), 0)
        assert combine(pair) != combine([_root(0), _root(2)])

    def test_closing_the_output_closes_the_wrapped_stream(self):
        closed: list[bool] = []

        def gen_values():
            try:
                yield from (DotDict({"i": i}) for i in range(3))
            finally:
                closed.append(True)

        results = NodeProvenance.from_identity(
            "filter", IdentityMode.PRESERVE
        ).gen_envelopes(gen_values())
        next(results)
        results.close()
        assert closed == [True]

    @async_test
    async def test_closing_the_async_output_closes_the_wrapped_stream(self):
        closed: list[bool] = []

        async def agen_values():
            try:
                for i in range(3):
                    yield DotDict({"i": i})
            finally:
                closed.append(True)

        provenance = NodeProvenance.from_identity("filter", IdentityMode.PRESERVE)
        results = provenance.agen_envelopes(agen_values())
        await anext(results)
        await results.aclose()
        assert closed == [True]

    @async_test
    async def test_async_twins_match_the_sync_rule(self):
        envelopes = _dotdicts(3)
        provenance = NodeProvenance.from_identity("reverse", IdentityMode.PRESERVE)
        values = [value async for value in provenance.agen_values(envelopes)]
        reversed_values = as_async(values[::-1])
        results = [env async for env in provenance.agen_envelopes(reversed_values)]
        assert results == envelopes[::-1]


def _get_seed_index(value: Item) -> int:
    """Gets the position of the seed item ``value`` came from."""
    index = dict(value).get("i")

    if not isinstance(index, int):
        raise TypeError(f"{value!r} has no seed index")

    return index


def _feed(pipeline: Pipeline, seed: Sequence[ItemOrValue]) -> list[_Result]:
    """Runs ``pipeline`` the way a pipeline run does and keeps each identity."""
    plan = ExecutionPlan.from_workflow(pipeline.workflow, dispatcher)
    results: list[_Result] = []

    with SyncExecution(settings=pipeline.settings) as execution:
        stream = execution.build_envelope_stream(plan, seed=seed)
        results = [(env.value, env.generation) for env in stream]

    return results


async def _afeed(pipeline: Pipeline, seed: Sequence[ItemOrValue]) -> list[_Result]:
    """The async twin of ``_feed``."""
    plan = ExecutionPlan.from_workflow(pipeline.workflow, dispatcher)
    results: list[_Result] = []

    async with AsyncExecution(settings=pipeline.settings) as execution:
        stream = await execution.abuild_envelope_stream(plan, seed=seed)
        results = [(env.value, env.generation) async for env in stream]

    return results


def _copy_item(item: Item, part: object) -> Item:
    return item.copy()


def _build_fan_in_copy() -> Workflow:
    """Builds a preserving callable node fed a second stream (a whole-stream run)."""
    a = ModuleNode(
        id="a",
        name="itembuilder",
        conf=ItemBuilderConf({"attrs": [{"key": "x", "value": "1"}]}),
    )
    b = ModuleNode(
        id="b",
        name="itembuilder",
        conf=ItemBuilderConf({"attrs": [{"key": "y", "value": "2"}]}),
    )
    c = CallableNode(id="c", name="copy_item", fn=_copy_item, identity="preserve")
    edges = (
        StreamEdge(Endpoint("a", "out"), Endpoint("c", "in")),
        StreamEdge(Endpoint("b", "out"), Endpoint("c", "in:part")),
    )
    outputs = {"default": Endpoint("c", "out")}
    return Workflow(nodes=[a, b, c], edges=edges, outputs=outputs)


def _seed_target(pipeline: Pipeline) -> NodeId:
    plan = ExecutionPlan.from_workflow(pipeline.workflow, dispatcher)
    return plan.require_seed_target("default")


def _roots(pipeline: Pipeline, results: list[_Result]) -> list[bool]:
    """Whether each result keeps the identity of the seed item it came from."""
    target = _seed_target(pipeline)
    return [
        generation == build_generation(target, MISSING, _get_seed_index(value))
        for value, generation in results
    ]


def _multiset(results: list[_Result]) -> list[tuple[str, str]]:
    return sorted((repr(sorted(value.items())), repr(gen)) for value, gen in results)


# Pipelines that pass each seed item on, so every result keeps its seed identity.
PRESERVING_PIPELINES = [
    pytest.param(_HASH, 4, id="processor"),
    pytest.param(_HASH | _HASH, 4, id="processor-chain"),
    pytest.param(_FILTER, 2, id="seeded-filter"),
    pytest.param(_HASH | _FILTER, 2, id="filter"),
    pytest.param(_TRUNCATE_2, 2, id="truncate"),
    pytest.param(
        Pipeline.from_module(
            "sort", conf=SortConf({"rule": SortConfRule(field="i", dir="desc")})
        ),
        4,
        id="sort",
    ),
    pytest.param(Pipeline.from_module("union"), 4, id="union"),
    pytest.param(_HASH.map(lambda item: {**item, "m": 1}), 4, id="map"),
    pytest.param(Pipeline().map(lambda item: item) | _FILTER, 2, id="seeded-map"),
    pytest.param(Pipeline().map(dict) | _FILTER, 2, id="fresh-dict-map"),
]
# Pipelines over scalar seed items, with the seed positions of the items they keep.
SCALAR_PIPELINES = [
    pytest.param(_FILTER, [0, 2], id="filter"),
    pytest.param(_TRUNCATE_2, [0, 1], id="truncate"),
]
# Pipelines whose results run on a worker pool or the async execution.
PARALLEL_PIPELINES = [
    pytest.param(_HASH.with_execution(concurrency=2, ordered=False), id="threads"),
    pytest.param(
        _HASH.with_execution(executor="process"),
        id="processes",
        marks=pytest.mark.timeout(5),
    ),
    pytest.param(_TOKENS.with_execution(concurrency=2), id="derived-threads"),
]
# Pipelines whose async run yields the same identities as their sync run.
ASYNC_PARITY_PIPELINES = [
    pytest.param(_TOKENS, id="derived"),
    pytest.param(_HASH.with_execution(concurrency=2, ordered=False), id="threads"),
    pytest.param(_TOKENS.with_execution(concurrency=2), id="derived-threads"),
    pytest.param(
        _HASH.map(lambda item: {**item, "m": 1}, identity="derive"), id="declared-map"
    ),
]


class TestBuildEnvelopeStream:
    """Test the identity each result of an envelope run keeps."""

    @pytest.mark.parametrize(("pipeline", "length"), PRESERVING_PIPELINES)
    def test_keeps_each_seed_item_s_identity(self, pipeline, length) -> None:
        results = _feed(pipeline, _FEED_SEED)
        assert len(results) == length
        assert all(_roots(pipeline, results))

    @pytest.mark.parametrize(("pipeline", "indexes"), SCALAR_PIPELINES)
    def test_keeps_each_scalar_seed_item_s_identity(self, pipeline, indexes) -> None:
        target = _seed_target(pipeline)
        generations = [gen for _, gen in _feed(pipeline, _SCALAR_SEED)]
        assert generations == [build_generation(target, MISSING, i) for i in indexes]

    def test_keeps_each_identity_of_a_repeated_item(self) -> None:
        target = _seed_target(_TRUNCATE_2)
        item = DotDict({"content": "a"})
        generations = [gen for _, gen in _feed(_TRUNCATE_2, [item, item])]
        assert generations == [build_generation(target, MISSING, i) for i in (0, 1)]

    def test_derives_tokens_from_their_own_item(self) -> None:
        target = _seed_target(_TOKENS)
        results = _feed(_TOKENS, _FEED_SEED)
        extended = _feed(_TOKENS, [*_FEED_SEED, {"i": 4, "content": "f g"}])
        parents = [build_generation(target, MISSING, i) for i in (0, 0, 1, 2, 3, 3)]
        indexes = [0, 1, 0, 0, 0, 1]
        expected = list(map(partial(build_generation, target), parents, indexes))
        assert [generation for _, generation in results] == expected
        assert extended[: len(results)] == results

    def test_combines_a_count_into_one_new_item(self) -> None:
        count_pipeline = Pipeline.from_module("count")
        [(value, generation)] = _feed(count_pipeline, _FEED_SEED)
        assert value == {"count": 4}
        assert _feed(count_pipeline, _FEED_SEED) == [(value, generation)]
        assert not any(_roots(count_pipeline, [({"i": 0}, generation)]))

    def test_derives_a_declared_map_result(self) -> None:
        pipeline = _HASH.map(lambda item: {**item, "m": 1}, identity="derive")
        target = _seed_target(pipeline)
        node_id = pipeline.workflow.outputs["default"].node
        results = _feed(pipeline, _FEED_SEED)
        expected = [
            build_generation(node_id, build_generation(target, MISSING, i), 0)
            for i in range(4)
        ]
        assert [generation for _, generation in results] == expected

    @pytest.mark.parametrize("pipeline", PARALLEL_PIPELINES)
    def test_on_workers_matches_a_sequential_run(self, pipeline) -> None:
        sequential = pipeline.with_execution(concurrency=None, executor=None)
        expected = _multiset(_feed(sequential, _FEED_SEED))
        assert _multiset(_feed(pipeline, _FEED_SEED)) == expected

    @pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason="a declared identity mode on a node fed a secondary input stream is "
        "not yet implemented",
    )
    def test_keeps_a_fan_in_node_s_declared_identity(self) -> None:
        plan = ExecutionPlan.from_workflow(_build_fan_in_copy(), dispatcher)
        results: list[_Result] = []

        with SyncExecution() as execution:
            stream = execution.build_envelope_stream(plan)
            results = [(env.value, env.generation) for env in stream]

        [(value, generation)] = results
        assert value == {"x": "1"}
        assert generation == build_generation("a", MISSING, 0)


class TestAsyncBuildEnvelopeStream:
    """Test the identity each result of an async envelope run keeps."""

    @pytest.mark.parametrize(("pipeline", "length"), PRESERVING_PIPELINES)
    @async_test
    async def test_keeps_each_seed_item_s_identity(self, pipeline, length) -> None:
        results = await _afeed(pipeline, _FEED_SEED)
        assert results == _feed(pipeline, _FEED_SEED)
        assert len(results) == length

    @pytest.mark.parametrize(("pipeline", "indexes"), SCALAR_PIPELINES)
    @async_test
    async def test_keeps_each_scalar_seed_item_s_identity(
        self, pipeline, indexes
    ) -> None:
        target = _seed_target(pipeline)
        results = await _afeed(pipeline, _SCALAR_SEED)
        assert results == _feed(pipeline, _SCALAR_SEED)
        assert [gen for _, gen in results] == [
            build_generation(target, MISSING, i) for i in indexes
        ]

    @pytest.mark.parametrize("pipeline", ASYNC_PARITY_PIPELINES)
    @async_test
    async def test_matches_a_sync_run(self, pipeline) -> None:
        expected = _multiset(_feed(pipeline, _FEED_SEED))
        assert _multiset(await _afeed(pipeline, _FEED_SEED)) == expected
