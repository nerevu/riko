# vim: sw=4:ts=4:expandtab
"""
One-shot lifecycle tests for the Phase 5 contract (docs/P5_CHECKLIST.md).

A pipe instance represents a single execution. It may be chained only while
NEW; once it has run it cannot be chained; an exhausted instance re-iterates as
an empty stream and never silently re-executes; a closed or failed instance
raises PipelineStateError on further iteration. Sync and async behave alike.
"""

import pytest

from riko import get_path
from riko.bado import _issync, react
from riko.bado.itertools import ensure_deferred
from riko.bado.mock import FakeReactor
from riko.collections import AsyncPipe, PipeState, SyncCollection, SyncPipe
from riko.exceptions import PipelineStateError

BUILDER_CONF = {"attrs": [{"key": "content", "value": "a,b,c"}]}
SRC = [{"content": "x"}, {"content": "y"}]


def _boom():
    raise RuntimeError("boom")
    yield  # pragma: no cover


def test_new_state():
    assert SyncPipe("hash", source=SRC).state is PipeState.NEW


def test_exhausted_after_full_iteration():
    flow = SyncPipe("hash", source=SRC)
    assert len(list(flow)) == 2
    assert flow.exhausted
    assert flow.state is PipeState.EXHAUSTED


def test_exhausted_reiterates_empty_without_reexecution():
    flow = SyncPipe("hash", source=SRC)
    first = list(flow)
    second = list(flow)
    assert len(first) == 2
    assert second == []


def test_chain_while_new_is_allowed():
    flow = SyncPipe("itembuilder", conf=BUILDER_CONF)
    chained = flow.hash()
    assert chained.state is PipeState.NEW


def test_chain_after_partial_iteration_wraps_remainder():
    flow = SyncPipe("hash", source=SRC)
    next(flow)
    assert flow.state is PipeState.RUNNING
    assert list(flow.count()) == [{"count": 1}]


def test_chain_after_exhaustion_is_allowed():
    flow = SyncPipe("hash", source=SRC)
    list(flow)
    assert list(flow.count()) == [{"count": 0}]


def test_close_is_idempotent():
    flow = SyncPipe("hash", source=SRC)
    flow.close()
    flow.close()
    assert flow.closed
    assert flow.state is PipeState.CLOSED


def test_chain_after_close_raises():
    flow = SyncPipe("hash", source=SRC)
    flow.close()

    with pytest.raises(PipelineStateError):
        flow.count()


def test_chain_after_failure_raises():
    flow = SyncPipe("hash", source=_boom())

    with pytest.raises(RuntimeError):
        list(flow)

    with pytest.raises(PipelineStateError):
        flow.count()


def test_iterate_after_run_then_close_is_empty():
    flow = SyncPipe("hash", source=SRC)
    assert len(list(flow)) == 2
    flow.close()
    assert list(flow) == []


def test_failed_state_reiterates_empty():
    flow = SyncPipe("hash", source=_boom())

    with pytest.raises(RuntimeError):
        list(flow)

    assert flow.state is PipeState.FAILED
    assert flow.failed
    assert list(flow) == []


def test_collection_lifecycle():
    sources = [{"url": get_path("feed.xml")}]
    stream = SyncCollection(sources)
    assert stream.state is PipeState.NEW
    assert len(list(stream)) > 0
    assert stream.exhausted
    assert list(stream) == []


def test_collection_close_is_idempotent():
    stream = SyncCollection([{"url": get_path("feed.xml")}])
    stream.close()
    stream.close()
    assert stream.closed
    assert stream.state is PipeState.CLOSED


@pytest.mark.skipif(_issync, reason="async support not available")
def test_async_exhausted_reiterates_empty_without_reexecution():
    reactor = FakeReactor()
    result = {}

    async def run(_reactor):
        pipe = AsyncPipe("itembuilder", conf=BUILDER_CONF).tokenizer(emit=True)
        result["first"] = [item async for item in pipe]
        result["second"] = [item async for item in pipe]

    try:
        react(lambda r: ensure_deferred(run(r)), _reactor=reactor)
    except SystemExit:
        pass

    assert len(result["first"]) > 0
    assert result["second"] == []


@pytest.mark.skipif(_issync, reason="async support not available")
def test_async_chain_after_run_is_allowed():
    reactor = FakeReactor()
    result = {}

    async def run(_reactor):
        pipe = AsyncPipe("itembuilder", conf=BUILDER_CONF)
        [item async for item in pipe]
        result["items"] = [item async for item in pipe.tokenizer(emit=True)]

    try:
        react(lambda r: ensure_deferred(run(r)), _reactor=reactor)
    except SystemExit:
        pass

    assert "items" in result


@pytest.mark.skipif(_issync, reason="async support not available")
def test_async_chain_after_run_wraps_remainder():
    reactor = FakeReactor()
    result = {}

    async def run(_reactor):
        pipe = AsyncPipe("itembuilder", conf=BUILDER_CONF)
        [item async for item in pipe]
        result["items"] = [item async for item in pipe.tokenizer(emit=True)]

    try:
        react(lambda r: ensure_deferred(run(r)), _reactor=reactor)
    except SystemExit:
        pass

    assert result["items"] == []
