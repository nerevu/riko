# vim: sw=4:ts=4:expandtab
"""
Provides pipeline collection tests.
"""

from multiprocessing.dummy import Pool as ThreadPool
from operator import itemgetter
from typing import cast

import pytest

from riko import get_path
from riko.bado import IReactorCore, _issync, react
from riko.bado.itertools import ensure_deferred
from riko.bado.mock import FakeReactor
from riko.collections import AsyncPipe, SyncCollection, SyncPipe
from riko.types.general import Item
from riko.types.modules import (
    ItemBuilderConf,
    ParsedParam,
    ReceiveConf,
    StrReplaceConf,
    StrReplaceConfRule,
)
from riko.types.values import StreamState
from riko.utils import noop

value = "once is 1x,twice is 2x,thrice is 3x"
attrs = ParsedParam({"key": "content", "value": value})
builder_conf = ItemBuilderConf({"attrs": attrs})
done_conf = {"attrs": {"key": "state", "value": StreamState.DONE}}
strr_conf = StrReplaceConf({"rule": StrReplaceConfRule(find="is", replace="was")})
reactor = cast(IReactorCore, FakeReactor())


class TestCollections:
    def setup_method(self):
        self.runs = 0

    def udf(self, item: Item) -> Item:
        self.runs += 1
        return item

    def test_udf(self):
        stream = (
            SyncPipe("itembuilder", conf=builder_conf)
            .tokenizer(emit=True)
            .udf(func=itemgetter("content"))
        )
        assert next(stream) == "once is 1x"

    def test_send(self):
        SyncPipe("receive", conf={"name": "receiver"})
        SyncPipe("receive", conf={"name": "printer"})

        stream = (
            SyncPipe("itembuilder", conf=builder_conf)
            .tokenizer(emit=True)
            .send(others=["receiver", "printer"])
        )

        assert next(stream) == {"content": "once is 1x"}

    def test_receive(self, capsys):
        _conf = ReceiveConf({"wait": 0.001, "max_wait": 2})
        receiver = SyncPipe("receive", conf=ReceiveConf({"name": "receiver", **_conf}))
        changer = SyncPipe("receive", conf={"name": "changer", **_conf}, func=len)
        printer = SyncPipe("receive", conf={"name": "printer", **_conf}, func=print)
        assert next(receiver) == {"state": StreamState.PENDING}
        assert next(printer) == {"state": StreamState.PENDING}
        assert next(changer) == {"state": StreamState.PENDING}

        stream = (
            SyncPipe("itembuilder", conf=builder_conf)
            .tokenizer(emit=True)
            .send(others=["receiver", "changer", "printer"])
        )

        assert next(stream) == {"content": "once is 1x"}
        assert next(receiver) == {"state": StreamState.PENDING}
        assert next(receiver) == {"content": "once is 1x"}
        assert next(changer) == {"state": StreamState.PENDING}
        assert next(changer) == 1

        next(printer)
        captured = capsys.readouterr()
        assert captured.out.split("\n")[0] == "{'content': 'once is 1x'}"

    def test_split(self):
        stream = (
            SyncPipe("itembuilder", conf=builder_conf)
            .tokenizer(emit=True)
            .udf(func=self.udf)
            .split()
        )

        stream1, stream2 = stream
        assert next(stream1) == {"content": "once is 1x"}
        assert next(stream2) == {"content": "once is 1x"}
        assert self.runs == 3

    def test_pubsub(self, caplog):
        _conf = ReceiveConf({"wait": 0.001, "max_wait": 2})
        receiver1 = SyncPipe("receive", conf={"name": "receiver1", **_conf}, func=noop)
        receiver2 = SyncPipe("receive", conf={"name": "receiver2", **_conf}, func=noop)
        assert next(receiver1) == {"state": StreamState.PENDING}

        stream = (
            SyncPipe("itembuilder", conf=builder_conf)
            .tokenizer(emit=True)
            .udf(func=self.udf)
            .send(others=["receiver2", "receiver1"])
        )

        assert next(stream) == {"content": "once is 1x"}
        assert next(stream) == {"content": "twice is 2x"}
        err_msg = (
            "Attempted to send {'content': 'once is 1x'} to non-existent 'receiver2'"
        )
        assert caplog.records[0].message == err_msg

        assert self.runs == 2
        assert next(receiver1) == {"state": StreamState.PENDING}
        assert next(receiver1) == {"content": "once is 1x"}
        assert next(receiver2) == {"state": StreamState.PENDING}

        assert next(stream) == {"content": "thrice is 3x"}
        assert next(receiver1) == {"content": "twice is 2x"}
        assert next(receiver2) == {"state": StreamState.PENDING}

        with pytest.raises(StopIteration):
            next(stream)

        assert next(receiver1) == {"content": "thrice is 3x"}

        with pytest.raises(StopIteration):
            next(receiver1)

        assert list(stream) == []

    def test_pipes_use_loopability_for_mapping(self):
        source = [{"content": "one"}, {"content": "two"}]
        transformer = SyncPipe("strtransform", source=source)
        input_pipe = SyncPipe("input", source=source)

        assert transformer.loopable
        assert transformer.mapify
        assert not input_pipe.loopable
        assert not input_pipe.mapify

        async_transformer = AsyncPipe("strtransform")
        async_input_pipe = AsyncPipe("input")

        assert async_transformer.loopable
        assert async_transformer.mapify
        assert not async_input_pipe.loopable
        assert not async_input_pipe.mapify

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

        first_item = next(stream)
        assert first_item == {"content": 396558121}
        assert self.runs == 3

    @pytest.mark.skipif(_issync, reason="async support not available")
    def test_astream(self, capsys):
        """Tests a asynchronous stream pipeline."""

        async def run(reactor):
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

        try:
            react(lambda r: ensure_deferred(run(r)), _reactor=reactor)
        except SystemExit:
            pass
        else:
            captured = capsys.readouterr()
            assert self.runs == 9
            assert captured.out == "396558121\n"


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
