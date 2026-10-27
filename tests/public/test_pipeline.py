# vim: sw=4:ts=4:expandtab
"""Provides public tests for building, running, and writing a ``Pipeline``."""

from __future__ import annotations

import gc
import os
import warnings
from concurrent.futures.process import BrokenProcessPool
from contextlib import nullcontext
from operator import itemgetter, methodcaller
from pathlib import Path
from pickle import dumps, loads  # noqa: S403
from time import perf_counter, sleep
from typing import TYPE_CHECKING, Any, NoReturn, assert_type, cast, get_args, get_origin

import pytest

from riko.bado._backend import async_sleep, checkpoint, fail_after
from riko.bado.itertools import alist, async_iter, async_map
from riko.base._exceptions import (
    EmptyPipelineError,
    InvalidPipelineError,
    PipelineError,
    PipelineStateError,
)
from riko.base._guards import is_mapping
from riko.base._paths import get_path
from riko.definitions._context import Context, ExecutionMode
from riko.definitions._nodes import CallableNode, ModuleNode, StreamEdge
from riko.definitions._resource_definition import Resource
from riko.definitions._settings import DEF_EXECUTION_SETTINGS
from riko.definitions._workflow_definition import Workflow
from riko.ext import ModuleDefinition, normalize_module_name, processor
from riko.modules._names import Transforms
from riko.runtime._module_registry import register_module, reset_module_registry
from riko.runtime._pipeline import Pipeline
from riko.types._enums import Executor, IdentityMode, ModuleName
from riko.types._options import CallOptions
from riko.types._streams import is_stateful_item
from riko.types._workflow import Endpoint
from riko.types.modules import (
    ConfArg,
    Embed,
    ItemBuilderConf,
    ParsedParam,
    SortConf,
    SortConfRule,
    StrconcatConf,
    StrReplaceConf,
    StrReplaceConfRule,
    TokenizerRawConf,
)
from tests import aresolve, async_test, skipif_issync
from tests._execution import agen_source, awaitable_source, module_workflow, tag_source
from tests._lifecycle import LIFECYCLE_SRC, boom, fanned_in_fetches, tokenized_letters

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Iterable, Iterator, Mapping

    from riko.types._streams import Item, Items
    from riko.types._wrappers import AsyncModuleWrapper, SyncModuleWrapper

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


_NON_WORKFLOWS = [
    pytest.param(lambda: [{"x": 1}], r"pipeline\(items\)", id="items"),
    pytest.param(lambda: "fetch", r"from_module\(name\)\?", id="module-name"),
    pytest.param(lambda: ("fetch", {}), r"conf=conf", id="module-pair"),
    pytest.param(lambda: {"nodes": []}, r"Workflow\.parse", id="document"),
    pytest.param(lambda: Pipeline.from_module("sort"), r"\.workflow", id="pipeline"),
    pytest.param(lambda: 3, r"Got 'int'", id="other"),
]


class TestPipelineConstruction:
    def test_module_seed_builds_single_node_workflow(self):
        pipeline = Pipeline.from_module("fetch")
        assert sorted(pipeline.workflow.nodes) == ["fetch-1"]
        assert pipeline.workflow.outputs["default"] == Endpoint("fetch-1", "out")
        assert pipeline.workflow.edges == ()
        assert pipeline.workflow.isvalid

    def test_pipeline_repr_notes_nodes_and_context(self):
        fetch = Pipeline.from_module("fetch")
        assert repr(fetch) == "Pipeline(fetch-1; outputs: default)"
        bound = Pipeline(context=Context())
        assert repr(bound) == "Pipeline(empty; context)"

    def test_workflow_constructor_keeps_the_workflow(self):
        flow = _workflow()
        assert Pipeline(flow).workflow is flow

    def test_empty_constructor_builds_an_empty_workflow(self):
        pipeline = Pipeline()
        assert dict(pipeline.workflow.nodes) == {}
        assert not pipeline.workflow.isvalid

    def test_pipeline_is_generic_over_item_type(self):
        alias = Pipeline[int]

        assert get_origin(alias) is Pipeline
        assert get_args(alias) == (int,)

    @pytest.mark.parametrize(("make", "match"), _NON_WORKFLOWS)
    def test_non_workflow_positional_rejected(self, make, match):
        value = make()

        with pytest.raises(TypeError, match=match):
            Pipeline(value)


_SORT_CONF_RULE = SortConfRule(dir="desc")
_SORT_CONF = SortConf({"rule": _SORT_CONF_RULE})
_OPTIONS = CallOptions(emit=True, field="title")

