# vim: sw=4:ts=4:expandtab
"""Provides public tests for building, running, and writing a ``Pipeline``."""

from __future__ import annotations

import gc
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from operator import itemgetter, methodcaller
from pickle import dumps, loads  # noqa: S403
from time import perf_counter
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    NoReturn,
    assert_type,
    cast,
    get_args,
    get_origin,
)

import pytest

from riko import export
from riko.bado._backend import async_sleep, checkpoint, fail_after
from riko.bado.itertools import alist, async_iter
from riko.base._paths import ROOT_DIR, get_path
from riko.base.exceptions import (
    EmptyPipelineError,
    InvalidPipelineError,
    PipelineError,
    UnsupportedTargetError,
)
from riko.definitions._context import Context, ExecutionMode
from riko.definitions._nodes import CallableNode, ModuleNode, StreamEdge, WriteNode
from riko.definitions._settings import DEF_EXECUTION_SETTINGS
from riko.definitions._workflow_definition import Workflow
from riko.definitions._write import WriteCapabilities, WriteMode
from riko.ext import ModuleDefinition, normalize_module_name
from riko.modules._names import Transforms
from riko.modules.write import async_pipe, pipe
from riko.parsing._dotdict import DotDict
from riko.runtime._module_registry import register_module, reset_module_registry
from riko.runtime._pipeline import Pipeline
from riko.types._enums import Backends, Executor, Formats, IdentityMode, ModuleName
from riko.types._guards import is_mapping, is_stateful_item
from riko.types._workflow import Endpoint
from riko.types.modules import (
    CallOptions,
    ConfArg,
    Embed,
    ItemBuilderConf,
    ParsedParam,
    SortConf,
    SortConfRule,
    StrconcatConf,
    StrReplaceConf,
    StrReplaceConfRule,
    TokenizerConf,
    TokenizerRawConf,
    WriteConf,
)
from tests import aresolve, async_test, skipif_issync
from tests._execution import agen_source, awaitable_source, module_workflow
from tests._lifecycle import LIFECYCLE_SRC, boom, fanned_in_fetches, tokenized_letters

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Iterable, Iterator, Mapping

    from riko.types._streams import Item, Items
    from riko.types._wrappers import AsyncModuleWrapper, SyncModuleWrapper

WRITE_NODE_PENDING = pytest.mark.xfail(
    strict=True, reason="write nodes do not execute yet"
)

SRC = [{"content": "a"}, {"content": "b"}, {"content": "c"}]
VALUE = "once is 1x,twice is 2x,thrice is 3x"
BUILDER_CONF = ItemBuilderConf(
    {"attrs": ParsedParam({"key": "content", "value": VALUE})}
)

EXPECTED = [
    {"content": "once is 1x"},
    {"content": "twice is 2x"},
    {"content": "thrice is 3x"},
]

ITEMS = [{"x": 0}, {"x": 1}, {"x": 2}]

FANIN_PENDING = pytest.mark.xfail(
    strict=True,
    reason=(
        "concurrent pulling of fan-in branches is not available yet; a fan-in "
        "pulls its sources one at a time"
    ),
)
PUBSUB_PENDING = pytest.mark.xfail(
    strict=True, reason="Pipeline.subscribe()/publish() are not available yet"
)
SPLIT_PENDING = pytest.mark.xfail(
    strict=True, reason="Pipeline.split() is not available yet"
)
SEED_PENDING = pytest.mark.xfail(
    strict=True,
    reason="an unseeded pipeline yields a placeholder item instead of raising",
)
PREDICATE_PENDING = pytest.mark.xfail(
    strict=True, reason="gating a node on a per-item predicate is not available yet"
)


def _tokenized() -> Pipeline:
    """Builds a three-item token stream."""
    source = Pipeline.from_module("itembuilder", conf=BUILDER_CONF)
    return source.tokenizer(options={"emit": True})


def _by_content(items):
    return sorted(items, key=itemgetter("content"))


def _workflow() -> Workflow:
    node = Pipeline.from_module("fetch").workflow.nodes["fetch-1"]
    return Workflow(
        nodes=[node], outputs={"default": Endpoint(node.id, "out")}, inputs={}
    )


class TestPipelineConstruction:
    def test_module_seed_builds_single_node_workflow(self):
        pipeline = Pipeline.from_module("fetch")
        assert sorted(pipeline.workflow.nodes) == ["fetch-1"]
        assert pipeline.workflow.outputs["default"] == Endpoint("fetch-1", "out")
        assert pipeline.workflow.edges == ()
        assert pipeline.workflow.isvalid
        assert pipeline.source is None

    def test_pipeline_repr_notes_seed_and_context(self):
        fetch = Pipeline.from_module("fetch")
        assert repr(fetch) == "Pipeline(fetch-1; outputs: default)"
        seeded = Pipeline(source=[{"x": 1}], context=Context())
        assert repr(seeded) == "Pipeline(empty; seed; context)"

    def test_workflow_constructor_keeps_the_workflow(self):
        flow = _workflow()
        assert Pipeline(flow).workflow is flow

    def test_empty_seed_builds_template(self):
        pipeline = Pipeline()
        assert dict(pipeline.workflow.nodes) == {}
        assert pipeline.source is None
        assert not pipeline.workflow.isvalid

    def test_items_seed_builds_template(self):
        items = [{"x": 1}]
        pipeline = Pipeline(source=items)
        assert dict(pipeline.workflow.nodes) == {}
        assert pipeline.source is items
        assert not pipeline.workflow.isvalid

    def test_pipeline_is_generic_over_item_type(self):
        alias = Pipeline[int]

        assert get_origin(alias) is Pipeline
        assert get_args(alias) == (int,)

    @pytest.mark.parametrize(
        "make",
        [
            pytest.param(lambda: Pipeline([{"x": 1}]), id="items"),  # pyright: ignore[reportArgumentType]
            pytest.param(lambda: Pipeline("fetch"), id="module-name"),  # pyright: ignore[reportArgumentType]
            pytest.param(lambda: Pipeline(Pipeline.from_module("sort")), id="pipeline"),  # pyright: ignore[reportArgumentType]
        ],
    )
    def test_non_workflow_positional_rejected(self, make):
        with pytest.raises(TypeError):
            make()


_SORT_CONF_RULE = SortConfRule(dir="desc")
_SORT_CONF = SortConf({"rule": _SORT_CONF_RULE})
_OPTIONS = CallOptions(emit=True, field="title")

tokenizer_conf = TokenizerRawConf(delimiter=ConfArg(type="text", value=" "))
_EMBED = Embed(name="tokenizer", conf=tokenizer_conf)


def _assert_embed(node):
    """Confirms a node carries the tokenizer embed and its typed configuration."""
    assert isinstance(node, ModuleNode)
    assert node.embed is not None
    assert node.embed["name"] == "tokenizer"
    assert dict(node.embed["conf"]) == {"delimiter": {"type": "text", "value": " "}}
    assert node.options == _OPTIONS


