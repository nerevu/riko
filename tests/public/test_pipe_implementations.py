# vim: sw=4:ts=4:expandtab
"""Tests pipe implementations."""

from __future__ import annotations

from itertools import count
from time import struct_time
from typing import TYPE_CHECKING, Any

import pytest

from riko import Pipeline
from riko.bado._backend import create_task_group
from riko.base.exceptions import ReceiverUnavailableError
from riko.modules.aggregate import pipe as aggregate_pipe
from riko.modules.filter import pipe as filter_pipe
from riko.modules.join import pipe as join_pipe
from riko.modules.receive import pipe as receive_pipe
from riko.modules.send import async_pipe as async_send
from riko.modules.send import pipe as send_pipe
from riko.modules.sort import pipe as sort_pipe
from riko.modules.udf import pipe as udf_pipe
from riko.runtime._pubsub import async_hub
from riko.types._enums import SortableCastType
from riko.types.modules import (
    FilterConf,
    FilterConfRule,
    JoinConf,
    SendConf,
    SortConf,
    SortConfRule,
)
from tests import async_test

if TYPE_CHECKING:
    from riko.types._streams import AsyncStream, Item, ItemOrValue, Stream


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
    An unparseable numeric field degrades to an orderable filler, not NaN.

    A missing field groups apart from it: first ascending, last descending,
    regardless of where either sat in the input.
    """
    rule = SortConfRule(field="n", dir=dir_, type=type_)
    conf = SortConf(rule=rule)

    if dir_ == "asc":
        expected = [None, "abc", *vals]
    else:
        expected = [*reversed(vals), "abc", None]

    mid = [{"n": vals[2]}, {"x": "abc"}, {"n": "abc"}, {"n": vals[0]}, {"n": vals[1]}]
    first = [{"n": "abc"}, {"x": "abc"}, {"n": vals[2]}, {"n": vals[0]}, {"n": vals[1]}]

    assert _values(sort_pipe(mid, conf=conf), "n") == expected
    assert _values(sort_pipe(first, conf=conf), "n") == expected


def test_sort_missing_field_is_not_the_cast_default():
    """A missing numeric field groups first instead of sorting as ``0``."""
    items = [{"n": "3"}, {"x": "no number"}, {"n": "-5"}]
    conf = SortConf(rule=SortConfRule(field="n", type=SortableCastType.INT))

    assert _values(sort_pipe(items, conf=conf), "n") == [None, "-5", "3"]


def test_sort_rule_default_sorts_missing_field_as_that_value():
    """A rule ``default`` stands in for the missing field and is cast like a value."""
    items = [{"n": "3"}, {"x": "no number"}, {"n": "-5"}]
    rule = SortConfRule(field="n", type=SortableCastType.INT, default="0")
    conf = SortConf(rule=rule)

    assert _values(sort_pipe(items, conf=conf), "n") == ["-5", None, "3"]


@pytest.mark.parametrize("dir_", ["asc", "desc"])
def test_untyped_sort_groups_items_lacking_the_field(dir_):
    """An untyped rule never compares a missing-field filler with real values."""
    early = struct_time((2012, 5, 11, 10, 1, 0, 4, 132, 1))
    late = struct_time((2014, 8, 27, 2, 2, 12, 2, 239, 0))
    items = [{"d": late}, {"x": "no date"}, {"d": None}, {"d": early}]
    conf = SortConf(rule=SortConfRule(field="d", dir=dir_))

    if dir_ == "asc":
        expected = [None, None, early, late]
    else:
        expected = [late, early, None, None]

    assert _values(sort_pipe(items, conf=conf), "d") == expected


def test_keyed_join_does_not_materialize_its_primary():
    """``other`` is the replayed side, so an unbounded primary must still emit."""
    consumed: list[int] = []
    other = [{"x": "bar", "c": 4}, {"x": "foo", "c": 5}]
    conf = JoinConf(join_key="x")
    joined = join_pipe(_counting_source(consumed), conf=conf, other=other)

    assert next(joined) == {"x": "foo", "i": 0, "c": 5}
    assert len(consumed) <= _LOOKAHEAD
    assert next(joined) == {"x": "foo", "i": 1, "c": 5}
    assert len(consumed) <= 1 + _LOOKAHEAD


def test_natural_join_does_not_materialize_its_primary():
    """The keyless natural join is lazy in its primary stream too."""
    consumed: list[int] = []
    joined = join_pipe(_counting_source(consumed), other=[{"c": 5}])

    assert next(joined) == {"x": "foo", "i": 0, "c": 5}
    assert len(consumed) <= _LOOKAHEAD


def test_filter_greater_less_compare_numeric_strings_numerically():
    """
    Compare numeric operands numerically and other operands lexically.

    Numeric strings such as ``"10"`` and ``"9"`` use numeric ordering; non-numeric
    strings use lexicographic ordering.
    """
    numeric_strings = [{"x": "9"}, {"x": "10"}]
    string_rule = FilterConfRule(field="x", op="greater", value="9")
    conf = FilterConf({"rule": string_rule})
    assert _values(filter_pipe(numeric_strings, conf=conf), "x") == ["10"]

    numbers = [{"x": 9}, {"x": 10}]
    numeric_rule = FilterConfRule(field="x", op="greater", value=9)
    conf = FilterConf({"rule": numeric_rule})
    assert _values(filter_pipe(numbers, conf=conf), "x") == [10]

    words = [{"x": "apple"}, {"x": "banana"}]
    word_rule = FilterConfRule(field="x", op="greater", value="apple")
    conf = FilterConf({"rule": word_rule})
    assert _values(filter_pipe(words, conf=conf), "x") == ["banana"]


def test_filter_ordered_coercion_is_all_or_nothing():
    """
    Fall back to lexical comparison when numeric coercion is incomplete.

    Mixed numeric/text pairs avoid ``Decimal``-versus-``str`` errors. Non-finite
    values such as ``inf`` and ``nan`` are also compared as strings.
    """
    mixed = [{"x": "10"}, {"x": "apple"}]
    conf = FilterConf({"rule": FilterConfRule(field="x", op="greater", value="banana")})
    assert _values(filter_pipe(mixed, conf=conf), "x") == []

    nonfinite = [{"x": "nan"}, {"x": "5"}]
    conf = FilterConf({"rule": FilterConfRule(field="x", op="greater", value="9")})
    assert _values(filter_pipe(nonfinite, conf=conf), "x") == ["nan"]


def test_filter_allow_inf_flag(monkeypatch):
    """Compare infinities numerically when ``ALLOW_INF`` is enabled."""
    items = [{"x": "-inf"}]
    conf = FilterConf({"rule": FilterConfRule(field="x", op="less", value="-5")})

    assert _values(filter_pipe(items, conf=conf), "x") == []

    monkeypatch.setattr("riko.modules.filter.ALLOW_INF", True)
    assert _values(filter_pipe(items, conf=conf), "x") == ["-inf"]

    nan_items = [{"x": "nan"}]
    nan_conf = FilterConf({"rule": FilterConfRule(field="x", op="greater", value="9")})
    assert _values(filter_pipe(nan_items, conf=nan_conf), "x") == ["nan"]


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
    """An omitted operand is a call-site error, so ``require_arg`` names it."""
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
    """An empty operand is a call-site error, so ``require_arg`` names it."""
    kwargs = {operand: value}

    with pytest.raises(TypeError, match=f"requires the {operand!r} keyword"):
        list(pipe([{"x": 0}], **kwargs))


def test_send_populates_ids_when_given():
    """The explicit ``ids`` parameter records each target's delivery id."""
    receiver = receive_pipe(conf={"name": "id-target", "wait": 0.01, "max_wait": 2})
    next(receiver)
    ids: dict[str, int] = {}
    list(send_pipe([{"x": 0}], others=["id-target"], ids=ids))
    assert isinstance(ids.get("id-target"), int)


