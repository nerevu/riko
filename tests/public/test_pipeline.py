# vim: sw=4:ts=4:expandtab
"""Provides public tests for building and running a ``Pipeline``."""

from __future__ import annotations

import gc
import os
import warnings
from concurrent.futures.process import BrokenProcessPool
from contextlib import nullcontext
from functools import partial
from operator import itemgetter, methodcaller
from pathlib import Path
from pickle import dumps, loads  # noqa: S403
from time import perf_counter, sleep
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast, get_args, get_origin

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
from riko.definitions._nodes import ModuleNode, StreamEdge
from riko.definitions._resource_definition import Resource
from riko.definitions._settings import DEF_EXECUTION_SETTINGS
from riko.definitions._workflow_definition import Workflow
from riko.ext import ModuleDefinition, normalize_module_name, processor
from riko.modules._names import Transforms
from riko.runtime._pipeline import Pipeline
from riko.types._enums import Executor, ModuleName
from riko.types._options import CallOptions
from riko.types._pipedef import DagModule, PipeDag
from riko.types._streams import is_stateful_item
from riko.types._workflow import Endpoint
from riko.types.modules import (
    ConfArg,
    Embed,
    FetchRawConf,
    SortConf,
    SortConfRule,
    StrconcatConf,
    StrReplaceConf,
    StrReplaceConfRule,
    TokenizerRawConf,
)
from tests import aresolve, async_test, skipif_issync
from tests._execution import (
    ClosingAsyncIterator,
    RecordingSink,
    agen_source,
    awaitable_source,
    module_workflow,
    registered_modules,
    tag_source,
)
from tests._lifecycle import EXPECTED, ITEMS, VALUE, tokenized
from tests._resources import (
    CREDENTIAL,
    Connection,
    async_cm_factory,
    async_gen_factory,
    check_credential_and_lazy,
    sync_cm_factory,
    sync_gen_factory,
)
from tests._workflows import SPLIT_METHOD_PENDING

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from riko.types._streams import Item, Items
    from riko.types._wrappers import AsyncModuleWrapper, SyncModuleWrapper

LIFECYCLE_SRC = [{"content": "x"}, {"content": "y"}]


def boom():
    raise RuntimeError("boom")
    yield  # pragma: no cover


def _fetch_node(index: int, url: str) -> DagModule:
    """Builds one fetch module entry for the fan-in ``PipeDag``."""
    conf = FetchRawConf({"url": ConfArg(type="url", value=url)})
    return DagModule(id=f"f{index}", type="fetch", conf=conf)


def fanned_in_fetches(*urls: str) -> Pipeline:
    """Builds a pipeline whose single union node merges one fetch per url."""
    fetches = [_fetch_node(index, url) for index, url in enumerate(urls)]
    ports = ["in" if index == 0 else f"in:{index}" for index in range(len(urls))]
    wires = [[f"f{index}", "u", port] for index, port in enumerate(ports)]
    union = DagModule(id="u", type="union")
    dag = PipeDag(modules=[*fetches, union], wires=wires)
    return Pipeline(Workflow.parse(dag))


SRC = [{"content": "a"}, {"content": "b"}, {"content": "c"}]
_FEED = get_path("feed.xml")

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
UNION_PENDING = pytest.mark.xfail(
    raises=AttributeError,
    strict=True,
    reason="merging several pipelines in one call is not available yet",
)
PREDICATE_PENDING = pytest.mark.xfail(
    strict=True, reason="gating a node on a per-item predicate is not available yet"
)


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

    def test_equal_pipelines_hash_alike(self):
        conf = SortConf(rule=SortConfRule(field="x"))
        pipeline = Pipeline.from_module("sort", conf=conf)
        same = Pipeline.from_module("sort", conf=SortConf(rule=SortConfRule(field="x")))
        assert pipeline == same
        assert hash(pipeline) == hash(same)
        assert hash(pipeline.workflow) == hash(same.workflow)

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

    def test_a_module_name_after_a_stream_asks_to_compose_first(self):
        with pytest.raises(TypeError, match="compose the pipeline first"):
            _ = ITEMS | Pipeline.from_module("sort") | "count"  # pyright: ignore[reportOperatorIssue]

    @pytest.mark.parametrize(
        "name", ["_hidden", "keys", "values", "items", "get", "close", "sortt"]
    )
    def test_getattr_rejects_non_builtin_names(self, name):
        with pytest.raises(AttributeError):
            getattr(Pipeline.from_module("fetch"), name)

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

        pipeline = Pipeline() | doubled  # pyright: ignore[reportOperatorIssue]
        assert list(pipeline([{"x": 3}])) == [{"x": 3, "doubled": 6}]