class TestPipelineChaining:
    def test_pipe_appends_node_and_edge(self):
        p1 = Pipeline.from_module("fetch")
        p2 = p1.pipe("sort", conf=_SORT_CONF)

        assert sorted(p2.workflow.nodes) == ["fetch-1", "sort-1"]
        assert p2.workflow.outputs["default"] == Endpoint("sort-1", "out")
        expected = StreamEdge(Endpoint("fetch-1", "out"), Endpoint("sort-1", "in"))
        assert p2.workflow.edges == (expected,)
        p2.workflow.validate()

    def test_pipe_leaves_prior_pipeline_unchanged(self):
        p1 = Pipeline.from_module("fetch")
        p2 = p1.pipe("sort")

        assert sorted(p1.workflow.nodes) == ["fetch-1"]
        assert p1.workflow.outputs["default"] == Endpoint("fetch-1", "out")
        assert p2 is not p1

    def test_pipe_skips_an_id_another_module_holds(self):
        node = ModuleNode(id="sort-1", name="reverse")
        flow = Workflow(nodes=[node], outputs={"default": Endpoint("sort-1", "out")})
        pipeline = Pipeline(flow).pipe("sort")
        assert pipeline.workflow.nodes["sort-2"].name == "sort"

    def test_pipe_shares_prior_node_identity(self):
        p1 = Pipeline.from_module("fetch")
        p2 = p1.pipe("sort")
        assert p2.workflow.nodes["fetch-1"] is p1.workflow.nodes["fetch-1"]

    def test_getattr_chains_filter(self):
        pipeline = Pipeline.from_module("fetch").filter(conf={"rule": []})
        assert pipeline.workflow.nodes["filter-1"].name == "filter"

    def test_or_chains_name_conf_pair(self):
        pipeline = Pipeline.from_module("fetch") | ("sort", _SORT_CONF)
        node = pipeline.workflow.nodes["sort-1"]
        assert isinstance(node, ModuleNode)
        node_conf_rule = node.conf.get("rule")
        assert is_mapping(node_conf_rule)
        assert dict(node_conf_rule) == asdict(_SORT_CONF_RULE)

    def test_chained_loop_carries_its_embed_and_options(self):
        pipeline = Pipeline.from_module("itembuilder").loop(
            embed=_EMBED, options=_OPTIONS
        )
        node = pipeline.workflow.nodes["loop-1"]
        _assert_embed(node)
        assert isinstance(node, ModuleNode)
        assert node.conf == {}

    def test_or_copies_a_loop_template_embed_and_options(self):
        template = Pipeline.from_module("loop", embed=_EMBED, options=_OPTIONS)
        pipeline = Pipeline.from_module("itembuilder") | template
        _assert_embed(pipeline.workflow.nodes["loop-1"])

    def test_or_chains_single_module_template(self):
        pipeline = Pipeline.from_module("fetch") | Pipeline.from_module("sort")
        assert sorted(pipeline.workflow.nodes) == ["fetch-1", "sort-1"]

    def test_or_keeps_a_module_template_resources_and_label(self):
        node = ModuleNode(id="hash-1", name="hash", resources="db", label="L")
        template = Pipeline(Workflow().with_node(node))
        pipeline = Pipeline.from_module("fetch") | template
        chained = pipeline.workflow.nodes["hash-1"]
        assert (dict(chained.resources), chained.label) == ({"db": "db"}, "L")
        assert pipeline.workflow.resources == ("db",)

    def test_or_string_matches_attribute_chaining(self):
        via_or = list(Pipeline(source=SRC) | "hash")
        via_attr = list(Pipeline(source=SRC).hash())
        assert via_or == via_attr
        assert len(via_or) == 3

    def test_ror_preserves_definitional_conf_and_options(self):
        conf = TokenizerConf({"delimiter": " "})
        template = Pipeline.from_module("tokenizer", conf=conf, options={"emit": False})
        primed = SRC | template
        node = primed.workflow.nodes["tokenizer-1"]
        assert isinstance(node, ModuleNode)
        assert primed.source is SRC
        assert dict(node.conf) == conf
        assert node.options.kwargs == {"emit": False}

    def test_ror_seeds_async_stream(self):
        async def stream():
            yield {"x": 1}

        source = stream()
        pipeline = source | Pipeline.from_module("sort")
        assert pipeline.source is source

    def test_duplicate_names_mint_unique_ids(self):
        pipeline = Pipeline.from_module("sort").pipe("sort")
        assert sorted(pipeline.workflow.nodes) == ["sort-1", "sort-2"]

    @pytest.mark.parametrize(
        "name", ["_hidden", "keys", "values", "items", "get", "close", "sortt"]
    )
    def test_getattr_rejects_non_builtin_names(self, name):
        with pytest.raises(AttributeError):
            getattr(Pipeline.from_module("fetch"), name)

    def test_or_rejects_multi_node_template(self):
        template = Pipeline.from_module("a").pipe("b")
        with pytest.raises(InvalidPipelineError):
            _ = Pipeline.from_module("fetch") | template

    def test_or_rejects_unsupported_operand(self):
        with pytest.raises(TypeError):
            _ = Pipeline.from_module("fetch") | 3

    def test_ror_rejects_reseeding(self):
        with pytest.raises(TypeError):
            _ = [{"x": 1}] | Pipeline(source=[{"y": 1}])


class _Mod(ModuleName):
    HASH = "hash"
    TRUNCATE = "truncate"


class TestModuleNameEnum:
    """A ``ModuleName`` enum is accepted anywhere a name string is."""

    def test_resolve_module_name(self):
        assert normalize_module_name(_Mod.HASH) == "hash"
        assert normalize_module_name("hash") == "hash"
        assert normalize_module_name(None) == ""

    def test_seed_stores_plain_string(self):
        node = Pipeline.from_module(_Mod.HASH).workflow.nodes["hash-1"]
        assert node.name == "hash"
        assert type(node.name) is str

    def test_enum_through_operator(self):
        pipeline = Pipeline(source=SRC) | _Mod.HASH
        assert pipeline.workflow.nodes["hash-1"].name == "hash"
        assert len(list(pipeline)) == 3

    def test_enum_through_method(self):
        pipeline = Pipeline(source=SRC).pipe(_Mod.TRUNCATE, conf={"count": 1})
        assert pipeline.workflow.nodes["truncate-1"].name == "truncate"
        assert len(list(pipeline)) == 1


class TestPipelineIteration:
    def test_iterating_a_source_only_pipeline_streams_the_source(self):
        assert list(Pipeline(source=[{"x": 1}, {"x": 2}])) == [{"x": 1}, {"x": 2}]
        assert list(Pipeline(source={"x": 1})) == [{"x": 1}]

    def test_a_dotted_assignment_leaves_the_source_untouched(self):
        source: Items = [{"a": {"b": "hi"}}]
        options = CallOptions(field="a.b", assign="a.c")
        conf = {"rule": {"transform": "upper"}}
        pipeline = Pipeline(source=source).strtransform(conf=conf, options=options)
        assert list(pipeline) == [{"a": {"b": "hi", "c": "HI"}}]
        assert source == [{"a": {"b": "hi"}}]

    def test_a_source_seed_runs_through_a_registered_module(self) -> None:
        def double(source, **_):
            return ({"x": item["x"] * 2} for item in source)

        reset_module_registry()
        sync_pipe = cast("SyncModuleWrapper", double)
        register_module(ModuleDefinition(name="doubler", sync_pipe=sync_pipe))

        try:
            expected = [{"x": 2}, {"x": 4}]
            assert (
                list([{"x": 1}, {"x": 2}] | Pipeline.from_module("doubler")) == expected
            )
            assert list(Pipeline(source=[{"x": 10}]).pipe("doubler")) == [{"x": 20}]
        finally:
            reset_module_registry()

    def test_first_returns_the_default_on_an_empty_pipeline(self):
        assert Pipeline(source=[]).first(default=None) is None
        assert Pipeline(source=[]).first(default={"x": 0}) == {"x": 0}
        assert Pipeline(source=[{"x": 1}]).first(default=None) == {"x": 1}

    def test_first_on_an_empty_pipeline_raises_a_lookup_error(self):
        with pytest.raises(EmptyPipelineError, match="no items") as info:
            Pipeline(source=[]).first()

        assert isinstance(info.value, PipelineError)
        assert isinstance(info.value, LookupError)

    def test_first_does_not_leak_stop_iteration_into_an_outer_iterator(self):
        pipelines = [Pipeline(source=[{"x": 1}]), Pipeline(source=[])]

        with pytest.raises(EmptyPipelineError):
            list(map(Pipeline.first, pipelines))

    def test_iterating_an_empty_pipeline_raises(self):
        with pytest.raises(InvalidPipelineError, match="no nodes"):
            list(Pipeline())

    def test_iterating_a_split_pipeline_raises_before_running(self):
        consumed = []

        def source():
            consumed.append(1)
            yield {"x": 1}

        with pytest.raises(InvalidPipelineError, match="splitter"):
            list(source() | Pipeline.from_module("split"))

        assert consumed == []