tokenizer_conf = TokenizerRawConf(delimiter=ConfArg(type="text", value=" "))
_EMBED = Embed(name="tokenizer", conf=tokenizer_conf)


def _tag_db(item: Item, db: int) -> dict[str, object]:
    return {**item, "db": db}


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

    def test_chained_loop_carries_its_embed_and_options(self):
        pipeline = Pipeline.from_module("itembuilder").loop(
            embed=_EMBED, options=_OPTIONS
        )
        node = pipeline.workflow.nodes["loop-1"]
        _assert_embed(node)
        assert isinstance(node, ModuleNode)
        assert node.conf == {}

    def test_or_copies_a_loop_node_embed_and_options(self):
        looped = Pipeline.from_module("loop", embed=_EMBED, options=_OPTIONS)
        pipeline = Pipeline.from_module("itembuilder") | looped
        _assert_embed(pipeline.workflow.nodes["loop-1"])

    def test_or_chains_a_single_module_pipeline(self):
        pipeline = Pipeline.from_module("fetch") | Pipeline.from_module("sort")
        assert sorted(pipeline.workflow.nodes) == ["fetch-1", "sort-1"]

    def test_or_keeps_node_resources_and_label(self):
        node = ModuleNode(id="hash-1", name="hash", resources="db", label="L")
        hashed = Pipeline(Workflow().with_node(node))
        pipeline = Pipeline.from_module("fetch") | hashed
        chained = pipeline.workflow.nodes["hash-1"]
        assert (dict(chained.resources), chained.label) == ({"db": "db"}, "L")
        assert pipeline.workflow.resources == ("db",)

    def test_or_string_matches_attribute_chaining(self):
        via_or = list((Pipeline() | "hash")(SRC))
        via_attr = list(Pipeline().hash()(SRC))
        assert via_or == via_attr
        assert len(via_or) == 3

    def test_duplicate_names_mint_unique_ids(self):
        pipeline = Pipeline.from_module("sort").pipe("sort")
        assert sorted(pipeline.workflow.nodes) == ["sort-1", "sort-2"]

    @pytest.mark.parametrize(
        "name", ["_hidden", "keys", "values", "items", "get", "close", "sortt"]
    )
    def test_getattr_rejects_non_builtin_names(self, name):
        with pytest.raises(AttributeError):
            getattr(Pipeline.from_module("fetch"), name)

    def test_or_composes_associatively(self):
        sort, reverse = Pipeline.from_module("sort"), Pipeline.from_module("reverse")
        left, right = (sort | reverse) | sort, sort | (reverse | sort)
        assert left.workflow == right.workflow
        assert list(left(ITEMS)) == list(right(ITEMS))
        assert (
            left.workflow.summary == "sort-1 -> reverse-1 -> sort-2; outputs: default"
        )

    def test_or_with_an_empty_pipeline_keeps_the_other_side(self):
        sort = Pipeline.from_module("sort")
        assert (sort | Pipeline()).workflow == sort.workflow
        assert (Pipeline() | sort).workflow == sort.workflow

    def test_or_combines_the_resources_each_side_provides(self):
        db = Resource.from_external(7)
        tagged = Pipeline().map(_tag_db, resources=["db"]).with_resource("db", db)
        pipeline = Pipeline.from_module("sort").with_resource("db", db) | tagged
        assert pipeline.context is not None
        assert dict(pipeline.context.resources) == {"db": db}
        assert list(pipeline([{"x": 1}])) == [{"x": 1, "db": 7}]

    @pytest.mark.parametrize(
        ("combine", "error", "match"),
        [
            pytest.param(lambda p: p | 3, TypeError, "unsupported", id="or"),
            pytest.param(lambda p: 3 | p, TypeError, "unsupported", id="ror"),
            pytest.param(lambda p: p | ("sort", {}), TypeError, "tuple", id="pair"),
            pytest.param(lambda p: p | len, TypeError, r"\.map\(fn\)", id="function"),
            pytest.param(
                lambda p: (
                    p.with_resource("db", Resource.from_external(1))
                    | p.with_resource("db", Resource.from_external(2))
                ),
                InvalidPipelineError,
                "different resources",
                id="resource-clash",
            ),
            pytest.param(
                lambda p: p | p.with_execution(concurrency=2),
                InvalidPipelineError,
                "execution settings",
                id="settings",
            ),
            pytest.param(
                lambda p: p | p.with_context(Context(inputs={"a": 1})),
                InvalidPipelineError,
                "inputs",
                id="context",
            ),
        ],
    )
    def test_or_rejects(self, combine, error, match):
        with pytest.raises(error, match=match):
            combine(Pipeline.from_module("fetch"))

    @pytest.mark.xfail(
        strict=True,
        raises=TypeError,
        reason="composing a decorated processor with | is not yet implemented",
    )
    def test_or_composes_a_decorated_processor(self):
        @processor
        def doubled(item, extraction, objconf, **kwargs) -> int:
            return item["x"] * 2

        pipeline = Pipeline() | doubled
        assert list(pipeline([{"x": 3}])) == [{"x": 3, "doubled": 6}]

    def test_a_module_name_after_a_stream_asks_to_compose_first(self):
        with pytest.raises(TypeError, match="compose the pipeline first"):
            _ = ITEMS | Pipeline.from_module("sort") | "count"  # pyright: ignore[reportOperatorIssue]

    def test_ror_on_a_stream_seeds_a_run(self):
        hashed = Pipeline.from_module("hash")
        counted = Pipeline.from_module("count")
        assert list(hashed(SRC) | counted) == [{"count": 3}]


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
        pipeline = Pipeline() | _Mod.HASH
        assert pipeline.workflow.nodes["hash-1"].name == "hash"
        assert len(list(pipeline(SRC))) == 3

    def test_enum_through_method(self):
        pipeline = Pipeline().pipe(_Mod.TRUNCATE, conf={"count": 1})
        assert pipeline.workflow.nodes["truncate-1"].name == "truncate"
        assert len(list(pipeline(SRC))) == 1


