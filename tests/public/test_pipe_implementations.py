# vim: sw=4:ts=4:expandtab
"""
Tests pipe implementations.
"""

from itertools import count
from typing import Any

import pytest

from riko._pubsub import async_hub
from riko.bado._backend import create_task_group
from riko.cast import SortableCastType
from riko.exceptions import ReceiverUnavailableError
from riko.modules.aggregate import pipe as aggregate_pipe
from riko.modules.filter import pipe as filter_pipe
from riko.modules.join import pipe as join_pipe
from riko.modules.receive import pipe as receive_pipe
from riko.modules.send import async_pipe as async_send
from riko.modules.send import pipe as send_pipe
from riko.modules.sort import pipe as sort_pipe
from riko.modules.udf import pipe as udf_pipe
from riko.types._streams import Feed, Item, ItemOrValue, Stream
from riko.types.modules import (
    FilterConf,
    FilterConfRule,
    JoinConf,
    SendConf,
    SortConf,
    SortConfRule,
)
from tests import async_test


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


def test_filter_greater_less_compare_strings_lexicographically():
    """
    ``greater``/``less`` only coerce to numeric when the field value is already numeric.
    String values compare lexicographically, e.g.,``"9" > "10"`` is True. This lets
    ``x greater "10"`` permit ``"9"``.

    Numeric values compare numerically. So ``x greater 10`` permits neither ``9`` nor
    ``10``.
    """
    strings = [{"x": "9"}, {"x": "10"}]
    string_rule = FilterConfRule(field="x", op="greater", value="10")
    conf = FilterConf({"rule": string_rule})
    assert _values(filter_pipe(strings, conf=conf), "x") == ["9"]

    numbers = [{"x": 9}, {"x": 10}]
    numeric_rule = FilterConfRule(field="x", op="greater", value=10)
    conf = FilterConf({"rule": numeric_rule})
    assert _values(filter_pipe(numbers, conf=conf), "x") == []


@pytest.mark.parametrize(
    ("pipe", "operand"),
    [
        (udf_pipe, "func"),
        (aggregate_pipe, "func"),
        (join_pipe, "other"),
        (send_pipe, "others"),
    ],
)
def test_omitting_an_operand_raises(pipe: Any, operand: str):
    """
    An omitted operand is a call-site error, so ``require_arg`` names it.
    """
    with pytest.raises(TypeError, match=f"requires the {operand!r} keyword"):
        list(pipe([{"x": 0}]))


@pytest.mark.parametrize(
    ("pipe", "operand", "value"),
    [
        (udf_pipe, "func", 0),
        (aggregate_pipe, "func", 0),
        (join_pipe, "other", []),
        (send_pipe, "others", []),
    ],
)
def test_passing_an_empty_operand_raises(pipe: Any, operand: str, value: object):
    """
    An empty operand is a call-site error, so ``require_arg`` names it.
    """
    kwargs = {operand: value}

    with pytest.raises(TypeError, match=f"requires the {operand!r} keyword"):
        list(pipe([{"x": 0}], **kwargs))


def test_send_populates_ids_when_given():
    """
    The explicit ``ids`` parameter records each target's delivery id.
    """
    receiver = receive_pipe(conf={"name": "id-target", "wait": 0.01, "max_wait": 2})
    next(receiver)
    ids: dict[str, int] = {}
    list(send_pipe([{"x": 0}], others=["id-target"], ids=ids))
    assert isinstance(ids.get("id-target"), int)


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


@pytest.mark.timeout(10)
@pytest.mark.xfail(reason="lazy async fan-out is not yet implemented", strict=True)
@async_test
async def test_async_send_does_not_buffer_its_source():
    """
    Async ``send`` collects sent items and only returns after complete. So an unbounded
    source never returns.
    """
    consumed: list[int] = []
    first, seen = await _send_first(consumed)

    assert first == {"x": "foo", "i": 0}
    assert seen <= _LOOKAHEAD


@pytest.mark.timeout(10)
@async_test
async def test_async_send_completes_targets_when_publish_fails():
    """
    A failed publish must still close the targets that did subscribe.

    ``publish`` raises ``ReceiverUnavailableError`` once an unsubscribed target
    outlasts ``max_wait``.
    """
    received: list[Item] = []
    await _send_missing_target(received)
    assert received == [{"x": "foo", "i": 0}]


@pytest.mark.timeout(10)
@async_test
async def test_async_send_accepts_a_feed_source():
    """
    An async source reaches the parser as an ``AsyncIterator``, not a list.

    ``operator.aparse``/``setup`` hand the parser an async ``orig_stream`` when the
    caller passes a ``Feed``. So a sync ``for`` over it raises ``TypeError``.
    """
    consumed: list[int] = []
    received: list[Item] = []
    expected = [{"x": "foo", "i": i} for i in range(_SOURCE_LEN)]
    out = await _send_feed(consumed, received)

    assert out == expected
    assert received == expected


@pytest.mark.timeout(10)
@async_test
async def test_async_receive_does_not_materialize():
    """
    The zero-buffer rendezvous channel hands each published item to the
    subscriber before ``send`` pulls the next one. A subscriber observes its first
    item while the source is barely read. It never waits for the whole source to
    materialize. (The eager bound is on ``send``'s own passthrough return; see
    ``test_async_send_does_not_buffer_its_source``.)
    """
    consumed: list[int] = []
    first, seen = await _receive_first(consumed)

    assert first == {"x": "foo", "i": 0}
    assert seen <= _LOOKAHEAD