class _Mod(ModuleName):
    HASH = "hash"
    TRUNCATE = "truncate"


_TRUNCATED = Pipeline().pipe(_Mod.TRUNCATE, conf={"count": 1})
ENUM_CHAINS = [
    pytest.param(Pipeline() | _Mod.HASH, "hash-1", 3, id="operator"),
    pytest.param(_TRUNCATED, "truncate-1", 1, id="method"),
]


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

    @pytest.mark.parametrize(("pipeline", "node_id", "count"), ENUM_CHAINS)
    def test_enum_through_chaining(self, pipeline, node_id, count):
        assert pipeline.workflow.nodes[node_id].name == node_id.split("-")[0]
        assert len(list(pipeline(SRC))) == count


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

        sync_pipe = cast("SyncModuleWrapper", double)

        with registered_modules(ModuleDefinition(name="doubler", sync_pipe=sync_pipe)):
            pipeline = [{"x": 1}, {"x": 2}] | Pipeline.from_module("doubler")
            assert list(pipeline) == [{"x": 2}, {"x": 4}]
            assert list(Pipeline().pipe("doubler")([{"x": 10}])) == [{"x": 20}]

    @pytest.mark.parametrize(("seed", "default", "expected"), FIRST_CASES)
    def test_first_returns_the_default_on_an_empty_run(self, seed, default, expected):
        assert Pipeline().first(seed, default=default) == expected

    def test_first_reads_a_self_starting_pipeline_unseeded(self):
        assert tokenized(VALUE).first(default=None) == EXPECTED[0]

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

        async_pipe = cast("AsyncModuleWrapper", adouble)
        definition = ModuleDefinition(name="adoubler", async_pipe=async_pipe)

        with registered_modules(definition):
            pipeline = make_seed() | Pipeline.from_module("adoubler")
            assert [item async for item in pipeline] == [{"x": 2}, {"x": 4}]

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


_PARITY_STRR_CONF = StrReplaceConf({"rule": StrReplaceConfRule(find="c", replace="C")})


def _both(build: Callable[[Pipeline], Pipeline]) -> tuple[Items, Items]:
    """Iterate *build*'s pipeline both ways; return ``(sync_result, async_result)``."""
    pipeline = build(tokenized("a,bb,ccc"))
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


RERUNNABLE = [
    pytest.param(tokenized, id="module-source"),
    pytest.param(partial(fanned_in_fetches, _FEED), id="fan-in"),
]


class TestReiteration:
    @pytest.mark.parametrize("build", RERUNNABLE)
    def test_pipeline_replays(self, build):
        pipeline = build()
        first = list(pipeline)
        assert first
        assert len(list(pipeline)) == len(first)

    def test_a_generator_seed_reruns_when_handed_a_fresh_seed(self):
        pipeline = Pipeline.from_module("hash")
        assert len(list(pipeline(item for item in LIFECYCLE_SRC))) == len(LIFECYCLE_SRC)
        assert len(list(pipeline(item for item in LIFECYCLE_SRC))) == len(LIFECYCLE_SRC)

    def test_chaining_after_a_run_builds_a_fresh_run(self):
        pipeline = tokenized()
        assert len(list(pipeline)) == 3
        assert list(pipeline.count()) == [{"count": 3}]

    def test_iteration_after_partial_iteration_restarts(self):
        pipeline = tokenized()
        stream = pipeline()
        assert next(stream)
        stream.close()
        assert len(list(pipeline)) == 3


