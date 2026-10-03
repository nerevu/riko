# vim: sw=4:ts=4:expandtab
"""
Tripwires for the parts of the ``Pipeline`` surface that are declared but inert.

Each case is written against the authoring form it will have once the capability
lands and asserts the behavior its retired predecessor asserted, so the strict
xfail flips to a pass the moment the capability ships.
"""

from __future__ import annotations

from operator import itemgetter
from time import perf_counter
from typing import TYPE_CHECKING, cast

import pytest

from riko import Pipeline
from riko.types._guards import is_mapping, is_stateful_item
from riko.types.modules import (
    ItemBuilderConf,
    ParsedParam,
    StrconcatConf,
    StrReplaceConf,
    StrReplaceConfRule,
)

if TYPE_CHECKING:
    from riko.types._streams import Items

SRC = [{"content": "a"}, {"content": "b"}, {"content": "c"}]
VALUE = "once is 1x,twice is 2x,thrice is 3x"
BUILDER_CONF = ItemBuilderConf(
    {"attrs": ParsedParam({"key": "content", "value": VALUE})}
)
STRR_CONF = StrReplaceConf({"rule": StrReplaceConfRule(find="is", replace="was")})

EXPECTED = [
    {"content": "once is 1x"},
    {"content": "twice is 2x"},
    {"content": "thrice is 3x"},
]

EXECUTION_PENDING = pytest.mark.xfail(
    strict=True, reason="Pipeline.with_execution() does not configure concurrency yet"
)
PUBSUB_PENDING = pytest.mark.xfail(
    strict=True, reason="Pipeline.subscribe()/publish() are not available yet"
)
SPLIT_PENDING = pytest.mark.xfail(
    strict=True, reason="Pipeline.split() is not available yet"
)
CALLABLE_PENDING = pytest.mark.xfail(
    strict=True, reason="Pipeline.map() is not available yet"
)
PREDICATE_PENDING = pytest.mark.xfail(
    strict=True, reason="gating a node on a per-item predicate is not available yet"
)


def _tokenized() -> Pipeline:
    """Builds the three-item token stream both halves of this module publish."""
    source = Pipeline.from_module("itembuilder", conf=BUILDER_CONF)
    return source.tokenizer(options={"emit": True})


def _by_content(items):
    return sorted(items, key=itemgetter("content"))


@EXECUTION_PENDING
class TestExecutionSettings:
    """Run-wide settings: concurrency, ordering, and where per-item work runs."""

    def test_parallel_matches_sequential_as_multiset(self):
        pipeline = _tokenized().hash(options={"assign": "h"})
        sequential = list(pipeline)
        parallel = list(pipeline.with_execution(concurrency=4))
        assert len(parallel) == len(sequential) == 3
        assert _by_content(parallel) == _by_content(sequential)

    def test_ordered_preserves_source_order(self):
        pipeline = _tokenized().hash(options={"assign": "h"})
        sequential = list(pipeline)
        ordered = list(pipeline.with_execution(concurrency=4, ordered=True))
        assert ordered == sequential

    @pytest.mark.parametrize("executor", ["inline", "thread", "process"])
    def test_every_executor_produces_the_same_items(self, executor):
        pipeline = Pipeline(source=SRC).hash(options={"assign": "h"})
        assert list(pipeline.with_execution(executor=executor)) == list(pipeline)


@PUBSUB_PENDING
class TestSubscriptions:
    """Named local subscriptions fed by a publishing pipeline."""

    def test_published_items_interleave_with_the_sender(self):
        events = Pipeline.subscribe("receiver1")
        stream = iter(_tokenized().publish(events))
        received = iter(events)

        assert next(stream) == EXPECTED[0]
        assert next(received) == EXPECTED[0]
        assert next(stream) == EXPECTED[1]
        assert next(received) == EXPECTED[1]

    def test_every_subscription_receives_the_whole_batch_in_order(self):
        first = Pipeline.subscribe("receiver1")
        second = Pipeline.subscribe("receiver2")
        sender = _tokenized().publish(first).publish(second)

        assert list(sender) == EXPECTED
        assert list(first) == EXPECTED
        assert list(second) == EXPECTED

    def test_func_maps_each_received_item(self):
        changer = Pipeline.subscribe("changer", func=len)
        sender = _tokenized().publish(changer)

        assert list(sender) == EXPECTED
        assert list(changer) == [1, 1, 1]

    def test_two_publishers_reach_one_subscription(self):
        events = Pipeline.subscribe("shared")
        one = Pipeline(source=[{"content": "a"}]).hash().publish(events)
        two = Pipeline(source=[{"content": "b"}]).hash().publish(events)

        assert len(list(one)) == 1
        assert len(list(two)) == 1
        assert len(list(events)) == 2

    def test_an_undrained_subscription_does_not_block_the_publisher(self):
        events = Pipeline.subscribe("undrained")
        assert list(_tokenized().publish(events)) == EXPECTED

    def test_idle_drain_returns_promptly(self):
        started = perf_counter()
        assert list(Pipeline.subscribe("idle")) == []
        assert perf_counter() - started < 0.5

    def test_lifecycle_markers_do_not_leak_into_received_items(self):
        events = Pipeline.subscribe("leakcheck")
        list(_tokenized().publish(events))
        drained = cast("Items", list(events))

        assert drained == EXPECTED
        assert not any(is_stateful_item(item) for item in drained if is_mapping(item))


@SPLIT_PENDING
class TestSplit:
    """Streaming fan-out into independently consumable branches."""

    def test_both_branches_yield_the_same_first_item(self):
        left, right = _tokenized().split(2)
        assert next(iter(left)) == EXPECTED[0]
        assert next(iter(right)) == EXPECTED[0]

    def test_upstream_runs_once_for_every_branch(self):
        consumed: list[int] = []

        def source():
            for index in range(3):
                consumed.append(index)
                yield {"content": str(index)}

        left, right = (source() | Pipeline.from_module("hash")).split(2)
        assert list(left) == list(right)
        assert len(consumed) == 3


@CALLABLE_PENDING
class TestCallableNodes:
    """A plain callable chained as its own node."""

    def test_map_extracts_a_field(self):
        pipeline = _tokenized().map(itemgetter("content"))
        assert list(pipeline) == ["once is 1x", "twice is 2x", "thrice is 3x"]

    def test_map_runs_once_per_item_mid_chain(self):
        runs: list[int] = []

        def record(item):
            runs.append(1)
            return item

        pipeline = (
            _tokenized()
            .strreplace(conf=STRR_CONF, options={"assign": "content"})
            .slugify(options={"assign": "content"})
            .hash(options={"assign": "content"})
            .map(record)
        )
        assert next(iter(pipeline)) == {"content": 396558121}
        assert len(runs) == 1


@PREDICATE_PENDING
class TestConditionalNodes:
    """A node gated on a per-item predicate rather than applied to every item."""

    def test_a_gated_node_runs_only_for_matching_items(self):
        items = [{"kind": "hourly", "rate": "$1"}, {"kind": "fixed", "rate": "$1"}]
        part = [{"subkey": "rate", "type": "text"}, " / hr"]
        pipeline = Pipeline(source=items).strconcat(
            conf=StrconcatConf({"part": part}),
            options={"assign": "rate"},
            skip_if=lambda item: item.get("kind") != "hourly",
        )
        assert [item.get("rate") for item in pipeline] == ["$1 / hr", "$1"]