class TestAsyncPipelineIteration:
    @async_test
    async def test_async_iterating_a_source_only_pipeline_streams_the_source(self):
        async def source():
            yield {"x": 1}

        assert [item async for item in Pipeline(source=source())] == [{"x": 1}]

    @pytest.mark.parametrize(
        "make_seed",
        [
            pytest.param(lambda: [{"x": 1}, {"x": 2}], id="sync-iterable"),
            pytest.param(agen_source, id="async-iterable"),
            pytest.param(awaitable_source, id="awaitable"),
        ],
    )
    @async_test
    async def test_a_seed_runs_through_a_registered_async_module(self, make_seed):
        async def adouble(source, **_):
            async for item in source:
                yield {"x": item["x"] * 2}

        reset_module_registry()
        async_pipe = cast("AsyncModuleWrapper", adouble)
        register_module(ModuleDefinition(name="adoubler", async_pipe=async_pipe))

        try:
            pipeline = make_seed() | Pipeline.from_module("adoubler")
            assert [item async for item in pipeline] == [{"x": 2}, {"x": 4}]
        finally:
            reset_module_registry()

    @async_test
    async def test_afirst_on_an_empty_pipeline_raises_a_lookup_error(self):
        with pytest.raises(EmptyPipelineError):
            await Pipeline(source=[]).afirst()

        assert await Pipeline(source=[]).afirst(default=None) is None
        assert await Pipeline(source=[{"x": 1}]).afirst() == {"x": 1}

    @async_test
    async def test_async_iterating_a_split_pipeline_raises_before_running(self):
        consumed = []

        def source():
            consumed.append(1)
            yield {"x": 1}

        with pytest.raises(InvalidPipelineError, match="splitter"):
            _ = [item async for item in source() | Pipeline.from_module("split")]

        assert consumed == []


_PARITY_BUILDER_CONF = ItemBuilderConf(
    {"attrs": {"key": "content", "value": "a,bb,ccc"}}
)
_PARITY_STRR_CONF = StrReplaceConf({"rule": StrReplaceConfRule(find="c", replace="C")})


def _parity_tokens() -> Pipeline:
    source = Pipeline.from_module("itembuilder", conf=_PARITY_BUILDER_CONF)
    return source.tokenizer(options={"emit": True})


def _both(build: Callable[[Pipeline], Pipeline]) -> tuple[Items, Items]:
    """Iterate *build*'s pipeline both ways; return ``(sync_result, async_result)``."""
    pipeline = build(_parity_tokens())
    return list(pipeline), aresolve(pipeline)


_A, _BB, _CCC = {"content": "a"}, {"content": "bb"}, {"content": "ccc"}
_STRR_ASSIGN = methodcaller(
    "strreplace", conf=_PARITY_STRR_CONF, options={"assign": "content"}
)
_ASSIGNED = [_A, _BB, {"content": "CCC"}]
_SMOKE = pytest.mark.smoke
PARITY_CASES = [
    pytest.param(methodcaller("count"), [{"count": 3}], id="count", marks=_SMOKE),
    pytest.param(_STRR_ASSIGN, _ASSIGNED, id="strreplace-assign", marks=_SMOKE),
    pytest.param(methodcaller("reverse"), [_CCC, _BB, _A], id="reverse"),
    pytest.param(methodcaller("tail", conf={"count": 1}), [_CCC], id="tail"),
    pytest.param(methodcaller("truncate", conf={"count": 2}), [_A, _BB], id="truncate"),
]


@skipif_issync
class TestOutputParity:
    @pytest.mark.parametrize(("build", "expected"), PARITY_CASES)
    def test_sync_matches_async(self, build: methodcaller, expected: Items):
        sync_result, async_result = _both(build)
        assert sync_result == async_result == expected

    def test_assignment_preserves_parent(self):
        build = lambda pipeline: pipeline.hash(options={"assign": "h"})
        sync_result, async_result = _both(build)
        expected = ["a", "bb", "ccc"]
        assert sync_result == async_result
        assert [
            item.get("content") for item in sync_result if is_mapping(item)
        ] == expected
        assert all("h" in item for item in sync_result if is_mapping(item))


class TestReiteration:
    def test_module_source_replays(self):
        pipeline = tokenized_letters()
        assert len(list(pipeline)) == 3
        assert len(list(pipeline)) == 3

    def test_one_shot_source_is_seen_consumed(self):
        pipeline = iter(LIFECYCLE_SRC) | Pipeline.from_module("hash")
        assert len(list(pipeline)) == 2
        assert list(pipeline) == []

    def test_chaining_after_a_run_builds_a_fresh_run(self):
        pipeline = tokenized_letters()
        assert len(list(pipeline)) == 3
        assert list(pipeline.count()) == [{"count": 3}]


class TestAsyncReiteration:
    @async_test
    async def test_module_source_replays(self):
        pipeline = tokenized_letters()
        assert len([item async for item in pipeline]) == 3
        assert len([item async for item in pipeline]) == 3

    @async_test
    async def test_one_shot_source_is_seen_consumed(self):
        pipeline = iter(LIFECYCLE_SRC) | Pipeline.from_module("hash")
        assert len([item async for item in pipeline]) == len(LIFECYCLE_SRC)
        assert [item async for item in pipeline] == []

    @async_test
    async def test_iteration_after_partial_iteration_restarts(self):
        pipeline = tokenized_letters()
        stream = aiter(pipeline)
        assert await anext(stream) == {"content": "a"}
        await stream.aclose()
        assert len([item async for item in pipeline]) == 3


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
        stream = iter(tokenized_letters())
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
        pipeline = tokenized_letters()
        stream = iter(pipeline)
        assert next(stream)
        stream.close()
        assert len(list(pipeline)) == 3

    def test_early_close_closes_an_upstream_module(self) -> None:
        closed: list[bool] = []

        def src(_items=None, **_):
            try:
                yield {"x": 1}
                yield {"x": 2}
            finally:
                closed.append(True)

        reset_module_registry()
        sync_pipe = cast("SyncModuleWrapper", src)
        register_module(ModuleDefinition(name="itersrc2", sync_pipe=sync_pipe))

        try:
            iterator = iter(Pipeline(module_workflow("itersrc2")))
            assert next(iterator) == {"x": 1}
            iterator.close()
            assert closed == [True]
        finally:
            reset_module_registry()


class TestAsyncClose:
    @async_test
    async def test_close_before_the_first_item_never_runs_the_source(self):
        ran: list[int] = []

        async def source():
            ran.append(1)
            yield {"content": "x"}

        stream = aiter(source() | Pipeline.from_module("hash"))
        await stream.aclose()
        assert [item async for item in stream] == []
        assert ran == []

    @async_test
    async def test_close_is_idempotent(self):
        stream = aiter(tokenized_letters())
        await stream.aclose()
        await stream.aclose()
        assert [item async for item in stream] == []

    @async_test
    async def test_early_close_stops_a_partially_consumed_run(self):
        consumed: list[int] = []
        closed: list[bool] = []

        async def source():
            try:
                for index in range(20):
                    consumed.append(index)
                    yield {"content": str(index)}
            finally:
                closed.append(True)

        stream = aiter(source() | Pipeline.from_module("hash"))
        assert await anext(stream)
        await stream.aclose()
        assert len(consumed) < 20
        assert closed == [True]

    @async_test
    async def test_afirst_closes_its_run_before_returning(self):
        consumed: list[int] = []

        async def source():
            for index in range(20):
                consumed.append(index)
                yield {"content": str(index)}

        with fail_after(5):
            hashed = Pipeline[dict[str, object]].from_module("hash")
            first = await (source() | hashed).afirst()
            gc.collect()
            await checkpoint()

        assert first["content"] == "0"
        assert len(consumed) < 20

    @async_test
    async def test_bare_break_leaves_the_callers_cancel_scope_intact(self):
        source = [{"content": str(index)} for index in range(5)]

        with fail_after(5):
            async for _ in source | Pipeline.from_module("hash"):
                break

            gc.collect()

            for _ in range(5):
                await checkpoint()


class TestFailure:
    def test_failing_source_propagates(self):
        pipeline = boom() | Pipeline.from_module("hash")

        with pytest.raises(RuntimeError, match="boom"):
            list(pipeline)

    def test_a_failing_pipeline_does_not_break_another_pipelines_run(self):
        pipeline = tokenized_letters()

        with pytest.raises(RuntimeError, match="boom"):
            list(boom() | Pipeline.from_module("hash"))

        assert len(list(pipeline)) == 3


async def _coro_source():
    return list(LIFECYCLE_SRC)


async def _raising_coro_source():
    raise RuntimeError("boom")


GOOD_SOURCES = [
    pytest.param(lambda: list(LIFECYCLE_SRC), id="sync-iterable"),
    pytest.param(lambda: async_iter(LIFECYCLE_SRC), id="async-iterable"),
    pytest.param(_coro_source, id="awaitable"),
]

