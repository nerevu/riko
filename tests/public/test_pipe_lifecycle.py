# vim: sw=4:ts=4:expandtab
"""
Run lifetime for synchronous pipeline iteration.

A ``Pipeline`` is a definition, not a run: the lifetime belongs to the execution
that each iterator creates, so there is no pipeline-level state to inspect.
Iterating again starts a fresh execution, and closing an iterator tears that one
execution down without touching the definition.
"""

from __future__ import annotations

import pytest

from riko import Pipeline, parse_dag
from riko.base._paths import get_path
from riko.types._compiler import DagModule, PipeDag
from riko.types.modules import ConfArg, FetchRawConf, ItemBuilderConf

BUILDER_CONF = ItemBuilderConf({"attrs": [{"key": "content", "value": "a,b,c"}]})
SRC = [{"content": "x"}, {"content": "y"}]


def _tokenized() -> Pipeline:
    source = Pipeline.from_module("itembuilder", conf=BUILDER_CONF)
    return source.tokenizer(options={"emit": True})


def _fetch_node(index: int, url: str) -> DagModule:
    """Builds one fetch module entry for the fan-in dag."""
    conf = FetchRawConf({"url": ConfArg(type="url", value=url)})
    return DagModule(id=f"f{index}", type="fetch", conf=conf)


def _fanned_in(*urls: str) -> Pipeline:
    """Builds a pipeline whose single union node merges one fetch per url."""
    fetches = [_fetch_node(index, url) for index, url in enumerate(urls)]
    ports = ["in" if index == 0 else f"in:{index}" for index in range(len(urls))]
    wires = [[f"f{index}", "u", port] for index, port in enumerate(ports)]
    union = DagModule(id="u", type="union")
    dag = PipeDag(modules=[*fetches, union], wires=wires)
    return Pipeline(parse_dag(dag))


def _boom():
    raise RuntimeError("boom")
    yield  # pragma: no cover


class TestReiteration:
    def test_module_source_replays(self):
        pipeline = _tokenized()
        assert len(list(pipeline)) == 3
        assert len(list(pipeline)) == 3

    def test_replayable_source_replays(self):
        pipeline = Pipeline(source=SRC).hash()
        assert len(list(pipeline)) == 2
        assert len(list(pipeline)) == 2

    def test_one_shot_source_is_seen_consumed(self):
        pipeline = iter(SRC) | Pipeline.from_module("hash")
        assert len(list(pipeline)) == 2
        assert list(pipeline) == []

    def test_chaining_after_a_run_builds_a_fresh_run(self):
        pipeline = _tokenized()
        assert len(list(pipeline)) == 3
        assert list(pipeline.count()) == [{"count": 3}]


class TestClose:
    def test_close_before_the_first_item_never_runs_the_source(self):
        ran: list[int] = []

        def source():
            ran.append(1)
            yield {"content": "x"}

        stream = iter(source() | Pipeline.from_module("hash"))
        stream.close()
        assert list(stream) == []
        assert ran == []

    def test_close_is_idempotent(self):
        stream = iter(_tokenized())
        stream.close()
        stream.close()
        assert list(stream) == []

    def test_early_close_stops_a_partially_consumed_run(self):
        consumed: list[int] = []

        def source():
            for index in range(20):
                consumed.append(index)
                yield {"content": str(index)}

        stream = iter(source() | Pipeline.from_module("hash"))
        assert next(stream)
        stream.close()
        assert len(consumed) < 20

    def test_closing_one_iterator_leaves_the_definition_runnable(self):
        pipeline = _tokenized()
        stream = iter(pipeline)
        assert next(stream)
        stream.close()
        assert len(list(pipeline)) == 3


class TestFailure:
    def test_failing_source_propagates(self):
        pipeline = _boom() | Pipeline.from_module("hash")

        with pytest.raises(RuntimeError, match="boom"):
            list(pipeline)

    def test_a_fresh_iteration_starts_cleanly_after_a_failure(self):
        pipeline = _tokenized()

        with pytest.raises(RuntimeError, match="boom"):
            list(_boom() | Pipeline.from_module("hash"))

        assert len(list(pipeline)) == 3


class TestFanIn:
    def test_fan_in_merges_every_source(self):
        one = len(list(_fanned_in(get_path("feed.xml"))))
        both = len(list(_fanned_in(get_path("feed.xml"), get_path("feed.xml"))))
        assert one
        assert both == 2 * one

    def test_fan_in_replays(self):
        pipeline = _fanned_in(get_path("feed.xml"))
        assert len(list(pipeline)) == len(list(pipeline))

    def test_fan_in_close_before_iteration_produces_nothing(self):
        stream = iter(_fanned_in(get_path("feed.xml")))
        stream.close()
        assert list(stream) == []
