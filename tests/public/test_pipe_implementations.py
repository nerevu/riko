# vim: sw=4:ts=4:expandtab
"""
Tests pipe implementations.
"""

from itertools import count
from typing import Any

import pytest

from riko._pubsub import async_hub
from riko.bado import create_task_group, run
from riko.cast import SortableCastType
from riko.exceptions import ReceiverUnavailableError
from riko.modules.join import pipe as join_pipe
from riko.modules.send import async_pipe as async_send
from riko.modules.sort import pipe as sort_pipe
from riko.types.general import Feed, Item, ItemOrValue, Stream
from riko.types.modules import JoinConf, SendConf, SortConf, SortConfRule
from tests import skipif_issync


def _values(stream: Any, key: str) -> list[Any]:
    return [item.get(key) for item in stream]


_LOOKAHEAD = 2
_SOURCE_LEN = 5


def _counting_source(consumed: list[int]) -> Any:
    for i in count():
        consumed.append(i)
        yield {"x": "foo", "i": i}


@pytest.mark.parametrize(
    ("dir_", "type_", "vals"),
    [
        ("asc", SortableCastType.FLOAT, ["1", "2", "3"]),
        ("asc", SortableCastType.DECIMAL, ["1", "2", "3"]),
        ("asc", SortableCastType.DATE, ["2019-01-01", "2020-05-01", "2024-11-12"]),
        ("asc", SortableCastType.DATETIME, ["2019-01-01", "2020-05-01", "2024-11-12"]),
        ("desc", SortableCastType.FLOAT, ["1", "2", "3"]),
        ("desc", SortableCastType.DECIMAL, ["1", "2", "3"]),
        ("desc", SortableCastType.DATE, ["2019-01-01", "2020-05-01", "2024-11-12"]),
        ("desc", SortableCastType.DATETIME, ["2019-01-01", "2020-05-01", "2024-11-12"]),
    ],
)
def test_sort_fillers_stay_orderable(dir_, type_, vals: list[str]):
    """
    A missing or unparseable numeric field must not poison the sort with NaN.
    """
    rule = SortConfRule(field="n", dir=dir_, type=type_)
    conf = SortConf(rule=rule)

    if dir_ == "asc":
        expected_mid = [None, "abc", *vals]
        expected_first = ["abc", None, *vals]
    else:
        expected_mid = [*reversed(vals), None, "abc"]
        expected_first = [*reversed(vals), "abc", None]

    mid = [{"n": vals[2]}, {"x": "abc"}, {"n": "abc"}, {"n": vals[0]}, {"n": vals[1]}]
    first = [{"n": "abc"}, {"x": "abc"}, {"n": vals[2]}, {"n": vals[0]}, {"n": vals[1]}]

    assert _values(sort_pipe(mid, conf=conf), "n") == expected_mid
    assert _values(sort_pipe(first, conf=conf), "n") == expected_first


def test_keyed_join_does_not_materialize_its_primary():
    """
    ``other`` is the replayed side, so an unbounded primary must still emit.
    """
    consumed: list[int] = []
    other = [{"x": "bar", "c": 4}, {"x": "foo", "c": 5}]
    conf = JoinConf(join_key="x")
    joined = join_pipe(_counting_source(consumed), conf=conf, other=other)

    assert next(joined) == {"x": "foo", "i": 0, "c": 5}
    assert len(consumed) <= _LOOKAHEAD
    assert next(joined) == {"x": "foo", "i": 1, "c": 5}
    assert len(consumed) <= 1 + _LOOKAHEAD


def test_natural_join_does_not_materialize_its_primary():
    """
    The keyless natural join is lazy in its primary stream too.
    """
    consumed: list[int] = []
    joined = join_pipe(_counting_source(consumed), other=[{"c": 5}])

    assert next(joined) == {"x": "foo", "i": 0, "c": 5}
    assert len(consumed) <= _LOOKAHEAD


def _finite_source(consumed: list[int]) -> Stream:
    for i in range(_SOURCE_LEN):
        consumed.append(i)
        yield {"x": "foo", "i": i}


async def _afinite_source(consumed: list[int]) -> Feed:
    for i in range(_SOURCE_LEN):
        consumed.append(i)
        yield {"x": "foo", "i": i}


async def _drain(receive_stream: Any, into: list[Item] | None = None) -> None:
    async for item in receive_stream:
        if into is not None:
            into.append(item)


