# vim: sw=4:ts=4:expandtab
"""
Tripwires for the parts of the ``Pipeline`` surface that are declared but inert.

Each case is written against the call form and behavior it will have once the
capability lands, so the strict xfail flips to a pass the moment the capability
ships. Most assert what their retired predecessor asserted; subscriptions are the
exception, because a subscription is observed through its ``func`` as items are
published rather than drained afterwards.
"""

from __future__ import annotations

from operator import itemgetter
from time import perf_counter
from typing import TYPE_CHECKING

import pytest

from riko.base.exceptions import InvalidPipelineError
from riko.modules._names import Transforms
from riko.runtime._pipeline import Pipeline
from riko.types._guards import is_stateful_item
from riko.types.modules import (
    ItemBuilderConf,
    ParsedParam,
    StrconcatConf,
    StrReplaceConf,
    StrReplaceConfRule,
)

if TYPE_CHECKING:
    from riko.types._streams import Item

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

PUBSUB_PENDING = pytest.mark.xfail(
    strict=True, reason="Pipeline.subscribe()/publish() are not available yet"
)
SPLIT_PENDING = pytest.mark.xfail(
    strict=True, reason="Pipeline.split() is not available yet"
)
CALLABLE_PENDING = pytest.mark.xfail(
    strict=True, reason="Pipeline.map() is not available yet"
)
SEED_PENDING = pytest.mark.xfail(
    strict=True,
    reason="an unseeded pipeline yields a placeholder item instead of raising",
)
PREDICATE_PENDING = pytest.mark.xfail(
    strict=True, reason="gating a node on a per-item predicate is not available yet"
)


def _tokenized() -> Pipeline:
    """Builds the three-item token stream both halves of this module publish."""
    source = Pipeline.from_module("itembuilder", conf=BUILDER_CONF)
    return source.tokenizer(options={"emit": True})


@PUBSUB_PENDING
class TestSubscriptions:
    """Named local subscriptions fed by a publishing pipeline."""

    def test_published_items_interleave_with_the_sender(self):
        seen: list[object] = []
        events = Pipeline.subscribe("receiver1", func=seen.append)
        stream = iter(_tokenized().publish(events))

        assert next(stream) == EXPECTED[0]
        assert seen == EXPECTED[:1]
        assert next(stream) == EXPECTED[1]
        assert seen == EXPECTED[:2]

    def test_every_subscription_receives_the_whole_batch_in_order(self):
        first_seen: list[object] = []
        second_seen: list[object] = []
        first = Pipeline.subscribe("receiver1", func=first_seen.append)
        second = Pipeline.subscribe("receiver2", func=second_seen.append)
        sender = _tokenized().publish(first).publish(second)

        assert list(sender) == EXPECTED
        assert first_seen == EXPECTED
        assert second_seen == EXPECTED

    def test_func_runs_per_item_and_items_pass_through(self):
        seen: list[object] = []
        archive = Pipeline.subscribe("archive", func=seen.append)
        sender = _tokenized().publish(archive)

        assert list(sender) == EXPECTED
        assert seen == EXPECTED

    def test_two_publishers_reach_one_subscription(self):
        seen: list[object] = []
        events = Pipeline.subscribe("shared", func=seen.append)
        one = Pipeline(source=[{"content": "a"}]).hash().publish(events)
        two = Pipeline(source=[{"content": "b"}]).hash().publish(events)

        assert len(list(one)) == 1
        assert len(list(two)) == 1
        assert len(seen) == 2

    def test_closing_the_publisher_keeps_what_it_delivered(self):
        seen: list[object] = []
        events = Pipeline.subscribe("abandoned", func=seen.append)
        stream = iter(Pipeline(source=[{"x": 0}, {"x": 1}]).publish(events))
        first = next(stream)
        stream.close()

        assert seen == [first]

    def test_an_undrained_subscription_does_not_block_the_publisher(self):
        events = Pipeline.subscribe("undrained")
        assert list(_tokenized().publish(events)) == EXPECTED

    def test_idle_drain_returns_promptly(self):
        started = perf_counter()
        assert list(Pipeline.subscribe("idle")) == []
        assert perf_counter() - started < 0.5

    def test_draining_after_publishing_starts_a_fresh_empty_run(self):
        events = Pipeline.subscribe("fresh")
        assert list(_tokenized().publish(events)) == EXPECTED
        assert list(events) == []

    def test_lifecycle_markers_do_not_leak_into_received_items(self):
        seen: list[Item] = []
        events = Pipeline.subscribe("leakcheck", func=seen.append)
        list(_tokenized().publish(events))

        assert seen == EXPECTED
        assert not any(is_stateful_item(item) for item in seen)


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


@SEED_PENDING
def test_an_unseeded_pipeline_requires_a_seed():
    pipeline = Pipeline.from_module(Transforms.REVERSE)

    with pytest.raises((InvalidPipelineError, TypeError), match="seed"):
        list(pipeline)