class TestAsyncReiteration:
    @async_test
    @pytest.mark.parametrize("build", RERUNNABLE)
    async def test_pipeline_replays(self, build):
        pipeline = build()
        first = [item async for item in pipeline]
        assert first
        assert len([item async for item in pipeline]) == len(first)

    @async_test
    async def test_a_generator_seed_reruns_when_handed_a_fresh_seed(self):
        pipeline = Pipeline.from_module("hash")
        first = [item async for item in pipeline(async_iter(LIFECYCLE_SRC))]
        second = [item async for item in pipeline(async_iter(LIFECYCLE_SRC))]
        assert len(first) == len(second) == len(LIFECYCLE_SRC)

    @async_test
    async def test_iteration_after_partial_iteration_restarts(self):
        pipeline = tokenized()
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

    sync_pipe = cast("SyncModuleWrapper", probe)

    with registered_modules(ModuleDefinition(name="probe", sync_pipe=sync_pipe)):
        yield log


class TestClose:
    def test_close_before_the_first_item_never_runs_the_source(self):
        ran: list[int] = []

        def source():
            ran.append(1)
            yield {"content": "x"}

        stream = Pipeline.from_module("hash")(source())
        stream.close()
        assert ran == []

    @pytest.mark.parametrize("build", RERUNNABLE)
    def test_close_is_idempotent(self, build):
        stream = build()()
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

    def test_early_close_closes_an_upstream_module(self) -> None:
        closed: list[bool] = []

        @tag_source
        def src(_items=None, **_):
            try:
                yield {"x": 1}
                yield {"x": 2}
            finally:
                closed.append(True)

        sync_pipe = cast("SyncModuleWrapper", src)

        with registered_modules(ModuleDefinition(name="itersrc2", sync_pipe=sync_pipe)):
            stream = Pipeline(module_workflow("itersrc2"))()
            assert next(stream) == {"x": 1}
            stream.close()
            assert closed == [True]

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

    @skipif_issync
    def test_leaving_open_closes_a_closeable_async_iterator_seed(self):
        closed: list[str] = []

        with Pipeline.from_module("hash").open(ClosingAsyncIterator(closed)) as stream:
            assert next(stream)
            assert closed == []

        assert closed == ["closed"]

    def test_concurrent_open_runs_are_independent(self):
        pipeline = Pipeline.from_module("hash")

        with pipeline.open(SRC) as left, pipeline.open(SRC[::-1]) as right:
            pairs = [(next(left), next(right)) for _ in SRC]

        lefts, rights = zip(*pairs, strict=True)
        assert [item["content"] for item in lefts] == ["a", "b", "c"]
        assert [item["content"] for item in rights] == ["c", "b", "a"]


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
    @pytest.mark.parametrize("build", RERUNNABLE)
    async def test_close_is_idempotent(self, build):
        stream = build()()
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
    async def test_concurrent_open_runs_are_independent(self):
        pipeline = Pipeline.from_module("hash")

        async with pipeline.open(SRC) as left, pipeline.open(SRC[::-1]) as right:
            pairs = [(await anext(left), await anext(right)) for _ in SRC]

        lefts, rights = zip(*pairs, strict=True)
        assert [item["content"] for item in lefts] == ["a", "b", "c"]
        assert [item["content"] for item in rights] == ["c", "b", "a"]


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


class TestFailure:
    def test_failing_source_propagates(self):
        pipeline = boom() | Pipeline.from_module("hash")

        with pytest.raises(RuntimeError, match="boom"):
            list(pipeline)

    def test_a_failing_pipeline_does_not_break_another_pipelines_run(self):
        pipeline = tokenized()

        with pytest.raises(RuntimeError, match="boom"):
            list(boom() | Pipeline.from_module("hash"))

        assert len(list(pipeline)) == 3

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
    async def test_source_iterates_and_acloses_without_error(self, make_source):
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

    @async_test
    async def test_async_map_rejects_negative_limit(self):
        with pytest.raises(ValueError, match="limit cannot be negative"):
            await async_map(_fail, range(3), -1)