FIRST_CASES = [
    pytest.param([], None, None, id="empty-none"),
    pytest.param([], {"x": 0}, {"x": 0}, id="empty-mapping"),
    pytest.param([{"x": 1}], None, {"x": 1}, id="item"),
]


class TestPipelineIteration:
    def test_an_empty_pipeline_streams_its_seed_unchanged(self):
        assert list(Pipeline()([{"x": 1}, {"x": 2}])) == [{"x": 1}, {"x": 2}]
        assert list(Pipeline()({"x": 1})) == [{"x": 1}]

    def test_a_dotted_assignment_leaves_the_seed_untouched(self):
        seed: Items = [{"a": {"b": "hi"}}]
        options = CallOptions(field="a.b", assign="a.c")
        conf = {"rule": {"transform": "upper"}}
        pipeline = Pipeline().strtransform(conf=conf, options=options)
        assert list(pipeline(seed)) == [{"a": {"b": "hi", "c": "HI"}}]
        assert seed == [{"a": {"b": "hi"}}]

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
            assert list(Pipeline().pipe("doubler")([{"x": 10}])) == [{"x": 20}]
        finally:
            reset_module_registry()

    @pytest.mark.parametrize(("seed", "default", "expected"), FIRST_CASES)
    def test_first_returns_the_default_on_an_empty_run(self, seed, default, expected):
        assert Pipeline().first(seed, default=default) == expected

    def test_first_reads_a_self_starting_pipeline_unseeded(self):
        assert _tokenized().first(default=None) == EXPECTED[0]

    def test_first_on_an_empty_pipeline_raises_a_lookup_error(self):
        with pytest.raises(EmptyPipelineError, match="no items") as info:
            Pipeline().first([])

        assert isinstance(info.value, PipelineError)
        assert isinstance(info.value, LookupError)

    def test_first_does_not_leak_stop_iteration_into_an_outer_iterator(self):
        pipeline = Pipeline()

        with pytest.raises(EmptyPipelineError):
            list(map(pipeline.first, [[{"x": 1}], []]))

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
    async def test_an_empty_pipeline_streams_an_async_seed_unchanged(self):
        async def seed():
            yield {"x": 1}

        assert [item async for item in Pipeline()(seed())] == [{"x": 1}]

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
        pipeline = Pipeline()

        with pytest.raises(EmptyPipelineError):
            await pipeline.afirst([])

        assert await pipeline.afirst([], default=None) is None
        assert await pipeline.afirst([{"x": 1}]) == {"x": 1}

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

    def test_a_generator_seed_reruns_when_handed_a_fresh_seed(self):
        pipeline = Pipeline.from_module("hash")
        assert len(list(pipeline(item for item in LIFECYCLE_SRC))) == len(LIFECYCLE_SRC)
        assert len(list(pipeline(item for item in LIFECYCLE_SRC))) == len(LIFECYCLE_SRC)

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
    async def test_a_generator_seed_reruns_when_handed_a_fresh_seed(self):
        pipeline = Pipeline.from_module("hash")
        first = [item async for item in pipeline(async_iter(LIFECYCLE_SRC))]
        second = [item async for item in pipeline(async_iter(LIFECYCLE_SRC))]
        assert len(first) == len(second) == len(LIFECYCLE_SRC)

    @async_test
    async def test_iteration_after_partial_iteration_restarts(self):
        pipeline = tokenized_letters()
        stream = pipeline()
        assert await anext(stream) == {"content": "a"}
        await stream.aclose()
        assert len([item async for item in pipeline]) == 3