RAISING_SOURCES = [
    pytest.param(boom, id="sync-iterable"),
    pytest.param(lambda: async_iter(boom()), id="async-iterable"),
    pytest.param(_raising_coro_source, id="awaitable"),
]


class TestAsyncSourceAdapter:
    """Every source kind an asynchronous execution accepts."""

    @pytest.mark.parametrize("make_source", GOOD_SOURCES)
    @async_test
    async def test_source_iterates_and_closes(self, make_source):
        pipeline = make_source() | Pipeline.from_module("hash")
        stream = aiter(pipeline)
        items = [item async for item in stream]
        await stream.aclose()
        assert len(items) == len(LIFECYCLE_SRC)

    @pytest.mark.parametrize("make_source", RAISING_SOURCES)
    @async_test
    async def test_source_failure_propagates(self, make_source):
        pipeline = make_source() | Pipeline.from_module("hash")

        with pytest.raises(RuntimeError, match="boom"):
            _ = [item async for item in pipeline]


class TestAlist:
    @async_test
    async def test_collects_a_sync_source(self):
        assert await alist([1, 2]) == [1, 2]


class TestFanIn:
    @pytest.mark.smoke
    def test_fan_in_merges_every_source(self):
        one = len(list(fanned_in_fetches(get_path("feed.xml"))))
        both = len(list(fanned_in_fetches(get_path("feed.xml"), get_path("feed.xml"))))
        assert one
        assert both == 2 * one

    def test_fan_in_replays(self):
        pipeline = fanned_in_fetches(get_path("feed.xml"))
        assert len(list(pipeline)) == len(list(pipeline))

    def test_fan_in_close_before_iteration_produces_nothing(self):
        stream = iter(fanned_in_fetches(get_path("feed.xml")))
        stream.close()
        assert list(stream) == []


class TestAsyncFanIn:
    @pytest.mark.smoke
    @async_test
    async def test_fan_in_merges_every_source(self):
        single = fanned_in_fetches(get_path("feed.xml"))
        doubled = fanned_in_fetches(get_path("feed.xml"), get_path("feed.xml"))
        one = len([item async for item in single])
        both = len([item async for item in doubled])
        assert one
        assert both == 2 * one

    @async_test
    async def test_fan_in_replays(self):
        pipeline = fanned_in_fetches(get_path("feed.xml"))
        first = [item async for item in pipeline]
        second = [item async for item in pipeline]
        assert first
        assert len(first) == len(second)

    @async_test
    async def test_fan_in_close_before_iteration_produces_nothing(self):
        stream = aiter(fanned_in_fetches(get_path("feed.xml")))
        await stream.aclose()
        assert [item async for item in stream] == []


class Recorder:
    def __init__(self) -> None:
        self.events: list[object] = []

    def emit(self, event: object) -> None:
        self.events.append(event)


class TestWithExecution:
    def test_defaults(self):
        pipeline = Pipeline.from_module("fetch")
        assert pipeline.settings == DEF_EXECUTION_SETTINGS
        assert pipeline.settings.executor is Executor.AUTO
        assert pipeline.settings.concurrency is None
        assert pipeline.settings.ordered is False
        assert pipeline.settings.event_sink is None
        assert pipeline.settings.shutdown_timeout is None
        assert pipeline.context is None

    def test_derives_without_changing_the_original(self):
        base = Pipeline.from_module("fetch")
        pipeline = base.with_execution(concurrency=4, ordered=True)
        assert pipeline is not base
        assert pipeline.workflow == base.workflow
        assert (pipeline.settings.concurrency, pipeline.settings.ordered) == (4, True)
        assert base.settings == DEF_EXECUTION_SETTINGS

    def test_chaining_keeps_the_settings(self):
        pipeline = Pipeline.from_module("fetch").with_execution(concurrency=4)
        chained = [
            pipeline.pipe("sort"),
            pipeline.sort(),
            pipeline | "sort",
            pipeline | ("sort", {"combine": "a"}),
            pipeline | Pipeline.from_module("sort"),
            pipeline.write("out.csv"),
        ]
        assert all(each.settings.concurrency == 4 for each in chained)

    def test_seeding_a_source_keeps_the_settings(self):
        pipeline = Pipeline.from_module("hash").with_execution(executor="thread")
        seeded = SRC | pipeline
        assert seeded.source is SRC
        assert seeded.settings.executor is Executor.THREAD

    @pytest.mark.parametrize(
        ("executor", "expected"),
        [
            ("thread", Executor.THREAD),
            ("inline", Executor.INLINE),
            (Executor.PROCESS, Executor.PROCESS),
            (Executor.AUTO, Executor.AUTO),
        ],
    )
    def test_executor_accepts_strings_and_members(self, executor, expected):
        pipeline = Pipeline.from_module("fetch").with_execution(executor=executor)
        assert pipeline.settings.executor is expected

    def test_concurrency_accepts_auto(self):
        pipeline = Pipeline.from_module("fetch").with_execution(concurrency="auto")
        assert pipeline.settings.concurrency == "auto"

    def test_omitted_arguments_keep_the_current_settings(self):
        sink = Recorder()
        pipeline = Pipeline.from_module("fetch").with_execution(
            executor="thread",
            concurrency=4,
            ordered=True,
            event_sink=sink,
            shutdown_timeout=2.5,
        )
        assert pipeline.settings.event_sink is sink
        assert pipeline.settings.shutdown_timeout == pytest.approx(2.5)
        assert pipeline.with_execution().settings == pipeline.settings

    @pytest.mark.parametrize(
        ("name", "value"),
        [
            ("executor", "thread"),
            ("concurrency", 4),
            ("ordered", True),
            ("event_sink", Recorder()),
            ("shutdown_timeout", 2.5),
        ],
    )
    def test_explicit_none_restores_the_default(self, name, value):
        kwargs = {"executor": "process", "concurrency": 8, name: value}
        pipeline = Pipeline.from_module("fetch").with_execution(**kwargs)
        reset = pipeline.with_execution(**{name: None})
        assert getattr(reset.settings, name) == getattr(DEF_EXECUTION_SETTINGS, name)

        if name not in {"executor", "concurrency"}:
            assert reset.settings.executor is Executor.PROCESS
            assert reset.settings.concurrency == 8

    @pytest.mark.parametrize(
        ("kwargs", "error"),
        [
            ({"executor": "gpu"}, ValueError),
            ({"concurrency": 0}, ValueError),
            ({"concurrency": "4"}, TypeError),
            ({"concurrency": "max"}, TypeError),
            ({"ordered": "yes"}, TypeError),
            ({"shutdown_timeout": -1}, ValueError),
            ({"shutdown_timeout": float("nan")}, ValueError),
        ],
    )
    def test_invalid_settings_raise_at_call_time(self, kwargs, error):
        with pytest.raises(error):
            Pipeline.from_module("fetch").with_execution(**kwargs)


class TestExecutionSettings:
    """Run-wide settings: concurrency, ordering, and where per-item work runs."""

    @pytest.mark.parametrize(
        "build",
        [
            pytest.param(_tokenized, id="module-source"),
            pytest.param(lambda: Pipeline(source=SRC), id="seed"),
        ],
    )
    def test_parallel_matches_sequential_as_multiset(self, build):
        pipeline = build().hash(options={"assign": "h"})
        sequential = list(pipeline)
        parallel = list(pipeline.with_execution(concurrency=4))
        assert len(parallel) == len(sequential) == 3
        assert _by_content(parallel) == _by_content(sequential)

    @pytest.mark.parametrize(
        ("build", "settings", "expected"),
        [
            pytest.param(
                _tokenized,
                {"concurrency": 4, "ordered": True},
                [item["content"] for item in EXPECTED],
                id="ordered",
            ),
            pytest.param(
                lambda: Pipeline(source=SRC), {}, ["a", "b", "c"], id="no-settings"
            ),
            pytest.param(
                lambda: Pipeline(source=SRC),
                {"executor": "inline", "concurrency": 4},
                ["a", "b", "c"],
                id="inline",
            ),
        ],
    )
    def test_preserves_source_order(self, build, settings, expected):
        pipeline = build().hash(options={"assign": "h"}).with_execution(**settings)
        assert [item["content"] for item in pipeline] == expected

    @pytest.mark.parametrize("executor", ["inline", "thread", "process"])
    def test_every_executor_produces_the_same_items(self, executor):
        pipeline = Pipeline(source=SRC).hash(options={"assign": "h"})
        executed = list(pipeline.with_execution(executor=executor))
        assert _by_content(executed) == _by_content(pipeline)


