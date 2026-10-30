"""Provides public tests for callable nodes in a ``Pipeline``."""

from __future__ import annotations

from operator import itemgetter
from typing import TYPE_CHECKING, Any, NoReturn, assert_type, cast

import pytest

from riko.bado._backend import checkpoint
from riko.base._exceptions import InvalidPipelineError
from riko.definitions._context import Context
from riko.definitions._nodes import CallableNode
from riko.ext import ModuleDefinition
from riko.runtime._pipeline import Pipeline
from riko.types._enums import IdentityMode
from riko.types._streams import Item
from riko.types.modules import StrReplaceConf, StrReplaceConfRule
from tests import async_test, skipif_issync
from tests._execution import registered_modules
from tests._lifecycle import VALUE, tokenized

if TYPE_CHECKING:
    from collections.abc import Generator, Iterable, Iterator, Mapping

    from riko.types._wrappers import SyncModuleWrapper


_THREAD = {"executor": "thread", "concurrency": 2, "ordered": True}
_PROCESS = {"executor": "process", "concurrency": 2, "ordered": True}
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
    pytest.param({"obj": object()}, "JSON", id="non-json-kwarg"),
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

    @pytest.mark.parametrize("settings", [{}, _THREAD], ids=["inline", "thread"])
    def test_a_seed_of_lists_maps_each_list_whole(self, settings):
        pipeline = Pipeline().map(len).with_execution(**settings)
        assert list(pipeline([[1, 2], [3]])) == [2, 1]

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

    @pytest.mark.parametrize("settings", _EXECUTIONS)
    def test_map_passes_only_bound_keywords(self, settings):
        pipeline = Pipeline().map(_keywords, factor=2)
        contextual = pipeline.with_context(Context(inputs={"q": 1}))
        assert list(contextual.with_execution(**settings)([{"x": 1}])) == [["factor"]]

    def test_maps_declare_each_resource_once_in_order(self):
        pipeline = (
            Pipeline()
            .with_resource("db", _open_db)
            .map(_enrich, resources="db")
            .map(_enrich, resources="db")
        )
        chained = Pipeline().map(len, resources={"a": "db"})
        ordered = chained.map(str, resources=("cache", "db"))

        assert pipeline.workflow.resources == ("db",)
        assert list(pipeline([{"x": 1}])) == [{"x": 1, "owner": 7}]
        assert ordered.workflow.resources == ("db", "cache")
        assert ordered.workflow.isvalid

    def test_map_carries_version_and_identity(self):
        flow = Pipeline().map(len, version="len-v1", identity="derive").workflow
        node = flow.nodes["len-1"]
        assert isinstance(node, CallableNode)
        assert node.version == "len-v1"
        assert node.identity is IdentityMode.DERIVE

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
        assert list(pipeline([1])) == ["1"]

    def test_chaining_yields_the_last_nodes_type(self):
        strings = Pipeline().map(str)
        lengths = strings | Pipeline().map(len)
        assert_type(lengths, Pipeline[int])
        assert_type(strings | "count", Pipeline[Item])
        assert_type(strings.pipe("count"), Pipeline[Item])
        assert_type(strings.count(), Pipeline[Item])

    @skipif_issync
    def test_sync_iteration_bridges_an_async_callable(self):
        pipeline = Pipeline().map(_ascaled, factor=3)
        assert list(pipeline([{"x": 1}, {"x": 2}])) == [3, 6]

    def test_process_executor_runs_a_module_level_callable(self):
        pipeline = Pipeline().map(_scaled).with_execution(**_PROCESS)
        assert list(pipeline([{"x": x} for x in range(4)])) == [0, 2, 4, 6]

    def test_map_extracts_a_field(self):
        pipeline = tokenized(VALUE).map(itemgetter("content"))
        assert isinstance(pipeline, Pipeline)
        assert list(pipeline) == ["once is 1x", "twice is 2x", "thrice is 3x"]

    def test_map_runs_once_per_item_mid_chain(self):
        runs: list[int] = []

        def record(item):
            runs.append(1)
            return item

        pipeline = (
            tokenized(VALUE)
            .strreplace(conf=STRR_CONF, options={"assign": "content"})
            .slugify(options={"assign": "content"})
            .hash(options={"assign": "content"})
            .map(record)
        )
        assert pipeline.first() == {"content": 396558121}
        assert len(runs) == 1

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

    def test_process_executor_rejects_a_lambda_when_planning(self):
        pipeline = Pipeline().map(lambda item: item)
        settings = {"executor": "process", "concurrency": 2}

        with pytest.raises(InvalidPipelineError, match="cannot be pickled"):
            list(pipeline.with_execution(**settings)([{"x": 1}]))

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "rejecting identity modes a one-to-one map cannot honor is not yet "
            "implemented"
        ),
    )
    def test_map_rejects_combine_identity(self):
        with pytest.raises(InvalidPipelineError, match="combine"):
            Pipeline().map(len, identity="combine")

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "callable nodes that resolve without borrowing the registered udf module "
            "are not yet implemented"
        ),
    )
    @skipif_issync
    def test_map_ignores_a_replaced_udf_module(self):
        sync_pipe = cast("SyncModuleWrapper", list)
        definition = ModuleDefinition(name="udf", sync_pipe=sync_pipe)

        with registered_modules(definition, replace=True):
            assert list(Pipeline().map(_ascaled)([{"x": 1}])) == [2]


class TestAsyncCallableNodes:
    @pytest.mark.parametrize("produce", _LISTLIKE_PRODUCERS)
    @async_test
    async def test_a_listlike_item_stays_whole_under_async_mapping(self, produce):
        pipeline = Pipeline().map(produce).map(_count)
        mapped = pipeline.with_execution(concurrency=2)
        assert [item async for item in mapped([{"x": 1}])] == [2]

    @async_test
    async def test_async_map_passes_only_bound_keywords(self):
        pipeline = Pipeline().map(_keywords, factor=2)
        assert [item async for item in pipeline([{"x": 1}])] == [["factor"]]

    @async_test
    async def test_async_iteration_awaits_an_async_callable(self):
        pipeline = Pipeline().map(_ascaled)
        assert [item async for item in pipeline([{"x": 1}, {"x": 2}])] == [2, 4]

    @async_test
    async def test_async_iteration_runs_a_sync_callable(self):
        pipeline = Pipeline().map(len)
        seed = ["hi", "you"]
        stream = pipeline(seed)
        assert [item async for item in stream] == [2, 3]