@pytest.fixture
def probe_log():
    """Registers a ``probe`` transformer that logs when its run is closed."""
    log: list[str] = []

    def probe(items, **_):
        try:
            yield from items
        finally:
            log.append("closed")

    reset_module_registry()
    sync_pipe = cast("SyncModuleWrapper", probe)
    register_module(ModuleDefinition(name="probe", sync_pipe=sync_pipe))

    try:
        yield log
    finally:
        reset_module_registry()


class TestClose:
    def test_close_before_the_first_item_never_runs_the_source(self):
        ran: list[int] = []

        def source():
            ran.append(1)
            yield {"content": "x"}

        stream = Pipeline.from_module("hash")(source())
        stream.close()
        assert ran == []

    def test_close_is_idempotent(self):
        stream = tokenized_letters()()
        stream.close()
        stream.close()
        assert list(stream) == []

    def test_early_close_stops_a_partially_consumed_run(self):
        consumed: list[int] = []
        closed: list[bool] = []

        def source():
            try:
                for index in range(20):
                    consumed.append(index)
                    yield {"content": str(index)}
            finally:
                closed.append(True)

        stream = Pipeline.from_module("hash")(source())
        assert next(stream)
        stream.close()
        assert len(consumed) < 20
        assert closed == [True]

    def test_closing_one_stream_leaves_the_definition_runnable(self):
        pipeline = tokenized_letters()
        stream = pipeline()
        assert next(stream)
        stream.close()
        assert len(list(pipeline)) == 3

    def test_early_close_closes_an_upstream_module(self) -> None:
        closed: list[bool] = []

        @tag_source
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
            stream = Pipeline(module_workflow("itersrc2"))()
            assert next(stream) == {"x": 1}
            stream.close()
            assert closed == [True]
        finally:
            reset_module_registry()

    def test_break_inside_open_closes_the_run_on_leaving_the_block(self, probe_log):
        with Pipeline.from_module("probe").open(SRC) as stream:
            for _ in stream:
                break

            assert probe_log == []

        assert probe_log == ["closed"]

    @skipif_issync
    def test_leaving_open_closes_an_async_generator_seed(self):
        closed: list[bool] = []

        async def source():
            try:
                for index in range(20):
                    yield {"content": str(index)}
            finally:
                closed.append(True)

        with Pipeline.from_module("hash").open(source()) as stream:
            assert next(stream)
            assert closed == []

        assert closed == [True]

    def test_concurrent_open_runs_are_independent(self):
        pipeline = Pipeline.from_module("hash")

        with pipeline.open(SRC) as left, pipeline.open(SRC[::-1]) as right:
            pairs = [(next(left), next(right)) for _ in SRC]

        lefts, rights = zip(*pairs, strict=True)
        assert [item["content"] for item in lefts] == ["a", "b", "c"]
        assert [item["content"] for item in rights] == ["c", "b", "a"]


def _is_unclosed_run_warning(warning: warnings.WarningMessage) -> bool:
    return "unclosed pipeline run" in str(warning.message)


class TestAsyncClose:
    @async_test
    async def test_close_before_the_first_item_never_runs_the_source(self):
        ran: list[int] = []

        async def source():
            ran.append(1)
            yield {"content": "x"}

        stream = Pipeline.from_module("hash")(source())
        await stream.aclose()
        assert ran == []

    @async_test
    async def test_close_is_idempotent(self):
        stream = tokenized_letters()()
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

        stream = Pipeline.from_module("hash")(source())
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
            first = await hashed.afirst(source())
            gc.collect()
            await checkpoint()

        assert first["content"] == "0"
        assert len(consumed) < 20

    @async_test
    async def test_break_inside_open_closes_the_run_in_the_opening_task(self):
        closed: list[bool] = []

        async def seed():
            try:
                for index in range(50):
                    yield {"content": str(index)}
            finally:
                closed.append(True)

        with fail_after(5):
            async with Pipeline.from_module("hash").open(seed()) as stream:
                async for _ in stream:
                    break

                assert closed == []

            assert closed == [True]
            gc.collect()

            for _ in range(5):
                await checkpoint()

    @async_test
    async def test_bare_break_leaves_the_callers_cancel_scope_intact(self):
        source = [{"content": str(index)} for index in range(5)]

        with fail_after(5), warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")

            async for _ in source | Pipeline.from_module("hash"):
                break

            gc.collect()

            for _ in range(5):
                await checkpoint()

        assert any(map(_is_unclosed_run_warning, caught))

    @async_test
    async def test_concurrent_open_runs_are_independent(self):
        pipeline = Pipeline.from_module("hash")

        async with pipeline.open(SRC) as left, pipeline.open(SRC[::-1]) as right:
            pairs = [(await anext(left), await anext(right)) for _ in SRC]

        lefts, rights = zip(*pairs, strict=True)
        assert [item["content"] for item in lefts] == ["a", "b", "c"]
        assert [item["content"] for item in rights] == ["c", "b", "a"]


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


