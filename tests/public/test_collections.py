# vim: sw=4:ts=4:expandtab
"""
Provides pipeline collection tests.
"""

from collections.abc import Awaitable, Callable, Iterable, Iterator
from multiprocessing.dummy import Pool as ThreadPool
from operator import itemgetter
from typing import Any, cast

import pytest

from riko import get_path
from riko._iterutils import noop
from riko._pubsub import async_hub, close, sync_hub
from riko.bado import gather_results, issync, run
from riko.collections import AsyncPipe, Executor, SyncCollection, SyncPipe
from riko.exceptions import ReceiverUnavailableError
from riko.types.general import Item, Items
from riko.types.modules import (
    ItemBuilderConf,
    ParsedParam,
    ReceiveConf,
    StrReplaceConf,
    StrReplaceConfRule,
)
from riko.types.values import StreamState
from tests import PipeBuilder

value = "once is 1x,twice is 2x,thrice is 3x"
attrs = ParsedParam({"key": "content", "value": value})
builder_conf = ItemBuilderConf({"attrs": attrs})
recv_conf = ReceiveConf({"wait": 0.001, "max_wait": 2})
strr_conf = StrReplaceConf({"rule": StrReplaceConfRule(find="is", replace="was")})
marks = pytest.mark.skipif(issync, reason="async support not available")


async def _gather_pubsub(sender: AsyncPipe, *receivers: AsyncPipe) -> list[Items]:
    results = await gather_results([*receivers, sender])
    return [list(result) for result in results]


async def _drain_ghost(sender: AsyncPipe) -> Items:
    return [item async for item in sender]


_ENGINES = [
    pytest.param(SyncPipe, id="sync"),
    pytest.param(AsyncPipe, id="async", marks=marks),
]

SRC = [{"content": "a"}, {"content": "b"}, {"content": "c"}]


def _aresolve[T](awaitable: Awaitable[Any], extract: Callable[..., T]) -> T:
    """Await *awaitable* on the async engine and return ``extract`` of the result."""

    async def _collect() -> T:
        return extract(await awaitable)

    return run(_collect)


def _run_on[T](
    pipe: type[SyncPipe] | type[AsyncPipe],
    build: PipeBuilder,
    extract: Callable[..., T],
) -> T:
    """
    Build a pipeline on *pipe*, resolve it, and return ``extract`` applied to
    the result. ``build(pipe)`` yields the terminal chain object; on the async
    engine that object is awaited before ``extract`` runs, so a single spec drives
    both engines.
    """
    if pipe is SyncPipe:
        result = extract(build(pipe))
    else:
        result = _aresolve(build(cast(type[AsyncPipe], pipe)), extract)

    return result


def _first_two[T](splits: Iterable[Iterator[T]]) -> tuple[T, T]:
    stream1, stream2 = splits
    return next(stream1), next(stream2)


class _CollectionTest:
    def setup_method(self):
        self.runs = 0

    def udf(self, item: Item) -> Item:
        self.runs += 1
        return item


