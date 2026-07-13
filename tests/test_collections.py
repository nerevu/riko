# vim: sw=4:ts=4:expandtab
"""
Provides pipeline collection tests.
"""

from operator import itemgetter

import pytest

from riko.bado import _issync, coroutine, react
from riko.bado.mock import FakeReactor
from riko.collections import AsyncPipe, SyncPipe
from riko.utils import StreamState, noop

value = "once is 1x,twice is 2x,thrice is 3x"
attrs = {"key": "content", "value": value}
builder_conf = {"attrs": attrs}
done_conf = {"attrs": {"key": "state", "value": StreamState.DONE}}
strr_conf = {"rule": {"find": "is", "replace": "was"}}


class TestCollections:
    def setup_method(self):
        self.runs = 0

    def udf(self, item):
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
        receiver = SyncPipe("receive", conf={"name": "receiver"})
        changer = SyncPipe("receive", conf={"name": "changer"}, func=len)
        printer = SyncPipe("receive", conf={"name": "printer"}, func=print)
        assert next(receiver) == {"content": StreamState.PENDING}
        assert next(printer) == {"content": StreamState.PENDING}
        assert next(changer) == {"content": StreamState.PENDING}

        stream = (
            SyncPipe("itembuilder", conf=builder_conf)
            .tokenizer(emit=True)
            .send(others=["receiver", "changer", "printer"])
        )

        assert next(stream) == {"content": "once is 1x"}
        assert next(receiver) == {"content": StreamState.PENDING}
        assert next(receiver) == {"content": "once is 1x"}
        assert next(changer) == {"content": StreamState.PENDING}
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
        receiver1 = SyncPipe("receive", conf={"name": "receiver1"}, func=noop)
        receiver2 = SyncPipe("receive", conf={"name": "receiver2"}, func=noop)
        assert next(receiver1) == {"content": StreamState.PENDING}

        stream = (
            SyncPipe("itembuilder", conf=builder_conf)
            .tokenizer(emit=True)
            .udf(func=self.udf)
            .send(others=["receiver1", "receiver2"])
        )

        assert next(stream) == {"content": "once is 1x"}
        assert next(stream) == {"content": "twice is 2x"}
        err_msg = (
            "Attempted to send {'content': 'once is 1x'} to non-existent 'receiver2'"
        )
        assert caplog.records[0].message == err_msg

        assert self.runs == 2
        assert next(receiver1) == {"content": StreamState.PENDING}
        assert next(receiver1) == {"content": "once is 1x"}
        assert next(receiver2) == {"content": StreamState.PENDING}

        assert next(stream) == {"content": "thrice is 3x"}
        assert next(receiver1) == {"content": "twice is 2x"}
        assert next(receiver2) == {"content": StreamState.PENDING}

        with pytest.raises(StopIteration):
            next(stream)

        assert next(receiver1) == {"content": "thrice is 3x"}

        with pytest.raises(StopIteration):
            next(receiver1)

        assert stream.list == []

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

        @coroutine  # pyright: ignore[reportArgumentType]
        def run(reactor):
            stream = yield (
                AsyncPipe("itembuilder", conf=builder_conf)
                .tokenizer(emit=True)
                .udf(func=self.udf)
                .strreplace(conf=strr_conf, assign="content")
                .udf(func=self.udf)
                .slugify(assign="content")
                .udf(func=self.udf)
                .hash(assign="content")
            )

            print(next(stream)["content"])

        try:
            react(run, _reactor=FakeReactor())
        except SystemExit:
            pass
        else:
            captured = capsys.readouterr()
            assert self.runs == 9
            assert captured.out == "396558121\n"