def _fail_item(item):
    raise ValueError("bad item")


async def _afail_item(item):
    raise ValueError("bad item")


FAILING_MAPS = [
    pytest.param(_fail_item, None, id="sync"),
    pytest.param(_afail_item, None, id="async"),
    pytest.param(_fail_item, 2, id="sync-concurrent"),
    pytest.param(_afail_item, 2, id="async-concurrent"),
]


class TestAsyncFailure:
    @pytest.mark.parametrize(("func", "concurrency"), FAILING_MAPS)
    @async_test
    async def test_a_failing_node_raises_its_own_error(self, func, concurrency):
        pipeline = Pipeline().map(func).with_execution(concurrency=concurrency)

        with pytest.raises(ValueError, match="bad item"):
            await alist(pipeline(SRC))


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
        stream = make_source() | Pipeline.from_module("hash")
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


async def _fail(value):
    raise ValueError(f"bad {value}")


class TestAsyncMap:
    @async_test
    async def test_a_lone_failure_raises_as_itself(self):
        with pytest.raises(ValueError, match="bad 1"):
            await async_map(_fail, [1])

    @async_test
    async def test_several_failures_raise_together(self):
        with pytest.raises(ExceptionGroup) as caught:
            await async_map(_fail, [1, 2])

        assert len(caught.value.exceptions) == 2


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

    def test_fan_in_close_before_iteration_ends_the_run(self):
        stream = fanned_in_fetches(get_path("feed.xml"))()
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
    async def test_fan_in_close_before_iteration_ends_the_run(self):
        stream = fanned_in_fetches(get_path("feed.xml"))()
        await stream.aclose()
        assert [item async for item in stream] == []


def _exit_worker(item):
    os._exit(1)


def _wait_or_block(item):
    marker = Path(item["dir"], "blocked.pid")

    if item["role"] == "block":
        staged = marker.with_suffix(".tmp")
        staged.write_text(str(os.getpid()))
        staged.replace(marker)
        sleep(60)

    while not marker.exists():
        sleep(0.01)

    if item["role"] == "fail":
        raise ValueError("boom")

    return item


_STOPPED_RUNS = [
    pytest.param("pass", nullcontext(), id="early-close"),
    pytest.param("fail", pytest.raises(ValueError, match="boom"), id="failing-sibling"),
]


class Recorder:
    def __init__(self) -> None:
        self.events: list[object] = []

    def emit(self, event: object) -> None:
        self.events.append(event)