class TestFanIn:
    @pytest.mark.smoke
    def test_fan_in_merges_every_source(self):
        one = len(list(fanned_in_fetches(_FEED)))
        both = len(list(fanned_in_fetches(_FEED, _FEED)))
        assert one
        assert both == 2 * one

    @UNION_PENDING
    def test_union_merges_pipelines(self):
        fetch = Pipeline.from_module("fetch", conf={"url": _FEED})
        merged = Pipeline.union(fetch, fetch)  # pyright: ignore[reportAttributeAccessIssue]
        assert len(list(merged)) == len(list(fanned_in_fetches(_FEED, _FEED)))


class TestAsyncFanIn:
    @pytest.mark.smoke
    @async_test
    async def test_fan_in_merges_every_source(self):
        single = fanned_in_fetches(_FEED)
        doubled = fanned_in_fetches(_FEED, _FEED)
        one = len([item async for item in single])
        both = len([item async for item in doubled])
        assert one
        assert both == 2 * one


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
        sink = RecordingSink()
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
            ("event_sink", RecordingSink()),
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
        ("kwargs", "error", "match"),
        [
            ({"executor": "gpu"}, ValueError, "'gpu'. Expected one of auto, inline"),
            ({"concurrency": 0}, ValueError, None),
            ({"concurrency": "4"}, TypeError, None),
            ({"concurrency": "max"}, TypeError, None),
            ({"ordered": "yes"}, TypeError, None),
            ({"shutdown_timeout": -1}, ValueError, None),
            ({"shutdown_timeout": float("nan")}, ValueError, None),
        ],
    )
    def test_invalid_settings_raise_at_call_time(self, kwargs, error, match):
        with pytest.raises(error, match=match):
            Pipeline.from_module("fetch").with_execution(**kwargs)


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