class TestSyncCollections(_CollectionTest):
    def test_pipes_use_loopability_for_mapping(self):
        source = [{"content": "one"}, {"content": "two"}]
        transformer = SyncPipe("strtransform", source=source)
        input_pipe = SyncPipe("input", source=source)

        assert transformer.loopable
        assert transformer.mapify
        assert not input_pipe.loopable
        assert not input_pipe.mapify

    def test_pubsub(self, caplog):
        names = ["receiver1", "receiver2"]
        receiver1, receiver2 = [
            SyncPipe("receive", conf={"name": name, **recv_conf}) for name in names
        ]

        assert next(receiver1) == {"state": StreamState.PENDING}

        sender = (
            SyncPipe("itembuilder", conf=builder_conf)
            .tokenizer(emit=True)
            .udf(func=self.udf)
            .send(others=names)
        )

        assert next(sender) == {"content": "once is 1x"}
        assert next(sender) == {"content": "twice is 2x"}
        err_msg = (
            "Attempted to send {'content': 'once is 1x'} to non-existent 'receiver2'"
        )
        assert caplog.records[0].message == err_msg

        assert self.runs == 2
        assert next(receiver1) == {"state": StreamState.PENDING}
        assert next(receiver1) == {"content": "once is 1x"}
        assert next(receiver2) == {"state": StreamState.PENDING}

        assert next(sender) == {"content": "thrice is 3x"}
        assert next(receiver1) == {"content": "twice is 2x"}
        assert next(receiver2) == {"state": StreamState.PENDING}

        with pytest.raises(StopIteration):
            next(sender)

        assert next(receiver1) == {"content": "thrice is 3x"}

        with pytest.raises(StopIteration):
            next(receiver1)

        assert list(sender) == []

    def test_pubsub_funcs(self, capsys):
        receiver = SyncPipe("receive", conf={"name": "receiver", **recv_conf})
        changer = SyncPipe("receive", conf={"name": "changer", **recv_conf}, func=len)
        printer = SyncPipe("receive", conf={"name": "printer", **recv_conf}, func=print)
        assert next(receiver) == {"state": StreamState.PENDING}
        assert next(printer) == {"state": StreamState.PENDING}
        assert next(changer) == {"state": StreamState.PENDING}

        sender = (
            SyncPipe("itembuilder", conf=builder_conf)
            .tokenizer(emit=True)
            .send(others=["receiver", "changer", "printer"])
        )

        assert next(sender) == {"content": "once is 1x"}
        assert next(receiver) == {"state": StreamState.PENDING}
        assert next(receiver) == {"content": "once is 1x"}
        assert next(changer) == {"state": StreamState.PENDING}
        assert next(changer) == 1
        assert next(printer) == {"state": StreamState.PENDING}
        assert next(printer) is None

        captured = capsys.readouterr()
        assert captured.out.split("\n")[0] == "{'content': 'once is 1x'}"

    def test_send_signals_done_on_early_close(self):
        """
        A sender abandoned before it exhausts still signals DONE to the
        receiver it bound to, so the receiver terminates promptly rather than
        blocking until its ``max_wait`` elapses.

        The receiver uses a 30s ``max_wait``; terminating within a handful of
        polls proves it stopped because of the DONE delivered on close, not a
        timeout (which would need ~30000 polls).
        """
        conf = ReceiveConf({"name": "r", "wait": 0.001, "max_wait": 30})
        receiver = SyncPipe("receive", conf=conf)
        assert next(receiver) == {"state": StreamState.PENDING}

        sender = (
            SyncPipe("itembuilder", conf=builder_conf)
            .tokenizer(emit=True)
            .send(others=["r"])
        )
        assert next(sender) == {"content": "once is 1x"}

        sender.close()
        drained = []

        for _ in range(100):
            try:
                drained.append(next(receiver))
            except StopIteration:
                break
        else:
            pytest.fail("receiver never terminated; DONE was not delivered on close")

        assert {"content": "once is 1x"} in drained

    def test_send_done_respects_channel_identity(self):
        """
        A sender's DONE is addressed to the exact receiver instance it bound
        to (by minted token), not merely to the channel name.

        The sender binds to two receivers. ``keep`` is left in place; ``r`` is
        replaced by a new receiver under the same name (a fresh token) before
        the sender is abandoned. Closing the sender delivers DONE to ``keep``
        (identity matches) but not to the replacement of ``r`` (stale token).
        The ``keep`` assertion is a positive control: it fails unless the close
        actually fired, so the identity assertion cannot pass vacuously.
        """
        r_conf = ReceiveConf({"name": "r", "wait": 0.001, "max_wait": 30})
        keep_conf = ReceiveConf({"name": "keep", "wait": 0.001, "max_wait": 30})
        first = SyncPipe("receive", conf=r_conf)
        keep = SyncPipe("receive", conf=keep_conf)
        next(first)
        next(keep)

        sender = (
            SyncPipe("itembuilder", conf=builder_conf)
            .tokenizer(emit=True)
            .send(others=["r", "keep"])
        )
        assert next(sender) == {"content": "once is 1x"}

        close("r")
        second = SyncPipe("receive", conf=r_conf)
        next(second)
        sender.close()
        keep_q = list(sync_hub.queues.get("keep") or [])
        r_q = list(sync_hub.queues.get("r") or [])
        assert any(state is StreamState.DONE for state, _ in keep_q)
        assert all(state is not StreamState.DONE for state, _ in r_q)

    def test_stream(self):
        """Tests a basic stream pipeline."""
        stream = (
            SyncPipe("itembuilder", conf=builder_conf)
            .tokenizer(emit=True)
            .strreplace(conf=strr_conf, assign="content")
            .slugify(assign="content")
            .hash(assign="content")
            .udf(func=self.udf)
        )

        first_item = next(stream)
        assert first_item == {"content": 396558121}
        assert self.runs == 1

    @pytest.mark.timeout(30)
    def test_pstream(self):
        """Tests a parallel stream pipeline."""
        stream = (
            SyncPipe("itembuilder", conf=builder_conf, parallel=True)
            .tokenizer(emit=True)
            .strreplace(conf=strr_conf, assign="content")
            .slugify(assign="content")
            .hash(assign="content")
            .udf(func=self.udf)
        )

        expected = (
            SyncPipe("itembuilder", conf=builder_conf)
            .tokenizer(emit=True)
            .strreplace(conf=strr_conf, assign="content")
            .slugify(assign="content")
            .hash(assign="content")
        )
        result = list(stream)
        actual_content = sorted(cast(dict, item)["content"] for item in result)
        expected_content = sorted(cast(dict, item)["content"] for item in expected)
        assert actual_content == expected_content
        assert self.runs == 3