class TestWithExecution:
    @pytest.mark.slow
    @pytest.mark.timeout(60)
    def test_a_dead_worker_process_fails_the_run(self) -> None:
        mapped = Pipeline().map(_exit_worker)
        pipeline = mapped.with_execution(executor="process", concurrency=2)

        with pytest.raises(BrokenProcessPool):
            list(pipeline([{"x": 1}, {"x": 2}]))

    @pytest.mark.slow
    @pytest.mark.timeout(60)
    @pytest.mark.parametrize(("role", "expectation"), _STOPPED_RUNS)
    def test_stopping_the_run_kills_a_busy_worker_process(
        self, tmp_path, role, expectation
    ) -> None:
        mapped = Pipeline().map(_wait_or_block)
        pipeline = mapped.with_execution(executor="process", concurrency=2)
        items = [
            {"dir": str(tmp_path), "role": "block"},
            {"dir": str(tmp_path), "role": role},
        ]

        with expectation:
            pipeline.first(items)

        pid = int(Path(tmp_path, "blocked.pid").read_text())

        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)

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
            pipeline | Pipeline.from_module("sort"),
            pipeline.write("out.csv"),
        ]
        assert all(each.settings.concurrency == 4 for each in chained)

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
        ("build", "seed"),
        [
            pytest.param(_tokenized, None, id="module-source"),
            pytest.param(Pipeline, SRC, id="seed"),
        ],
    )
    def test_parallel_matches_sequential_as_multiset(self, build, seed):
        pipeline = build().hash(options={"assign": "h"})
        sequential = list(pipeline(seed))
        parallel = list(pipeline.with_execution(concurrency=4)(seed))
        assert len(parallel) == len(sequential) == 3
        assert _by_content(parallel) == _by_content(sequential)

    @pytest.mark.parametrize(
        ("build", "seed", "settings", "expected"),
        [
            pytest.param(
                _tokenized,
                None,
                {"concurrency": 4, "ordered": True},
                [item["content"] for item in EXPECTED],
                id="ordered",
            ),
            pytest.param(Pipeline, SRC, {}, ["a", "b", "c"], id="no-settings"),
            pytest.param(
                Pipeline,
                SRC,
                {"executor": "inline", "concurrency": 4},
                ["a", "b", "c"],
                id="inline",
            ),
        ],
    )
    def test_preserves_source_order(self, build, seed, settings, expected):
        pipeline = build().hash(options={"assign": "h"}).with_execution(**settings)
        assert [item["content"] for item in pipeline(seed)] == expected

    @pytest.mark.parametrize("executor", ["inline", "thread", "process"])
    def test_every_executor_produces_the_same_items(self, executor):
        pipeline = Pipeline().hash(options={"assign": "h"})
        executed = list(pipeline.with_execution(executor=executor)(SRC))
        assert _by_content(executed) == _by_content(pipeline(SRC))


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

        hashed = Pipeline.from_module("hash")
        pipeline = hashed.with_execution(concurrency=2, ordered=ordered)
        stream = pipeline(tracking())
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

        hashed = Pipeline.from_module("hash")
        pipeline = hashed.with_execution(concurrency=2, ordered=ordered)
        stream = pipeline(unbounded())
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
        @tag_source
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

        pipeline = Pipeline().hash()
        described = pipeline.with_context(Context(mode=mode))
        list(described(source()))
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
    @tag_source
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
        pipeline = Pipeline().hash().publish(events)

        assert len(list(pipeline([{"content": "a"}]))) == 1
        assert len(list(pipeline([{"content": "b"}]))) == 1
        assert len(seen) == 2

    def test_closing_the_publisher_keeps_what_it_delivered(self):
        seen: list[object] = []
        events = Pipeline.subscribe("abandoned", func=seen.append)
        stream = Pipeline().publish(events)([{"x": 0}, {"x": 1}])
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

        left, right = Pipeline.from_module("hash").split(2)
        assert list(left(source())) == list(right(source()))
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
        pipeline = Pipeline()

        for fn in fns:
            pipeline = pipeline.map(fn)

        assert list(pipeline(source)) == expected

    @pytest.mark.parametrize(("produce", "settings"), _LISTLIKE_ITEMS)
    def test_a_listlike_item_reaches_the_next_map_whole(self, produce, settings):
        pipeline = Pipeline().map(produce).map(_count)
        assert list(pipeline.with_execution(**settings)([{"x": 1}])) == [2]

    @pytest.mark.parametrize("produce", _LISTLIKE_PRODUCERS)
    @async_test
    async def test_a_listlike_item_stays_whole_under_async_mapping(self, produce):
        pipeline = Pipeline().map(produce).map(_count)
        mapped = pipeline.with_execution(concurrency=2)
        assert [item async for item in mapped([{"x": 1}])] == [2]

    @pytest.mark.parametrize("settings", [{}, _THREAD], ids=["inline", "thread"])
    def test_a_seed_of_lists_maps_each_list_whole(self, settings):
        pipeline = Pipeline().map(len).with_execution(**settings)
        assert list(pipeline([[1, 2], [3]])) == [2, 1]  # pyright: ignore[reportArgumentType]

    @pytest.mark.parametrize("returned", [[1, 2], []], ids=["full", "empty"])
    def test_map_returns_an_iterator_as_one_item(self, returned):
        items = list(Pipeline().map(lambda _: iter(returned))([{"x": 1}]))
        assert len(items) == 1
        assert list(items[0]) == returned

    def test_map_propagates_exceptions(self):
        with pytest.raises(ValueError, match="'x': 1"):
            list(Pipeline().map(_raise_value_error)([{"x": 1}]))

    def test_map_binds_keywords(self):
        pipeline = Pipeline().map(_scaled, factor=10)
        assert list(pipeline([{"x": 1}, {"x": 2}])) == [10, 20]

    def test_bound_keywords_are_identity_significant(self):
        ten = Pipeline().map(_scaled, factor=10).workflow.nodes["_scaled-1"]
        twenty = Pipeline().map(_scaled, factor=20).workflow.nodes["_scaled-1"]
        assert ten == Pipeline().map(_scaled, factor=10).workflow.nodes["_scaled-1"]
        assert ten != twenty

    def test_map_passes_resources_by_alias(self):
        pipeline = (
            Pipeline()
            .with_resource("primary", _open_db)
            .map(_enrich, resources={"db": "primary"})
        )
        assert pipeline.workflow.resources == ("primary",)
        assert list(pipeline([{"x": 1}])) == [{"x": 1, "owner": 7}]

    def test_map_requires_the_context_to_provide_its_resources(self):
        pipeline = Pipeline().map(_enrich, resources="db")

        with pytest.raises(InvalidPipelineError, match="'db' not provided"):
            list(pipeline([{"x": 1}]))

    @pytest.mark.parametrize(("kwargs", "match"), _MAP_ERRORS)
    def test_map_rejects_invalid_arguments(self, kwargs, match):
        with pytest.raises(InvalidPipelineError, match=match):
            Pipeline().map(_enrich, **kwargs)

    @pytest.mark.parametrize(("version", "match"), _BAD_VERSIONS)
    def test_map_rejects_an_invalid_version(self, version, match):
        with pytest.raises(TypeError, match=match):
            Pipeline().map(len, version=version)

    @pytest.mark.parametrize("settings", _EXECUTIONS)
    def test_map_passes_only_bound_keywords(self, settings):
        pipeline = Pipeline().map(_keywords, factor=2)
        contextual = pipeline.with_context(Context(inputs={"q": 1}))
        assert list(contextual.with_execution(**settings)([{"x": 1}])) == [["factor"]]

    @async_test
    async def test_async_map_passes_only_bound_keywords(self):
        pipeline = Pipeline().map(_keywords, factor=2)
        assert [item async for item in pipeline([{"x": 1}])] == [["factor"]]

    def test_maps_binding_one_resource_declare_it_once(self):
        pipeline = (
            Pipeline()
            .with_resource("db", _open_db)
            .map(_enrich, resources="db")
            .map(_enrich, resources="db")
        )
        assert pipeline.workflow.resources == ("db",)
        assert list(pipeline([{"x": 1}])) == [{"x": 1, "owner": 7}]

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
            Pipeline().map(len, identity="combine")

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
        pipeline = Pipeline().map(_upper_content)
        assert_type(pipeline, Pipeline[str])
        assert list(pipeline([{"content": "a"}])) == ["A"]

    def test_a_callable_pipeline_chains_with_or(self):
        pipeline = Pipeline().map(str) | Pipeline().map(str)
        assert list(pipeline.workflow.nodes) == ["str-1", "str-2"]
        assert list(pipeline([1])) == ["1"]  # pyright: ignore[reportArgumentType]

    @skipif_issync
    def test_sync_iteration_bridges_an_async_callable(self):
        pipeline = Pipeline().map(_ascaled, factor=3)
        assert list(pipeline([{"x": 1}, {"x": 2}])) == [3, 6]

    @async_test
    async def test_async_iteration_awaits_an_async_callable(self):
        pipeline = Pipeline().map(_ascaled)
        assert [item async for item in pipeline([{"x": 1}, {"x": 2}])] == [2, 4]

    @async_test
    async def test_async_iteration_runs_a_sync_callable(self):
        pipeline = Pipeline().map(len)
        seed = ["hi", "you"]
        stream = pipeline(seed)  # pyright: ignore[reportArgumentType]
        assert [item async for item in stream] == [2, 3]

    def test_process_executor_runs_a_module_level_callable(self):
        pipeline = Pipeline().map(_scaled).with_execution(**_PROCESS)
        assert list(pipeline([{"x": x} for x in range(4)])) == [0, 2, 4, 6]

    def test_process_executor_rejects_a_lambda_when_planning(self):
        pipeline = Pipeline().map(lambda item: item)
        settings = {"executor": "process", "concurrency": 2}

        with pytest.raises(InvalidPipelineError, match="cannot be pickled"):
            list(pipeline.with_execution(**settings)([{"x": 1}]))

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
        assert pipeline.first() == {"content": 396558121}
        assert len(runs) == 1