class TestExecutionSettings:
    """Run-wide settings: concurrency, ordering, and where per-item work runs."""

    @pytest.mark.parametrize(
        ("build", "seed"),
        [
            pytest.param(lambda: tokenized(VALUE), None, id="module-source"),
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
                lambda: tokenized(VALUE),
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

    @pytest.mark.slow
    @pytest.mark.timeout(60)
    def test_a_dead_worker_process_fails_the_run(self) -> None:
        mapped = Pipeline().map(_exit_worker)
        pipeline = mapped.with_execution(executor="process", concurrency=2)

        with pytest.raises(BrokenProcessPool):
            list(pipeline([{"x": 1}, {"x": 2}]))

    @pytest.mark.slow
    def test_a_process_mapped_callable_ignores_unused_context_resources(self) -> None:
        unpicklable = Resource.from_external(SimpleNamespace(fn=lambda: None))
        mapped = Pipeline().map(dict).with_resource("lock", unpicklable)
        pipeline = mapped.with_execution(executor="process", concurrency=2)
        items = [{"x": 1}, {"x": 2}]
        assert sorted(pipeline(items), key=itemgetter("x")) == items


@pytest.mark.slow
@skipif_issync
class TestAsyncBoundedParallel:
    @pytest.mark.anyio
    async def test_parallel_matches_sequential_as_multiset(self):
        pipeline = tokenized("a,bb,ccc,dddd", hashed=True)
        sequential = [item async for item in pipeline]
        parallel = [item async for item in pipeline.with_execution(concurrency=4)]
        assert len(parallel) == len(sequential) == 4
        assert _by_content(parallel) == _by_content(sequential)

    @pytest.mark.anyio
    async def test_ordered_parallel_preserves_order(self):
        pipeline = tokenized("a,bb,ccc,dddd", hashed=True)
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
        """Ensure early closure cleans up a bounded pipeline and its seed."""
        closed: list[bool] = []

        async def unbounded():
            index = 0

            try:
                while True:
                    yield {"content": str(index)}
                    index += 1
            finally:
                closed.append(True)

        hashed = Pipeline.from_module("hash")
        pipeline = hashed.with_execution(concurrency=2, ordered=ordered)
        stream = pipeline(unbounded())
        first = await anext(stream)
        await stream.aclose()
        assert is_mapping(first)
        assert first.get("content")
        assert closed == [True]


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

    pipes = {name: cast("AsyncModuleWrapper", build_branch(name)) for name in BRANCHES}
    definitions = [ModuleDefinition(name=n, async_pipe=p) for n, p in pipes.items()]

    with registered_modules(*definitions):
        yield log


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
        base = Context(test=False)
        derived = base.replace(test=True)

        assert (base.test, derived.test) == (False, True)

    def test_augment_source_mutation_does_not_leak(self):
        tags = ["a"]
        source = {"count": 2, "tags": tags}
        context = Context(inputs=source)
        source["count"] = 99
        tags.append("b")
        assert context.inputs == {"count": 2, "tags": ("a",)}

    def test_roundtrips_through_pickle(self):
        context = Context(mode=ExecutionMode.DESCRIBE, inputs={"count": 2}, test=True)
        restored = cast("Context", loads(dumps(context)))  # noqa: S301

        assert restored.mode is ExecutionMode.DESCRIBE
        assert restored.test is True
        assert restored.inputs == {"count": 2}

        with pytest.raises(AttributeError):
            restored.mode = ExecutionMode.RUN  # pyright: ignore[reportAttributeAccessIssue]


class TestContext:
    @pytest.mark.parametrize("inputs", ["abc", [("a", 1)]])
    def test_non_mapping_inputs_are_rejected(self, inputs: Any):
        with pytest.raises(TypeError, match="Context 'inputs' must be a mapping"):
            Context(inputs=inputs)

    @pytest.mark.parametrize(
        ("mode", "match"),
        [
            pytest.param(5, "Invalid ExecutionMode: 5", id="non-string"),
            pytest.param("bogus", "Invalid ExecutionMode: 'bogus'", id="unknown"),
        ],
    )
    def test_invalid_mode_is_rejected(self, mode: Any, match: str):
        with pytest.raises(ValueError, match=match):
            Context(mode=mode)


class TestResource:
    """
    Keep resource definitions structurally immutable and their constructors strict.

    Fields cannot be reassigned and definition-owned containers are read-only, but
    Riko does not recursively freeze arbitrary referenced values. Do not restore
    public setters; mutable resolved state belongs to the execution layer.
    """

    def test_external_value_fields_are_read_only(self):
        resource = Resource.from_external(Connection())

        with pytest.raises(AttributeError):
            resource.value = object()  # pyright: ignore[reportAttributeAccessIssue]

        with pytest.raises(AttributeError):
            resource.credential = "other"  # pyright: ignore[reportAttributeAccessIssue]

        with pytest.raises(AttributeError):
            resource.lazy = True  # pyright: ignore[reportAttributeAccessIssue]

    def test_referenced_value_is_not_frozen(self):
        connection = Connection()
        resource = Resource.from_external(connection)
        connection.opened = False
        assert resource.value is connection

        if isinstance(resource.value, Connection):
            assert resource.value.closed

    @pytest.mark.parametrize(
        "factory",
        [sync_gen_factory, async_gen_factory, sync_cm_factory, async_cm_factory],
    )
    def test_credential_and_lazy_carried(self, factory):
        context = Context().with_resource(
            "factory", factory, credential=CREDENTIAL, lazy=True
        )
        resource = context.resources["factory"]
        check_credential_and_lazy(resource)

        resource = Resource.from_lifecycle(factory, credential=CREDENTIAL, lazy=True)
        check_credential_and_lazy(resource)

        resource = Resource.from_factory(factory, credential=CREDENTIAL, lazy=True)
        check_credential_and_lazy(resource)

    @pytest.mark.parametrize(
        "factory",
        [sync_gen_factory, async_gen_factory, sync_cm_factory, async_cm_factory],
    )
    def test_lifecycle_factory_is_not_a_value(self, factory):
        with pytest.raises(TypeError, match="Expected a resolved resource"):
            Resource(factory)

        with pytest.raises(TypeError, match="Expected a resolved resource"):
            Resource.from_external(factory)

        with pytest.raises(TypeError, match="Cleanup is not allowed"):
            Resource.from_factory(factory, cleanup=False)


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

    sync_pipe = cast("SyncModuleWrapper", read)

    with registered_modules(ModuleDefinition(name=READER, sync_pipe=sync_pipe)):
        yield READER


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
        stream = iter(tokenized(VALUE).publish(events))

        assert next(stream) == EXPECTED[0]
        assert seen == EXPECTED[:1]
        assert next(stream) == EXPECTED[1]
        assert seen == EXPECTED[:2]

    def test_every_subscription_receives_the_whole_batch_in_order(self):
        first_seen: list[object] = []
        second_seen: list[object] = []
        first = Pipeline.subscribe("receiver1", func=first_seen.append)
        second = Pipeline.subscribe("receiver2", func=second_seen.append)
        sender = tokenized(VALUE).publish(first).publish(second)

        assert list(sender) == EXPECTED
        assert first_seen == EXPECTED
        assert second_seen == EXPECTED

    def test_func_runs_per_item_and_items_pass_through(self):
        seen: list[object] = []
        archive = Pipeline.subscribe("archive", func=seen.append)
        sender = tokenized(VALUE).publish(archive)

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
        assert list(tokenized(VALUE).publish(events)) == EXPECTED

    def test_idle_drain_returns_promptly(self):
        started = perf_counter()
        assert list(Pipeline.subscribe("idle")) == []
        assert perf_counter() - started < 0.5

    def test_draining_after_publishing_starts_a_fresh_empty_run(self):
        events = Pipeline.subscribe("fresh")
        assert list(tokenized(VALUE).publish(events)) == EXPECTED
        assert list(events) == []

    def test_lifecycle_markers_do_not_leak_into_received_items(self):
        seen: list[Item] = []
        events = Pipeline.subscribe("leakcheck", func=seen.append)
        list(tokenized(VALUE).publish(events))

        assert seen == EXPECTED
        assert not any(is_stateful_item(item) for item in seen)


@SPLIT_METHOD_PENDING
class TestSplit:
    """Streaming fan-out into independently consumable branches."""

    def test_both_branches_yield_the_same_first_item(self):
        left, right = tokenized(VALUE).split(2)
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


UNSEEDED_RUNS = [
    pytest.param(list, id="iter"),
    pytest.param(_first_in_open, id="open"),
    pytest.param(Pipeline.first, id="first"),
]


class TestPipelineSeeding:
    """A run takes its seed per call; one whose first node needs input requires it."""

    def test_ror_on_a_stream_seeds_a_run(self):
        hashed = Pipeline.from_module("hash")
        counted = Pipeline.from_module("count")
        assert list(hashed(SRC) | counted) == [{"count": 3}]

    @pytest.mark.parametrize("run", UNSEEDED_RUNS)
    def test_an_unseeded_pipeline_requires_a_seed(self, run):
        pipeline = Pipeline.from_module(Transforms.REVERSE)

        with pytest.raises(InvalidPipelineError, match=r"'reverse-1'.*requires a seed"):
            run(pipeline)

    @async_test
    async def test_an_unseeded_pipeline_requires_a_seed_async(self):
        pipeline = Pipeline.from_module(Transforms.REVERSE)

        with pytest.raises(InvalidPipelineError, match=r"'reverse-1'.*requires a seed"):
            _ = [item async for item in pipeline]

        with pytest.raises(InvalidPipelineError, match="requires a seed"):
            await pipeline.afirst()


def _is_unclosed_run_warning(warning: warnings.WarningMessage) -> bool:
    return "unclosed pipeline run" in str(warning.message)


def _start_and_drop(pipeline: Pipeline) -> None:
    stream = pipeline(SRC)
    next(stream)


FINISHES = [
    pytest.param(list, id="finished"),
    pytest.param(methodcaller("close"), id="closed"),
]


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

    @pytest.mark.parametrize("finish", FINISHES)
    def test_a_finished_or_closed_stream_yields_nothing_more(self, finish):
        stream = Pipeline()(SRC)
        assert next(stream) == SRC[0]
        finish(stream)
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