@pytest.mark.xfail(
    strict=True, reason="Pipeline.subscribe()/publish() are not available yet"
)
def test_closing_a_publisher_completes_its_subscription():
    """A sender abandoned after one item still completes what it published."""
    events = Pipeline.subscribe("r")
    stream = iter(Pipeline(source=[{"x": 0}, {"x": 1}]).publish(events))
    first = next(stream)
    stream.close()
    assert list(events) == [first]


def _finite_source(consumed: list[int]) -> Stream:
    for i in range(_SOURCE_LEN):
        consumed.append(i)
        yield {"x": "foo", "i": i}


async def _afinite_source(consumed: list[int]) -> AsyncStream:
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
        stream = async_send(_finite_source(consumed), others=["r4-lazy"])
        first = await anext(stream)
        seen = len(consumed)

    return (first, seen)


async def _send_missing_target(received: list[Item]) -> None:
    async with (
        async_hub.subscribe("r4-good") as receive_stream,
        create_task_group() as tg,
    ):
        tg.start_soon(_drain, receive_stream, received)

        with pytest.raises(ReceiverUnavailableError):
            async for _ in async_send(
                _finite_source([]),
                conf=SendConf(max_wait=0.05),
                others=["r4-good", "r4-missing"],
            ):
                pass


async def _send_feed(consumed: list[int], received: list[Item]) -> list[ItemOrValue]:
    out: list[ItemOrValue] = []

    async with (
        async_hub.subscribe("r4-feed") as receive_stream,
        create_task_group() as tg,
    ):
        tg.start_soon(_drain, receive_stream, received)
        stream = async_send(_afinite_source(consumed), others=["r4-feed"])
        out = [item async for item in stream]

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
        async for _ in async_send(_finite_source(consumed), others=["r-recv-lazy"]):
            pass

    return (first, seen)


@pytest.mark.timeout(10)
@pytest.mark.xfail(reason="lazy async fan-out is not yet implemented", strict=True)
@async_test
async def test_async_send_does_not_buffer_its_source():
    """Keep unbounded async sends from returning before completion."""
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
    Deliver each item before pulling the next one from the source.

    The zero-buffer channel lets subscribers observe items without materializing the
    source. ``send`` still eagerly collects its own passthrough return; see
    ``test_async_send_does_not_buffer_its_source``.
    """
    consumed: list[int] = []
    first, seen = await _receive_first(consumed)

    assert first == {"x": "foo", "i": 0}
    assert seen <= _LOOKAHEAD