@PREDICATE_PENDING
class TestConditionalNodes:
    """A node gated on a per-item predicate rather than applied to every item."""

    def test_a_gated_node_runs_only_for_matching_items(self):
        items = [{"kind": "hourly", "rate": "$1"}, {"kind": "fixed", "rate": "$1"}]
        part = [{"subkey": "rate", "type": "text"}, " / hr"]
        pipeline = Pipeline().strconcat(
            conf=StrconcatConf({"part": part}),
            options={"assign": "rate"},
            skip_if=lambda item: item.get("kind") != "hourly",
        )
        assert [item.get("rate") for item in pipeline(items)] == ["$1 / hr", "$1"]


def _first_in_open(pipeline: Pipeline) -> object:
    with pipeline.open() as stream:
        item = next(stream)

    return item


def _start_and_drop(pipeline: Pipeline) -> None:
    stream = pipeline(SRC)
    next(stream)


UNSEEDED_RUNS = [
    pytest.param(list, id="iter"),
    pytest.param(_first_in_open, id="open"),
    pytest.param(Pipeline.first, id="first"),
]

FINISHES = [
    pytest.param(list, id="finished"),
    pytest.param(methodcaller("close"), id="closed"),
]


class TestPipelineSeeding:
    """A run takes its seed per call; one whose first node needs input requires it."""

    def test_a_string_before_or_is_refused_with_both_readings(self):
        pipeline = Pipeline.from_module("hash")

        with pytest.raises(
            TypeError, match=r"pipeline\('sort'\).*from_module\('sort'\)"
        ):
            _ = "sort" | pipeline

    @pytest.mark.parametrize("run", UNSEEDED_RUNS)
    def test_an_unseeded_pipeline_requires_a_seed(self, run):
        pipeline = Pipeline.from_module(Transforms.REVERSE)

        with pytest.raises(InvalidPipelineError, match="requires a seed"):
            run(pipeline)

    @async_test
    async def test_an_unseeded_pipeline_requires_a_seed_async(self):
        pipeline = Pipeline.from_module(Transforms.REVERSE)

        with pytest.raises(InvalidPipelineError, match="requires a seed"):
            _ = [item async for item in pipeline]

        with pytest.raises(InvalidPipelineError, match="requires a seed"):
            await pipeline.afirst()