_PARALLEL_BUILDER_CONF = ItemBuilderConf(
    {"attrs": {"key": "content", "value": "a,bb,ccc,dddd"}}
)


def _hashed_tokens() -> Pipeline:
    source = Pipeline.from_module("itembuilder", conf=_PARALLEL_BUILDER_CONF)
    return source.tokenizer(options={"emit": True}).hash(options={"assign": "h"})


@pytest.mark.slow
@skipif_issync
class TestAsyncBoundedParallel:
    @pytest.mark.anyio
    async def test_parallel_matches_sequential_as_multiset(self):
        pipeline = _hashed_tokens()
        sequential = [item async for item in pipeline]
        parallel = [item async for item in pipeline.with_execution(concurrency=4)]
        assert len(parallel) == len(sequential) == 4
        assert _by_content(parallel) == _by_content(sequential)

    @pytest.mark.anyio
    async def test_ordered_parallel_preserves_order(self):
        pipeline = _hashed_tokens()
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


BRANCHES = ("fanin_branch_a", "fanin_branch_b", "fanin_branch_c")


def _fanned_in(names: tuple[str, ...]) -> Pipeline[dict[str, str]]:
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
    flow = Workflow(
        nodes=[*branches, union],
        edges=edges,
        outputs={"default": Endpoint(union.id, "out")},
        inputs={},
    )
    return Pipeline[dict[str, str]](flow)


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


@pytest.mark.slow
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


MODES = [
    (ExecutionMode.RUN, False, False),
    (ExecutionMode.DESCRIBE_INPUTS, True, False),
    (ExecutionMode.DESCRIBE_DEPENDENCIES, False, True),
    (ExecutionMode.DESCRIBE, True, True),
]


class TestContextMode:
    """A ``Context`` carries one ``ExecutionMode`` the describe flags derive from."""

    def test_default_mode_is_run(self):
        assert Context().mode is ExecutionMode.RUN

    @pytest.mark.parametrize(("mode", "wants_input", "wants_deps"), MODES)
    def test_mode_drives_describe_properties(self, mode, wants_input, wants_deps):
        context = Context(mode=mode)
        assert context.describe_input is wants_input
        assert context.describe_dependencies is wants_deps

    def test_orthogonal_flags_preserved(self):
        context = Context(mode=ExecutionMode.DESCRIBE, test=True)
        assert context.test is True
        assert context.mode is ExecutionMode.DESCRIBE

    def test_describe_properties_are_read_only(self):
        context = Context()

        with pytest.raises(AttributeError):
            context.describe_input = True  # pyright: ignore[reportAttributeAccessIssue]

    @pytest.mark.xfail(
        strict=True,
        reason="a Pipeline runs its modules even when its context only asks to "
        "describe it, until pipelines can declare their inputs and dependencies",
    )
    @pytest.mark.parametrize(
        "mode", [ExecutionMode.DESCRIBE_INPUTS, ExecutionMode.DESCRIBE_DEPENDENCIES]
    )
    def test_describing_pipeline_does_not_run_it(self, mode):
        pulled: list[dict[str, int]] = []

        def source() -> Iterator[dict[str, int]]:
            for item in [{"x": 1}, {"x": 2}]:
                pulled.append(item)
                yield item

        pipeline = Pipeline(source=source()).hash()
        described = pipeline.with_context(Context(mode=mode))
        list(described)
        assert pulled == []


class TestContextImmutability:
    """A Context is an immutable definition-layer snapshot."""

    def test_fields_cannot_be_reassigned(self):
        context = Context()

        with pytest.raises(AttributeError):
            context.mode = ExecutionMode.DESCRIBE  # pyright: ignore[reportAttributeAccessIssue]

    def test_rejects_the_removed_submodule_flag(self):
        with pytest.raises(TypeError):
            Context(submodule=True)  # pyright: ignore[reportCallIssue]

    def test_inputs_mapping_is_read_only(self):
        context = Context(inputs={"count": 2})
        assert context.inputs is not None

        with pytest.raises(TypeError):
            context.inputs["count"] = 3  # pyright: ignore[reportIndexIssue]

    def test_resources_mapping_is_read_only(self):
        context = Context()

        with pytest.raises(TypeError):
            context.resources["db"] = object()  # pyright: ignore[reportIndexIssue]

    def test_augment_returns_independent_snapshot(self):
        base = Context(inputs={"count": 2}, test=False)
        derived = base.replace(test=True, inputs={"limit": 5})

        assert derived is not base
        assert base.test is False
        assert derived.test is True
        assert base.inputs == {"count": 2}
        assert derived.inputs == {"limit": 5}

    def test_augment_source_mutation_does_not_leak(self):
        source = {"count": 2}
        context = Context(inputs=source)
        source["count"] = 99
        assert context.inputs == {"count": 2}

    def test_roundtrips_through_pickle(self):
        context = Context(mode=ExecutionMode.DESCRIBE, inputs={"count": 2}, test=True)
        restored = cast("Context", loads(dumps(context)))  # noqa: S301

        assert restored.mode is ExecutionMode.DESCRIBE
        assert restored.test is True
        assert restored.inputs == {"count": 2}

        with pytest.raises(AttributeError):
            restored.mode = ExecutionMode.RUN  # pyright: ignore[reportAttributeAccessIssue]


READER = "settings_resource_reader"


def _reader_workflow() -> Workflow:
    """Builds a one-node workflow whose module declares a ``primary`` resource."""
    node = ModuleNode(id="n", name=READER, resources={"slot": "primary"})
    return Workflow(
        nodes=[node],
        edges=(),
        outputs={"default": Endpoint(node.id, "out")},
        inputs={},
        resources=("primary",),
    )


@pytest.fixture
def reader():
    def read(_items=None, **kwargs):
        yield {"got": kwargs["resources"]["slot"]}

    reset_module_registry()
    sync_pipe = cast("SyncModuleWrapper", read)
    register_module(ModuleDefinition(name=READER, sync_pipe=sync_pipe))

    try:
        yield READER
    finally:
        reset_module_registry()


class TestEnvironmentBinding:
    def test_with_context_derives_without_changing_the_original(self):
        context = Context(inputs={"limit": 5})
        base = Pipeline.from_module("fetch")
        pipeline = base.with_context(context)
        assert pipeline.context is context
        assert base.context is None
        assert pipeline.sort().context is context

    def test_with_resource_extends_the_bound_context(self):
        def open_db():
            yield "conn"

        context = Context(inputs={"limit": 5})
        base = Pipeline.from_module("fetch").with_context(context)
        pipeline = base.with_resource("db", open_db)
        assert pipeline.context is not None
        assert pipeline.context.inputs == context.inputs
        assert sorted(pipeline.context.resources) == ["db"]
        assert dict(context.resources) == {}

    def test_bound_resource_reaches_the_module(self, reader):
        def open_db():
            yield "conn"

        pipeline = Pipeline(_reader_workflow()).with_resource("primary", open_db)
        assert list(pipeline) == [{"got": "conn"}]

    @skipif_issync
    @async_test
    async def test_bound_resource_reaches_the_module_async(self, reader):
        def open_db():
            yield "conn"

        pipeline = Pipeline(_reader_workflow()).with_context(
            Context().with_resource("primary", open_db)
        )
        assert [item async for item in pipeline] == [{"got": "conn"}]

    def test_with_resource_rejects_factory_options_on_a_resource(self):
        def open_db():
            yield "conn"

        pipeline = Pipeline.from_module("fetch").with_resource("db", open_db)
        assert pipeline.context is not None
        resource = pipeline.context.resources["db"]

        with pytest.raises(TypeError):
            pipeline.with_resource(  # pyright: ignore[reportCallIssue]
                "other",
                resource,
                lazy=True,  # pyright: ignore[reportArgumentType]
            )