class TestSyncPipeExecutor:
    def test_process_executor_creates_pool(self):
        with SyncPipe("hash", source=SRC, parallel=True, threads=False) as pipe:
            assert pipe.executor is Executor.PROCESS
            assert pipe.pool is not None
            assert len(list(pipe)) == 3

    def test_thread_executor_creates_pool(self):
        with SyncPipe("hash", source=SRC, parallel=True) as pipe:
            assert pipe.executor is Executor.THREAD
            assert pipe.pool is not None
            assert len(list(pipe)) == 3

    def test_inline_skips_pool_and_runs_sequentially(self):
        pipe = SyncPipe("hash", source=SRC)
        assert pipe.executor is Executor.INLINE
        assert not pipe.parallelize
        assert pipe.pool is None
        assert len(list(pipe)) == 3

    def test_executor_propagates_through_chain(self):
        head = SyncPipe("itembuilder", conf={"attrs": {"key": "content", "value": "a"}})
        assert head.hash().executor is Executor.INLINE


@pytest.mark.skipif(issync, reason="async support not available")
class TestAsyncCollections(_CollectionTest):
    def test_pipes_use_loopability_for_mapping(self):
        async_transformer = AsyncPipe("strtransform")
        async_input_pipe = AsyncPipe("input")

        assert async_transformer.loopable
        assert async_transformer.mapify
        assert not async_input_pipe.loopable
        assert not async_input_pipe.mapify

    def test_stream(self, capsys):
        """Tests a asynchronous stream pipeline."""

        async def main():
            stream = await (
                AsyncPipe("itembuilder", conf=builder_conf)
                .tokenizer(emit=True)
                .udf(func=self.udf)
                .strreplace(conf=strr_conf, assign="content")
                .udf(func=self.udf)
                .slugify(assign="content")
                .udf(func=self.udf)
                .hash(assign="content")
            )

            print(next(stream))

        run(main)

        captured = capsys.readouterr()
        assert self.runs == 9
        assert captured.out == "{'content': 396558121}\n"

    @pytest.mark.anyio
    @pytest.mark.timeout(10)
    def test_pubsub(self):
        """
        Two concurrent async receivers each collect every item a sender pushes,
        and the sender's own output is unchanged (passthrough).

        Each receiver has its own AnyIO rendezvous channel; publish and subscribe
        converge on the same named slot, so startup needs no delay and completion
        is channel closure (nothing coordinates startup or DONE by hand). If
        completion regressed the receivers would block forever, so the timeout
        marker makes that a failure rather than a hang. Delivery is materialized
        (P7.2): each receiver returns its whole batch once the sender completes.
        """
        names = ["receiver1", "receiver2"]
        receivers = [
            AsyncPipe("receive", conf={"name": name, **recv_conf}) for name in names
        ]
        sender = (
            AsyncPipe("itembuilder", conf=builder_conf)
            .tokenizer(emit=True)
            .udf(func=self.udf)
            .send(others=["receiver1", "receiver2"])
        )

        expected = [
            {"content": "once is 1x"},
            {"content": "twice is 2x"},
            {"content": "thrice is 3x"},
        ]

        for result in run(_gather_pubsub, sender, *receivers):
            assert result == expected

        assert self.runs == 3

        # After a normal run no channel slot lingers in the async hub
        assert not async_hub._slots

    def test_pubsub_funcs(self, capsys):
        receiver = AsyncPipe("receive", conf={"name": "receiver", **recv_conf})
        changer = AsyncPipe("receive", conf={"name": "changer", **recv_conf}, func=len)
        printer = AsyncPipe(
            "receive", conf={"name": "printer", **recv_conf}, func=print
        )

        sender = (
            AsyncPipe("itembuilder", conf=builder_conf)
            .tokenizer(emit=True)
            .send(others=["receiver", "changer", "printer"])
        )

        expected_receiver = [
            {"content": "once is 1x"},
            {"content": "twice is 2x"},
            {"content": "thrice is 3x"},
        ]

        expected_changer = [1, 1, 1]
        expected_printer = [None, None, None]

        results = run(_gather_pubsub, sender, receiver, changer, printer)
        assert results[0] == expected_receiver
        assert results[3] == expected_receiver
        assert results[1] == expected_changer
        assert results[2] == expected_printer

        captured = capsys.readouterr()
        assert captured.out.split("\n")[0] == "{'content': 'once is 1x'}"

    @pytest.mark.anyio
    @pytest.mark.timeout(10)
    def test_pubsub_missing_receiver_times_out(self):
        """
        A publish to a name that is never subscribed fails fast, bounded by
        ``max_wait``, rather than dropping data or hanging.
        """
        sender = (
            AsyncPipe("itembuilder", conf=builder_conf)
            .tokenizer(emit=True)
            .send(others=["ghost"], conf={"max_wait": 0.05})
        )

        with pytest.raises(ReceiverUnavailableError):
            run(_drain_ghost, sender)

    def test_pstream(self):
        """Tests a parallel asynchronous stream pipeline."""
        result = {}

        async def main():
            stream = await (
                AsyncPipe("itembuilder", conf=builder_conf, parallel=True)
                .tokenizer(emit=True)
                .strreplace(conf=strr_conf, assign="content")
                .slugify(assign="content")
                .hash(assign="content")
                .udf(func=self.udf)
            )
            result["first"] = next(stream)

        run(main)
        assert result["first"] == {"content": 396558121}
        assert self.runs == 3