class TestPipelineStream:
    """A called pipeline is a single-use stream, iterated in one mode only."""

    def test_with_on_a_stream_points_at_open(self):
        stream = Pipeline()(SRC)

        with pytest.raises(TypeError, match="open"), stream:  # pyright: ignore[reportGeneralTypeIssues]
            pass

    @async_test
    async def test_async_with_on_a_stream_points_at_open(self):
        stream = Pipeline()(SRC)

        with pytest.raises(TypeError, match="open"):
            async with stream:  # pyright: ignore[reportGeneralTypeIssues]
                pass

    def test_a_consumed_stream_yields_nothing_more(self):
        stream = Pipeline()(SRC)
        assert list(stream) == SRC
        assert list(stream) == []
        assert next(stream, None) is None

    def test_a_closed_stream_yields_nothing_more(self):
        stream = Pipeline()(SRC)
        assert next(stream) == SRC[0]
        stream.close()
        assert list(stream) == []
        assert next(stream, None) is None

    def test_a_partly_consumed_stream_can_be_reentered(self):
        stream = Pipeline()(SRC)
        assert next(stream) == SRC[0]
        assert list(stream) == SRC[1:]

    @async_test
    async def test_a_consumed_async_stream_yields_nothing_more(self):
        stream = Pipeline()(SRC)
        assert [item async for item in stream] == SRC
        assert [item async for item in stream] == []
        assert await anext(stream, None) is None

    @async_test
    async def test_mixing_sync_and_async_iteration_raises(self):
        pipeline = Pipeline.from_module("hash")
        sync_stream = pipeline(SRC)
        async_stream = pipeline(SRC)
        assert next(sync_stream)
        assert await anext(async_stream)

        with pytest.raises(PipelineStateError, match="cannot asynchronously iterate"):
            await anext(sync_stream)

        with pytest.raises(PipelineStateError, match="cannot synchronously iterate"):
            next(async_stream)

        with pytest.raises(PipelineStateError, match="cannot synchronously close"):
            async_stream.close()

        await sync_stream.aclose()
        await async_stream.aclose()

    def test_dropping_a_started_unclosed_stream_warns(self):
        with pytest.warns(ResourceWarning, match="unclosed pipeline run"):
            _start_and_drop(Pipeline.from_module("hash"))

    @pytest.mark.parametrize("finish", FINISHES)
    def test_dropping_a_finished_or_closed_stream_does_not_warn(self, finish):
        stream = Pipeline.from_module("hash")(SRC)
        assert next(stream)
        finish(stream)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            del stream
            gc.collect()

        assert not any(map(_is_unclosed_run_warning, caught))