class TestWritePassthrough:
    """``write`` yields every input item unchanged, in order."""

    def test_sync_preserves_sequence(self, tmp_path):
        conf = WriteConf({"dest": str(tmp_path / "out.json")})
        assert list(pipe(ITEMS, conf=conf)) == ITEMS

    @async_test
    async def test_async_preserves_sequence(self, tmp_path):
        conf = WriteConf({"dest": str(tmp_path / "out.json")})
        result = async_pipe(ITEMS, conf=conf)
        assert [item async for item in result] == ITEMS


@skipif_issync
class TestWriteParity:
    """The sync and async parsers serialize identical bytes."""

    @pytest.mark.anyio
    async def test_json_parity(self, tmp_path):
        sync_path, async_path = tmp_path / "sync.json", tmp_path / "async.json"
        list(pipe(ITEMS, conf=WriteConf({"dest": sync_path, "fmt": "json"})))
        conf = WriteConf({"dest": async_path, "fmt": "json"})
        _ = [item async for item in async_pipe(ITEMS, conf=conf)]
        expected = b'[{"x": 0}, {"x": 1}, {"x": 2}]'
        assert sync_path.read_bytes() == expected
        assert async_path.read_bytes() == expected

    @pytest.mark.anyio
    async def test_csv_parity(self, tmp_path):
        sync_path, async_path = tmp_path / "sync.csv", tmp_path / "async.csv"
        list(pipe(ITEMS, conf=WriteConf({"dest": sync_path, "fmt": "csv"})))
        conf = WriteConf({"dest": async_path, "fmt": "csv"})
        _ = [item async for item in async_pipe(ITEMS, conf=conf)]
        sync_bytes = sync_path.read_bytes()
        assert sync_bytes == async_path.read_bytes()
        assert sync_bytes.split() == [b"x", b"0", b"1", b"2"]


class TestWriteNestedItems:
    """Items holding nested mappings, as module output does, serialize to JSON."""

    @pytest.mark.parametrize(
        ("fmt", "expected"),
        [
            ("json", b'[{"a": {"b": [1, {"c": 2}]}}]'),
            ("jsonl", b'{"a": {"b": [1, {"c": 2}]}}'),
        ],
    )
    def test_nested_dotdict_items(self, tmp_path, fmt, expected):
        items: Items = [DotDict({"a": {"b": [1, {"c": 2}]}})]
        path = tmp_path / f"out.{fmt}"
        list(pipe(items, conf=WriteConf({"dest": path, "fmt": fmt})))
        assert path.read_bytes().strip() == expected


_SEEDED_SET_WRITE = """
import sys
from riko.modules.write import pipe
items = [{"tags": {"alpha", "beta", "gamma", "delta"}}]
list(pipe(items, conf={"dest": sys.argv[1], "fmt": sys.argv[2]}))
"""


class TestWriteSetValues:
    """Set values serialize in a stable sorted order."""

    @pytest.mark.parametrize("fmt", ["json", "jsonl"])
    def test_set_values_are_written_sorted_under_any_hash_seed(self, tmp_path, fmt):
        def write(seed: str) -> bytes:
            path = tmp_path / f"{seed}.{fmt}"
            args = [sys.executable, "-c", _SEEDED_SET_WRITE, str(path), fmt]
            env = {**os.environ, "PYTHONHASHSEED": seed}
            subprocess.run(args, check=True, cwd=ROOT_DIR, env=env)
            return path.read_bytes()

        expected = b'"tags": ["alpha", "beta", "delta", "gamma"]'
        assert all(expected in write(seed) for seed in ("1", "2", "3"))


class TestWriteSkips:
    """Unwritable configurations degrade: nothing is written, items pass through."""

    @pytest.mark.parametrize("fmt", ["bogus", "list", "tuple"])
    def test_sync_bad_target_skips_but_passes_through(self, tmp_path, fmt):
        path = tmp_path / "out"
        conf = cast("WriteConf", {"dest": path, "fmt": fmt})
        assert list(pipe(ITEMS, conf=conf)) == ITEMS
        assert not path.exists()

    @pytest.mark.parametrize("fmt", ["bogus", "list", "tuple"])
    @async_test
    async def test_async_bad_target_skips_but_passes_through(self, tmp_path, fmt):
        path = tmp_path / "out"
        conf = WriteConf({"dest": path, "fmt": fmt})
        result = async_pipe(ITEMS, conf=conf)
        assert [item async for item in result] == ITEMS
        assert not path.exists()

    def test_sync_missing_dest_skips_but_passes_through(self):
        conf = cast("WriteConf", {"fmt": "json"})
        assert list(pipe(ITEMS, conf=conf)) == ITEMS

    @async_test
    async def test_async_missing_dest_skips_but_passes_through(self):
        conf = cast("WriteConf", {"fmt": "json"})
        result = async_pipe(ITEMS, conf=conf)
        assert [item async for item in result] == ITEMS


class TestWriteTargetFromExtension:
    """When ``fmt`` is omitted, the dest extension selects the converter."""

    def test_sync_csv_extension(self, tmp_path):
        path = tmp_path / "out.csv"
        list(pipe(ITEMS, conf=WriteConf({"dest": path})))
        assert path.read_bytes().split() == [b"x", b"0", b"1", b"2"]

    @async_test
    async def test_async_csv_extension(self, tmp_path):
        path = tmp_path / "out.csv"
        result = async_pipe(ITEMS, conf=WriteConf({"dest": path}))
        _ = [item async for item in result]
        assert path.read_bytes().split() == [b"x", b"0", b"1", b"2"]

    def test_explicit_target_overrides_extension(self, tmp_path):
        path = tmp_path / "out.csv"
        list(pipe(ITEMS, conf=WriteConf({"dest": path, "fmt": "json"})))
        assert path.read_bytes() == b'[{"x": 0}, {"x": 1}, {"x": 2}]'

    def test_unknown_extension_fails(self, tmp_path, caplog):
        path = tmp_path / "out.dat"
        list(pipe(ITEMS, conf=WriteConf({"dest": path})))
        assert not path.exists()
        assert any("Invalid Formats: 'dat'" in r.message for r in caplog.records)


@dataclass(frozen=True)
class _RecordStore:
    """A native keyed target exercising the match-keyed/idempotent branches."""

    backend: ClassVar[Backends] = Backends.AIRTABLE

    def capabilities(self, fmt=None) -> WriteCapabilities:
        return WriteCapabilities(
            modes=frozenset(WriteMode),
            match_keyed_modes=frozenset({WriteMode.MERGE, WriteMode.DELETE}),
            idempotent_modes=frozenset({WriteMode.APPEND}),
        )


class TestPipelineWriteDefinition:
    """The ``write`` verb validates its destination when the node is declared."""

    def test_file_rejects_keys(self, tmp_path):
        with pytest.raises(ValueError, match="forbids 'keys'"):
            Pipeline(source=ITEMS).write(tmp_path / "out.csv", keys="x")

    def test_destination_rejects_module_arguments(self, tmp_path):
        with pytest.raises(TypeError, match="not both"):
            Pipeline(source=ITEMS).write(tmp_path / "out.csv", conf=WriteConf({}))

    def test_declares_the_resolved_format_and_mode(self, tmp_path):
        pipeline = Pipeline(source=ITEMS).write(tmp_path / "out.csv", mode="append")
        node = pipeline.workflow.nodes["write-1"]
        assert isinstance(node, WriteNode)
        assert (node.fmt, node.mode, node.keys) == (Formats.CSV, WriteMode.APPEND, ())

    @pytest.mark.xfail(
        strict=True,
        reason="the write module stays reachable until write nodes execute: write() "
        "without a destination chains that module instead of requiring a destination",
    )
    def test_requires_a_destination(self):
        with pytest.raises(TypeError):
            Pipeline(source=ITEMS).write()