async def _send_first(consumed: list[int]) -> tuple[ItemOrValue, int]:
    first: ItemOrValue = {}
    seen = 0

    async with (
        async_hub.subscribe("r4-lazy") as receive_stream,
        create_task_group() as tg,
    ):
        tg.start_soon(_drain, receive_stream)
        stream = await async_send(_finite_source(consumed), others=["r4-lazy"])
        first = next(stream)
        seen = len(consumed)

    return (first, seen)


async def _send_missing_target(received: list[Item]) -> None:
    async with (
        async_hub.subscribe("r4-good") as receive_stream,
        create_task_group() as tg,
    ):
        tg.start_soon(_drain, receive_stream, received)

        with pytest.raises(ReceiverUnavailableError):
            await async_send(
                _finite_source([]),
                conf=SendConf(max_wait=0.05),
                others=["r4-good", "r4-missing"],
            )


async def _send_feed(consumed: list[int], received: list[Item]) -> list[ItemOrValue]:
    out: list[ItemOrValue] = []

    async with (
        async_hub.subscribe("r4-feed") as receive_stream,
        create_task_group() as tg,
    ):
        tg.start_soon(_drain, receive_stream, received)
        stream = await async_send(_afinite_source(consumed), others=["r4-feed"])
        out = list(stream)

    return out


async def _receive_first(consumed: list[int]) -> tuple[ItemOrValue, int]:
    first: ItemOrValue = {}
    seen = 0

    async def _snapshot(receive_stream: Any) -> None:
        nonlocal first, seen
        idx = 0

        async for item in receive_stream:
            if idx == 0:
                first, seen = item, len(consumed)

            idx += 1

    async with (
        async_hub.subscribe("r-recv-lazy") as receive_stream,
        create_task_group() as tg,
    ):
        tg.start_soon(_snapshot, receive_stream)
        await async_send(_finite_source(consumed), others=["r-recv-lazy"])

    return (first, seen)


@skipif_issync
@pytest.mark.timeout(10)
@pytest.mark.xfail(reason="lazy async fan-out is not yet implemented", strict=True)
def test_async_send_does_not_buffer_its_source():
    """
    Async ``send`` collects sent items and only returns after complete. So an unbounded
    source never returns.
    """
    consumed: list[int] = []
    first, seen = run(_send_first, consumed)

    assert first == {"x": "foo", "i": 0}
    assert seen <= _LOOKAHEAD


@skipif_issync
@pytest.mark.timeout(10)
def test_async_send_completes_targets_when_publish_fails():
    """
    A failed publish must still close the targets that did subscribe.

    ``publish`` raises ``ReceiverUnavailableError`` once an unsubscribed target
    outlasts ``max_wait``.
    """
    received: list[Item] = []
    run(_send_missing_target, received)
    assert received == [{"x": "foo", "i": 0}]


@skipif_issync
@pytest.mark.timeout(10)
def test_async_send_accepts_a_feed_source():
    """
    An async source reaches the parser as an ``AsyncIterator``, not a list.

    ``operator.aparse``/``setup`` hand the parser an async ``orig_stream`` when the
    caller passes a ``Feed``. So a sync ``for`` over it raises ``TypeError``.
    """
    consumed: list[int] = []
    received: list[Item] = []
    expected = [{"x": "foo", "i": i} for i in range(_SOURCE_LEN)]
    out = run(_send_feed, consumed, received)

    assert out == expected
    assert received == expected


@skipif_issync
@pytest.mark.timeout(10)
def test_async_receive_does_not_materialize():
    """
    The zero-buffer rendezvous channel hands each published item to the
    subscriber before ``send`` pulls the next one. A subscriber observes its first
    item while the source is barely read. It never waits for the whole source to
    materialize. (The eager bound is on ``send``'s own passthrough return; see
    ``test_async_send_does_not_buffer_its_source``.)
    """
    consumed: list[int] = []
    first, seen = run(_receive_first, consumed)

    assert first == {"x": "foo", "i": 0}
    assert seen <= _LOOKAHEAD


@skipif_issync
@pytest.mark.timeout(10)
def test_async_subscriber_sees_item_before_publisher_completes():
    """
    The canonical incremental-delivery contract: a subscriber's first item
    arrives before the publisher finishes reading its source (a weaker bound
    than ``test_async_receive_does_not_materialize``).
    """
    consumed: list[int] = []
    first, seen = run(_receive_first, consumed)

    assert first == {"x": "foo", "i": 0}
    assert seen < _SOURCE_LEN