class TestCollectionParity(_CollectionTest):
    """Behaviors whose observable output is identical across both engines."""

    @pytest.mark.parametrize("pipe", _ENGINES)
    def test_udf(self, pipe):
        build = lambda pipe: (
            pipe("itembuilder", conf=builder_conf)
            .tokenizer(emit=True)
            .udf(func=itemgetter("content"))
        )
        assert _run_on(pipe, build, next) == "once is 1x"

    @pytest.mark.parametrize("pipe", _ENGINES)
    def test_export(self, pipe):
        build = lambda pipe: (
            pipe("itembuilder", conf=builder_conf).tokenizer(emit=True).export()
        )
        assert _run_on(pipe, build, noop) == [
            {"content": "once is 1x"},
            {"content": "twice is 2x"},
            {"content": "thrice is 3x"},
        ]

    @pytest.mark.parametrize("pipe", _ENGINES)
    def test_split(self, pipe):
        build = lambda pipe: (
            pipe("itembuilder", conf=builder_conf)
            .tokenizer(emit=True)
            .udf(func=self.udf)
            .split()
        )
        first1, first2 = _run_on(pipe, build, _first_two)
        assert first1 == {"content": "once is 1x"}
        assert first2 == {"content": "once is 1x"}
        assert self.runs == 3


class TestPoolLifecycle:
    """Owned pools are cleaned up; caller-provided pools remain usable."""

    def _parallel_pipe(self) -> SyncPipe:
        source = [{"content": "a"}, {"content": "b"}]
        return SyncPipe("hash", source=source, parallel=True)

    def test_enter_returns_self(self):
        pipe = self._parallel_pipe()

        with pipe as flow:
            assert flow is pipe

    def test_owned_pool_closed_on_exit(self):
        pipe = self._parallel_pipe()

        assert pipe._pool_handle is not None
        assert pipe._pool_handle.owned
        assert pipe.pool is not None

        with pipe:
            assert len(list(pipe)) == 2
            assert pipe.pool is not None

        assert pipe.pool is None
        assert pipe._pool_handle.owned

    def test_owned_pool_terminated_on_exception(self):
        pipe = self._parallel_pipe()

        assert pipe._pool_handle is not None
        assert pipe._pool_handle.owned
        assert pipe.pool is not None

        with pytest.raises(RuntimeError), pipe:
            raise RuntimeError("boom")

        assert pipe.pool is None
        assert pipe._pool_handle.owned

    def test_borrowed_pool_not_closed(self):
        pool = ThreadPool(2)

        try:
            source = [{"content": "a"}]
            pipe = SyncPipe("hash", source=source, parallel=True, pool=pool)

            assert pipe._pool_handle is not None
            assert not pipe._pool_handle.owned
            assert pipe.pool is pool

            with pipe:
                assert len(list(pipe)) == 1

            assert pipe.pool is pool
            assert pool.map(lambda x: x, [1, 2]) == [1, 2]
        finally:
            pool.close()
            pool.join()

    def test_close_is_idempotent(self):
        pipe = self._parallel_pipe()
        pipe.close()
        pipe.close()
        assert pipe.pool is None

    def test_collection_owned_pool_closed_on_exit(self):
        coll = SyncCollection([{"url": get_path("feed.xml")}], parallel=True)

        assert coll._pool_handle is not None
        assert coll._pool_handle.owned
        assert coll.pool is not None

        with coll:
            assert list(coll)
            assert coll.pool is not None

        assert coll.pool is None
        assert coll._pool_handle.owned