@WRITE_NODE_PENDING
class TestPipelineWrite:
    """The ``write`` verb at the pipeline level, once a write node can run."""

    def test_passthrough_preserves_stream(self, tmp_path):
        pipeline = Pipeline(source=ITEMS).write(tmp_path / "out.json")
        assert list(pipeline) == ITEMS

    def test_passthrough_reaches_a_target_without_a_path(self):
        assert list(Pipeline(source=ITEMS).write(_RecordStore())) == ITEMS

    def test_writes_mid_chain(self, tmp_path):
        path = tmp_path / "out.json"
        pipeline = Pipeline(source=ITEMS).write(path).tail(conf={"count": 1})
        assert list(pipeline) == [{"x": 2}]
        assert path.read_bytes() == b'[{"x": 0}, {"x": 1}, {"x": 2}]'

    def test_replace_defers_truncation_until_consumed(self, tmp_path):
        path = tmp_path / "out.jsonl"
        path.write_bytes(b'{"old": 1}\n')
        pipeline = Pipeline(source=ITEMS).write(path, mode="replace")
        assert path.read_bytes() == b'{"old": 1}\n'
        list(pipeline)
        assert path.read_bytes() == b'{"x": 0}\n{"x": 1}\n{"x": 2}\n'

    def test_graceful_close_finalizes_prefix(self, tmp_path):
        path = tmp_path / "out.json"
        stream = iter(Pipeline(source=ITEMS).write(path))
        next(stream)
        stream.close()
        assert path.read_bytes() == b'[{"x": 0}]'

    def test_exception_aborts(self, tmp_path):
        path = tmp_path / "out.json"
        stream = iter(Pipeline(source=ITEMS).write(path))
        next(stream)

        with pytest.raises(RuntimeError, match="boom"):
            stream.throw(RuntimeError("boom"))

        assert not path.exists()

    def test_csv_writes_the_header_once(self, tmp_path):
        path = tmp_path / "out.csv"
        list(Pipeline(source=ITEMS).write(path))
        assert path.read_bytes() == b"x\r\n0\r\n1\r\n2\r\n"

    def test_jsonl_has_no_array(self, tmp_path):
        path = tmp_path / "out.jsonl"
        list(Pipeline(source=ITEMS).write(path))
        assert path.read_bytes() == b'{"x": 0}\n{"x": 1}\n{"x": 2}\n'

    def test_leaf_write_produces_one_framed_document(self, tmp_path):
        path = tmp_path / "out.json"
        pipeline = Pipeline(source=ITEMS).hash(options={"assign": "h"}).write(path)
        assert len(list(pipeline)) == len(ITEMS)
        assert path.read_bytes().startswith(b"[")
        assert path.read_bytes().endswith(b"]")

    def test_non_file_target_execution_unsupported(self):
        pipeline = Pipeline(source=ITEMS).write(_RecordStore())

        with pytest.raises(UnsupportedTargetError, match="_RecordStore"):
            list(pipeline)

    def test_write_does_not_rerun_preceding_module(self, tmp_path):
        once = list(Pipeline(source=ITEMS).hash(options={"assign": "h"}))
        source = Pipeline(source=ITEMS).hash(options={"assign": "h"})
        through = list(source.write(tmp_path / "out.json"))
        assert through == once


class TestExportFormats:
    """``Formats`` members mirror the ``export`` converters."""

    def test_member_and_string_export_identically(self):
        items = [{"a": 1}]
        assert (
            export(items, Formats.JSON).getvalue() == export(items, "json").getvalue()
        )


class TestExportPipeline:
    """``export`` accepts a ``Pipeline`` wherever it accepts a stream."""

    def test_pipeline_exports_its_items(self):
        source = Pipeline.from_module("itembuilder", conf=BUILDER_CONF)
        pipeline = source.tokenizer(options={"emit": True})
        assert export(pipeline) == EXPECTED

    def test_pipeline_serializes(self):
        source = Pipeline.from_module("itembuilder", conf=BUILDER_CONF)
        pipeline = source.tokenizer(options={"emit": True})
        lines = export(pipeline, Formats.CSV).getvalue().splitlines()
        assert lines == ["content", "once is 1x", "twice is 2x", "thrice is 3x"]


TRANSACTIONS = [
    {
        "Account": "Checking",
        "Date": "2024-01-01",
        "Amount": "100.00",
        "Description": "Acme",
        "Reference": "Widget",
        "Row": "1",
    },
    {
        "Account": "Checking",
        "Date": "2024-01-02",
        "Amount": "-50.00",
        "Description": "Store",
        "Reference": "Refund",
        "Row": "2",
    },
]


@pytest.mark.finance
class TestExportFinance:
    """The ``ofx``/``qif`` formats, available only with the ``finance`` extra."""

    def test_export_ofx_serializes_transactions(self):
        """``export(..., Formats.OFX)`` serializes an OFX document, one txn per item."""
        ofx = "".join(export(TRANSACTIONS, Formats.OFX))
        assert "<OFX>" in ofx
        assert ofx.count("<STMTTRN>") == len(TRANSACTIONS)

    def test_export_qif_serializes_transactions(self):
        """``export(..., Formats.QIF)`` emits a QIF document for the transactions."""
        qif = "".join(export(TRANSACTIONS, Formats.QIF))
        assert qif.startswith("!Account")
        assert "Checking" in qif


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


STRR_CONF = StrReplaceConf({"rule": StrReplaceConfRule(find="is", replace="was")})


def _scaled(item: Mapping[str, Any], *, factor: int = 2) -> int:
    return item["x"] * factor


def _keywords(_: object, **kwargs: object) -> list[str]:
    return sorted(kwargs)


def _upper_content(item: Mapping[str, object]) -> str:
    return str(item["content"]).upper()


async def _ascaled(item: Mapping[str, Any], *, factor: int = 2) -> int:
    await checkpoint()
    return item["x"] * factor


def _raise_value_error(item: object) -> NoReturn:
    raise ValueError(item)


def _enrich(item: Mapping[str, object], *, db: Mapping[str, int]) -> dict[str, object]:
    return {**item, "owner": db["owner"]}


def _open_db() -> Generator[dict[str, int]]:
    yield {"owner": 7}


def _to_list(_: object) -> list[int]:
    return [1, 2]


def _to_tuple(_: object) -> tuple[int, ...]:
    return (1, 2)


def _to_generator(_: object) -> Iterator[int]:
    return (value for value in (1, 2))


def _count(value: Iterable[object]) -> int:
    return len(list(value))


_THREAD = {"executor": "thread", "concurrency": 2, "ordered": True}
_PROCESS = {"executor": "process", "concurrency": 2, "ordered": True}

_LISTLIKE_ITEMS = [
    pytest.param(_to_list, {}, id="list-inline"),
    pytest.param(_to_list, _THREAD, id="list-thread"),
    pytest.param(_to_list, _PROCESS, id="list-process"),
    pytest.param(_to_tuple, {}, id="tuple-inline"),
    pytest.param(_to_tuple, _THREAD, id="tuple-thread"),
    pytest.param(_to_tuple, _PROCESS, id="tuple-process"),
    pytest.param(_to_generator, {}, id="generator-inline"),
    pytest.param(_to_generator, _THREAD, id="generator-thread"),
]

_LISTLIKE_PRODUCERS = [
    pytest.param(_to_list, id="list"),
    pytest.param(_to_tuple, id="tuple"),
    pytest.param(_to_generator, id="generator"),
]

_PASSTHROUGH_CASES = [
    pytest.param(["hi"], [len], [2], id="scalar-reaches-fn-unwrapped"),
    pytest.param([{"c": "hi"}], [itemgetter("c"), len], [2], id="chained-scalar"),
    pytest.param([{"x": 1}], [lambda _: None], [None], id="none-is-a-result"),
    pytest.param([{"x": 1}], [lambda i: {"y": i["x"]}], [{"y": 1}], id="mapping"),
    pytest.param([{"x": 1}, {"x": 2}], [_scaled], [2, 4], id="one-per-item"),
]

_MAP_ERRORS = [
    pytest.param({"resources": "db", "db": 1}, "share names", id="alias-collision"),
    pytest.param({"resources": {"no-dash": "db"}}, "identifiers", id="bad-alias"),
    pytest.param({"resources": "class"}, "identifiers", id="keyword-alias"),
    pytest.param({"obj": object()}, "JSON", id="non-json-kwarg"),
    pytest.param({"identity": "bogus"}, "identity", id="bad-identity"),
]

_BAD_VERSIONS = [
    pytest.param(None, "'version' must not be None", id="none"),
    pytest.param([1], "'version' must be a hashable scalar", id="unhashable"),
    pytest.param(([1],), "'version' must be a hashable scalar", id="nested-unhashable"),
    pytest.param(object(), "'version' must be a hashable scalar", id="opaque-object"),
    pytest.param(range(3), "'version' must be a hashable scalar", id="range"),
]

