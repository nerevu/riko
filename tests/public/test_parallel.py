# vim: sw=4:ts=4:expandtab
"""
Bounded-parallelism tripwires for asynchronous pipeline iteration.

A pipeline carrying concurrency settings maps a loopable node over its source with
bounded concurrency and backpressure: results arrive as they complete unless
``ordered=True`` preserves source order, and the source advances only as workers
free up, so it is never pre-materialized. A fan-in graph should pull its upstream
branches concurrently under the same ceiling; that is not available yet.

The primitives' precise ``limit + buffer`` bound is covered in
``tests/internal/test_streams.py``. Here we assert the *pipeline-level* contract:
same results as sequential, order control, and non-materialization.
"""

from typing import TYPE_CHECKING, cast

import pytest

from riko import Pipeline
from riko.bado._backend import async_sleep
from riko.definitions._workflow import ModuleNode, StreamEdge, Workflow
from riko.ext.registry import ModuleDefinition, register_module, reset_module_registry
from riko.types._guards import is_mapping
from riko.types._workflow import Endpoint
from riko.types.modules import ItemBuilderConf
from tests import skipif_issync

if TYPE_CHECKING:
    from riko.types._wrappers import AsyncModuleWrapper

pytestmark = pytest.mark.slow

BUILDER_CONF = ItemBuilderConf({"attrs": {"key": "content", "value": "a,bb,ccc,dddd"}})
BRANCHES = ("fanin_branch_a", "fanin_branch_b", "fanin_branch_c")

FANIN_PENDING = pytest.mark.xfail(
    strict=True,
    reason=(
        "concurrent pulling of fan-in branches is not available yet; a fan-in "
        "pulls its sources one at a time"
    ),
)


def _by_content(items):
    return sorted(items, key=lambda item: item["content"])


def _tokenized() -> Pipeline:
    source = Pipeline.from_module("itembuilder", conf=BUILDER_CONF)
    return source.tokenizer(options={"emit": True}).hash(options={"assign": "h"})


def _fanned_in(names: tuple[str, ...]) -> Pipeline:
    """Builds a pipeline whose single union node merges one branch per name."""
    branches = [
        ModuleNode(id=f"b{index}", name=name) for index, name in enumerate(names)
    ]
    union = ModuleNode(id="u", name="union")
    ports = ["in" if index == 0 else f"in:{index}" for index in range(len(names))]
    edges = tuple(
        StreamEdge(Endpoint(branch.id, "out"), Endpoint(union.id, port))
        for branch, port in zip(branches, ports, strict=True)
    )
    workflow = Workflow(
        nodes={node.id: node for node in [*branches, union]},
        edges=edges,
        outputs={"default": Endpoint(union.id, "out")},
        inputs={},
    )
    return Pipeline(workflow)


@pytest.fixture
def branch_log():
    """Registers slow async branch sources that log when each starts and ends."""
    log: list[tuple[str, str]] = []

    def build_branch(name: str):
        async def branch(_items=None, **_):
            log.append(("start", name))
            await async_sleep(0.05)
            yield {"content": name}
            log.append(("end", name))

        return branch

    reset_module_registry()

    for name in BRANCHES:
        async_pipe = cast("AsyncModuleWrapper", build_branch(name))
        register_module(ModuleDefinition(name=name, async_pipe=async_pipe))

    try:
        yield log
    finally:
        reset_module_registry()


@skipif_issync
class TestAsyncBoundedParallel:
    @pytest.mark.anyio
    async def test_parallel_matches_sequential_as_multiset(self):
        pipeline = _tokenized()
        sequential = [item async for item in pipeline]
        parallel = [item async for item in pipeline.with_execution(concurrency=4)]
        assert len(parallel) == len(sequential) == 4
        assert _by_content(parallel) == _by_content(sequential)

    @pytest.mark.anyio
    async def test_ordered_parallel_preserves_order(self):
        pipeline = _tokenized()
        sequential = [item async for item in pipeline]
        ordered = pipeline.with_execution(concurrency=4, ordered=True)
        assert [item async for item in ordered] == sequential

    @pytest.mark.parametrize("ordered", [False, True])
    @pytest.mark.anyio
    async def test_bounded_source_is_not_fully_drained(self, ordered):
        consumed: list[int] = []

        async def tracking():
            for index in range(20):
                consumed.append(index)
                yield {"content": str(index)}

        pipeline = (tracking() | Pipeline.from_module("hash")).with_execution(
            concurrency=2, ordered=ordered
        )
        stream = aiter(pipeline)
        first = await anext(stream)
        await stream.aclose()
        assert is_mapping(first)
        assert first.get("content") in {str(index) for index in range(20)}
        assert len(consumed) < 20

    @pytest.mark.parametrize("ordered", [False, True])
    @pytest.mark.anyio
    async def test_early_close_is_clean(self, ordered):
        """Ensure early closure tears down a bounded pipeline cleanly."""

        async def unbounded():
            index = 0

            while True:
                yield {"content": str(index)}
                index += 1

        pipeline = (unbounded() | Pipeline.from_module("hash")).with_execution(
            concurrency=2, ordered=ordered
        )
        stream = aiter(pipeline)
        first = await anext(stream)
        await stream.aclose()
        assert is_mapping(first)
        assert first.get("content")


@skipif_issync
class TestAsyncFanInParallel:
    @pytest.mark.parametrize("ordered", [False, True])
    @pytest.mark.anyio
    async def test_fan_in_yields_every_branch(self, branch_log, ordered):
        pipeline = _fanned_in(BRANCHES[:2]).with_execution(
            concurrency=2, ordered=ordered
        )
        items = [item async for item in pipeline]
        assert sorted(item["content"] for item in items) == sorted(BRANCHES[:2])

    @FANIN_PENDING
    @pytest.mark.parametrize("ordered", [False, True])
    @pytest.mark.anyio
    async def test_branches_are_pulled_concurrently(self, branch_log, ordered):
        pipeline = _fanned_in(BRANCHES[:2]).with_execution(
            concurrency=2, ordered=ordered
        )
        assert len([item async for item in pipeline]) == 2
        assert [event for event, _ in branch_log[:2]] == ["start", "start"]

    @FANIN_PENDING
    @pytest.mark.anyio
    async def test_more_branches_than_limit_stay_bounded(self, branch_log):
        pipeline = _fanned_in(BRANCHES).with_execution(concurrency=2)
        assert len([item async for item in pipeline]) == 3
        active, peak = 0, 0

        for event, _ in branch_log:
            active += 1 if event == "start" else -1
            peak = max(peak, active)

        assert peak == 2