class TestSyncPipeChaining:
    """positional ``.pipe(name)`` and the ``|`` operators."""

    def test_pipe_accepts_positional_name(self):
        flow = SyncPipe("hash", source=SRC)
        chained = flow.pipe("hash")
        assert chained.name == "hash"
        assert chained.source is flow
        assert len(list(chained)) == 3

    def test_pipe_method_matches_operator(self):
        flow = SyncPipe("hash", source=SRC)
        chained = flow.pipe("truncate", conf={"count": 1})
        assert chained.name == "truncate"
        assert chained.conf == {"count": 1}
        assert len(list(chained)) == 1

    def test_or_string_matches_attribute_chaining(self):
        via_or = list(SyncPipe("hash", source=SRC) | "hash")
        via_attr = list(SyncPipe("hash", source=SRC).hash())
        assert via_or == via_attr
        assert len(via_or) == 3

    def test_or_string_sets_source_to_lhs(self):
        flow = SyncPipe("hash", source=SRC)
        piped = flow | "hash"
        assert piped.name == "hash"
        assert piped.source is flow

    def test_or_tuple_applies_conf(self):
        piped = SyncPipe("hash", source=SRC) | ("truncate", {"count": 1})
        assert piped.name == "truncate"
        assert piped.conf == {"count": 1}
        assert len(list(piped)) == 1

    def test_or_template_rebinds_onto_lhs(self):
        flow = SyncPipe("hash", source=SRC)
        piped = flow | SyncPipe("truncate", conf={"count": 1})
        assert piped.name == "truncate"
        assert piped.conf == {"count": 1}
        assert piped.source is flow
        assert len(list(piped)) == 1

    def test_ror_seeds_source_from_stream(self):
        primed = SRC | SyncPipe("hash")
        assert primed.name == "hash"
        assert list(primed.source) == SRC
        assert len(list(primed)) == 3

    def test_ror_preserves_definitional_kwargs(self):
        primed = SRC | SyncPipe("tokenizer", conf={"delimiter": " "}, emit=False)
        assert primed.name == "tokenizer"
        assert not primed.kwargs["emit"]

    def test_or_unsupported_rhs_raises_type_error(self):
        with pytest.raises(TypeError):
            _ = SyncPipe("hash", source=SRC) | 5

    def test_ror_rejects_non_template_target(self):
        # a source-bound pipe is not a rebind target
        with pytest.raises(TypeError):
            _ = SRC | SyncPipe("hash", source=SRC)


@pytest.mark.skipif(issync, reason="async support not available")
class TestAsyncPipeChaining:
    """The ``|`` operators wire AsyncPipe stages (construction is loop-free)."""

    def test_async_pipe_accepts_positional_name(self):
        flow = AsyncPipe("hash", source=SRC)
        chained = flow.async_pipe("hash")
        assert chained.name == "hash"
        assert chained.source is flow

    def test_or_string_and_tuple(self):
        flow = AsyncPipe("hash", source=SRC)
        assert (flow | "hash").name == "hash"
        spec = AsyncPipe("hash", source=SRC) | ("truncate", {"count": 1})
        assert spec.name == "truncate"
        assert spec.conf == {"count": 1}

    def test_or_template_rebinds_onto_lhs(self):
        flow = AsyncPipe("hash", source=SRC)
        piped = flow | AsyncPipe("truncate", conf={"count": 1})
        assert piped.name == "truncate"
        assert piped.conf == {"count": 1}
        assert piped.source is flow

    def test_ror_seeds_source_from_stream(self):
        primed = SRC | AsyncPipe("hash")
        assert primed.name == "hash"
        assert primed.source is not None

    def test_or_unsupported_rhs_raises_type_error(self):
        with pytest.raises(TypeError):
            _ = AsyncPipe("hash", source=SRC) | 5