_EXECUTIONS = [
    pytest.param({}, id="inline"),
    pytest.param(_THREAD, id="thread"),
    pytest.param(_PROCESS, id="process"),
]


class TestCallableNodes:
    """A plain callable chained as its own node."""

    @pytest.mark.parametrize(("source", "fns", "expected"), _PASSTHROUGH_CASES)
    def test_map_passes_values_through_as_is(self, source, fns, expected):
        pipeline = Pipeline(source=source)

        for fn in fns:
            pipeline = pipeline.map(fn)

        assert list(pipeline) == expected

    @pytest.mark.parametrize(("produce", "settings"), _LISTLIKE_ITEMS)
    def test_a_listlike_item_reaches_the_next_map_whole(self, produce, settings):
        pipeline = Pipeline(source=[{"x": 1}]).map(produce).map(_count)
        assert list(pipeline.with_execution(**settings)) == [2]

    @pytest.mark.parametrize("produce", _LISTLIKE_PRODUCERS)
    @async_test
    async def test_a_listlike_item_stays_whole_under_async_mapping(self, produce):
        pipeline = Pipeline(source=[{"x": 1}]).map(produce).map(_count)
        mapped = pipeline.with_execution(concurrency=2)
        assert [item async for item in mapped] == [2]

    @pytest.mark.parametrize("settings", [{}, _THREAD], ids=["inline", "thread"])
    def test_a_seed_of_lists_maps_each_list_whole(self, settings):
        seeded = Pipeline(source=[[1, 2], [3]])  # pyright: ignore[reportArgumentType]
        assert list(seeded.map(len).with_execution(**settings)) == [2, 1]

    @pytest.mark.parametrize("returned", [[1, 2], []], ids=["full", "empty"])
    def test_map_returns_an_iterator_as_one_item(self, returned):
        items = list(Pipeline(source=[{"x": 1}]).map(lambda _: iter(returned)))
        assert len(items) == 1
        assert list(items[0]) == returned

    def test_map_propagates_exceptions(self):
        with pytest.raises(ValueError, match="'x': 1"):
            list(Pipeline(source=[{"x": 1}]).map(_raise_value_error))

    def test_map_binds_keywords(self):
        pipeline = Pipeline(source=[{"x": 1}, {"x": 2}]).map(_scaled, factor=10)
        assert list(pipeline) == [10, 20]

    def test_bound_keywords_are_identity_significant(self):
        ten = Pipeline().map(_scaled, factor=10).workflow.nodes["_scaled-1"]
        twenty = Pipeline().map(_scaled, factor=20).workflow.nodes["_scaled-1"]
        assert ten == Pipeline().map(_scaled, factor=10).workflow.nodes["_scaled-1"]
        assert ten != twenty

    def test_map_passes_resources_by_alias(self):
        pipeline = (
            Pipeline(source=[{"x": 1}])
            .with_resource("primary", _open_db)
            .map(_enrich, resources={"db": "primary"})
        )
        assert pipeline.workflow.resources == ("primary",)
        assert list(pipeline) == [{"x": 1, "owner": 7}]

    def test_map_requires_the_context_to_provide_its_resources(self):
        pipeline = Pipeline(source=[{"x": 1}]).map(_enrich, resources="db")

        with pytest.raises(InvalidPipelineError, match="'db' not provided"):
            list(pipeline)

    @pytest.mark.parametrize(("kwargs", "match"), _MAP_ERRORS)
    def test_map_rejects_invalid_arguments(self, kwargs, match):
        with pytest.raises(InvalidPipelineError, match=match):
            Pipeline(source=[{}]).map(_enrich, **kwargs)

    @pytest.mark.parametrize(("version", "match"), _BAD_VERSIONS)
    def test_map_rejects_an_invalid_version(self, version, match):
        with pytest.raises(TypeError, match=match):
            Pipeline(source=[{}]).map(len, version=version)

    @pytest.mark.parametrize("settings", _EXECUTIONS)
    def test_map_passes_only_bound_keywords(self, settings):
        pipeline = Pipeline(source=[{"x": 1}]).map(_keywords, factor=2)
        contextual = pipeline.with_context(Context(inputs={"q": 1}))
        assert list(contextual.with_execution(**settings)) == [["factor"]]

    @async_test
    async def test_async_map_passes_only_bound_keywords(self):
        pipeline = Pipeline(source=[{"x": 1}]).map(_keywords, factor=2)
        assert [item async for item in pipeline] == [["factor"]]

    def test_maps_binding_one_resource_declare_it_once(self):
        pipeline = (
            Pipeline(source=[{"x": 1}])
            .with_resource("db", _open_db)
            .map(_enrich, resources="db")
            .map(_enrich, resources="db")
        )
        assert pipeline.workflow.resources == ("db",)
        assert list(pipeline) == [{"x": 1, "owner": 7}]

    def test_map_carries_version_and_identity(self):
        flow = Pipeline().map(len, version="len-v1", identity="derive").workflow
        node = flow.nodes["len-1"]
        assert isinstance(node, CallableNode)
        assert node.version == "len-v1"
        assert node.identity is IdentityMode.DERIVE

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "rejecting identity modes a one-to-one map cannot honor is not yet "
            "implemented"
        ),
    )
    def test_map_rejects_combine_identity(self):
        with pytest.raises(InvalidPipelineError):
            Pipeline(source=[{}]).map(len, identity="combine")

    @pytest.mark.parametrize(
        ("fn", "node_id"),
        [
            pytest.param(len, "len-1", id="named"),
            pytest.param(lambda item: item, "map-1", id="lambda"),
            pytest.param(itemgetter("x"), "map-1", id="itemgetter"),
        ],
    )
    def test_map_names_the_node_after_the_callable(self, fn, node_id):
        assert list(Pipeline().map(fn).workflow.nodes) == [node_id]

    def test_map_types_its_items_from_the_callable(self):
        pipeline = Pipeline(source=[{"content": "a"}]).map(_upper_content)
        assert_type(pipeline, Pipeline[str])
        assert list(pipeline) == ["A"]

    def test_a_callable_template_chains_with_or(self):
        seeded = Pipeline(source=[1])  # pyright: ignore[reportArgumentType]
        pipeline = seeded.map(str) | Pipeline().map(str)
        assert list(pipeline.workflow.nodes) == ["str-1", "str-2"]
        assert list(pipeline) == ["1"]

    @skipif_issync
    def test_sync_iteration_bridges_an_async_callable(self):
        pipeline = Pipeline(source=[{"x": 1}, {"x": 2}]).map(_ascaled, factor=3)
        assert list(pipeline) == [3, 6]

    @async_test
    async def test_async_iteration_awaits_an_async_callable(self):
        pipeline = Pipeline(source=[{"x": 1}, {"x": 2}]).map(_ascaled)
        assert [item async for item in pipeline] == [2, 4]

    @async_test
    async def test_async_iteration_runs_a_sync_callable(self):
        seeded = Pipeline(source=["hi", "you"])  # pyright: ignore[reportArgumentType]
        pipeline = seeded.map(len)
        assert [item async for item in pipeline] == [2, 3]

    def test_process_executor_runs_a_module_level_callable(self):
        pipeline = Pipeline(source=[{"x": x} for x in range(4)]).map(_scaled)
        assert list(pipeline.with_execution(**_PROCESS)) == [0, 2, 4, 6]

    def test_process_executor_rejects_a_lambda_when_planning(self):
        pipeline = Pipeline(source=[{"x": 1}]).map(lambda item: item)
        settings = {"executor": "process", "concurrency": 2}

        with pytest.raises(InvalidPipelineError, match="cannot be pickled"):
            list(pipeline.with_execution(**settings))

    def test_map_extracts_a_field(self):
        pipeline = _tokenized().map(itemgetter("content"))
        assert isinstance(pipeline, Pipeline)
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


class TestUnseededPipeline:
    """A pipeline whose first node needs input refuses to run without a seed."""

    @SEED_PENDING
    def test_an_unseeded_pipeline_requires_a_seed(self):
        pipeline = Pipeline.from_module(Transforms.REVERSE)

        with pytest.raises((InvalidPipelineError, TypeError), match="seed"):
            list(pipeline)
