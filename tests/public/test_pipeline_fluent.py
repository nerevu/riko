# vim: sw=4:ts=4:expandtab
"""
Tests the immutable fluent authoring surface on ``Pipeline``.

Most cases cover workflow derivation only: each fluent operation returns a new
``Pipeline`` whose workflow shares the prior structure. A handful run the derived
pipeline where the point is that two authoring forms produce the same items.
"""

from dataclasses import asdict
from typing import get_args, get_origin

import pytest

from riko import Pipeline
from riko.base.exceptions import EmptyPipelineError, InvalidPipelineError, PipelineError
from riko.definitions._workflow import ModuleNode, StreamEdge, Workflow
from riko.definitions.modules import normalize_module_name
from riko.types._enums import ModuleName
from riko.types._guards import is_mapping
from riko.types._workflow import Endpoint
from riko.types.modules import (
    ConfArg,
    Embed,
    ModuleOptions,
    SortConf,
    SortConfRule,
    TokenizerConf,
    TokenizerRawConf,
)
from tests import async_test

_SORT_CONF_RULE = SortConfRule(dir="desc")
_SORT_CONF = SortConf({"rule": _SORT_CONF_RULE})
_OPTIONS = ModuleOptions(emit=True, field="title")

SRC = [{"content": "a"}, {"content": "b"}, {"content": "c"}]


class _Mod(ModuleName):
    HASH = "hash"
    TRUNCATE = "truncate"


tokenizer_conf = TokenizerRawConf(delimiter=ConfArg(type="text", value=" "))
_EMBED = Embed(name="tokenizer", conf=tokenizer_conf)


def _spec():
    node = Pipeline.from_module("fetch").workflow.nodes["fetch-1"]
    return Workflow(
        nodes={node.id: node}, outputs={"default": Endpoint(node.id, "out")}, inputs={}
    )


def test_module_seed_builds_single_node_spec():
    pipeline = Pipeline.from_module("fetch")
    assert sorted(pipeline.workflow.nodes) == ["fetch-1"]
    assert pipeline.workflow.outputs["default"] == Endpoint("fetch-1", "out")
    assert pipeline.workflow.edges == ()
    assert pipeline.workflow.isvalid
    assert pipeline.source is None


def test_spec_constructor_is_canonical():
    workflow = _spec()
    assert Pipeline(workflow).workflow is workflow


def test_empty_seed_builds_template():
    pipeline = Pipeline()
    assert dict(pipeline.workflow.nodes) == {}
    assert pipeline.source is None
    assert not pipeline.workflow.isvalid


def test_items_seed_builds_template():
    items = [{"x": 1}]
    pipeline = Pipeline(source=items)
    assert dict(pipeline.workflow.nodes) == {}
    assert pipeline.source is items
    assert not pipeline.workflow.isvalid


@pytest.mark.parametrize(
    "make",
    [
        lambda: Pipeline([{"x": 1}]),  # pyright: ignore[reportArgumentType]
        lambda: Pipeline("fetch"),  # pyright: ignore[reportArgumentType]
        lambda: Pipeline(Pipeline.from_module("sort")),  # pyright: ignore[reportArgumentType]
    ],
    ids=["items", "module-name", "pipeline"],
)
def test_non_spec_positional_rejected(make):
    with pytest.raises(TypeError):
        make()


def test_pipe_appends_node_and_edge():
    p1 = Pipeline.from_module("fetch")
    p2 = p1.pipe("sort", conf=_SORT_CONF)

    assert sorted(p2.workflow.nodes) == ["fetch-1", "sort-1"]
    assert p2.workflow.outputs["default"] == Endpoint("sort-1", "out")
    expected = StreamEdge(Endpoint("fetch-1", "out"), Endpoint("sort-1", "in"))
    assert p2.workflow.edges == (expected,)
    p2.workflow.validate()


def test_pipe_leaves_prior_pipeline_unchanged():
    p1 = Pipeline.from_module("fetch")
    p2 = p1.pipe("sort")

    assert sorted(p1.workflow.nodes) == ["fetch-1"]
    assert p1.workflow.outputs["default"] == Endpoint("fetch-1", "out")
    assert p2 is not p1


def test_pipe_shares_prior_node_identity():
    p1 = Pipeline.from_module("fetch")
    p2 = p1.pipe("sort")
    assert p2.workflow.nodes["fetch-1"] is p1.workflow.nodes["fetch-1"]


def test_getattr_chains_sort():
    pipeline = Pipeline.from_module("fetch").sort(conf=_SORT_CONF)
    assert pipeline.workflow.nodes["sort-1"].name == "sort"


def test_getattr_chains_filter():
    pipeline = Pipeline.from_module("fetch").filter(conf={"rule": []})
    assert pipeline.workflow.nodes["filter-1"].name == "filter"


@pytest.mark.parametrize("name", ["_hidden", "keys", "values", "items", "get"])
def test_getattr_rejects_reserved_names(name):
    with pytest.raises(AttributeError):
        getattr(Pipeline.from_module("fetch"), name)


def test_or_chains_str():
    pipeline = Pipeline.from_module("fetch") | "sort"
    assert sorted(pipeline.workflow.nodes) == ["fetch-1", "sort-1"]


def test_or_chains_name_conf_pair():
    pipeline = Pipeline.from_module("fetch") | ("sort", _SORT_CONF)
    node = pipeline.workflow.nodes["sort-1"]
    assert isinstance(node, ModuleNode)
    node_conf_rule = node.conf.get("rule")
    assert is_mapping(node_conf_rule)
    assert dict(node_conf_rule) == asdict(_SORT_CONF_RULE)


def _assert_embed(node):
    """Confirms a node carries the tokenizer embed and its typed configuration."""
    assert isinstance(node, ModuleNode)
    assert node.embed is not None
    assert node.embed["name"] == "tokenizer"
    assert dict(node.embed["conf"]) == {"delimiter": {"type": "text", "value": " "}}
    assert node.options == _OPTIONS


def test_chained_loop_carries_its_embed_and_options():
    pipeline = Pipeline.from_module("itembuilder").loop(embed=_EMBED, options=_OPTIONS)
    node = pipeline.workflow.nodes["loop-1"]
    _assert_embed(node)
    assert isinstance(node, ModuleNode)
    assert node.conf == {}


def test_or_copies_a_loop_template_embed_and_options():
    template = Pipeline.from_module("loop", embed=_EMBED, options=_OPTIONS)
    pipeline = Pipeline.from_module("itembuilder") | template
    _assert_embed(pipeline.workflow.nodes["loop-1"])


def test_or_chains_single_module_template():
    pipeline = Pipeline.from_module("fetch") | Pipeline.from_module("sort")
    assert sorted(pipeline.workflow.nodes) == ["fetch-1", "sort-1"]


def test_or_rejects_multi_node_template():
    template = Pipeline.from_module("a").pipe("b")
    with pytest.raises(InvalidPipelineError):
        _ = Pipeline.from_module("fetch") | template


def test_or_rejects_unsupported_operand():
    with pytest.raises(TypeError):
        _ = Pipeline.from_module("fetch") | 3


def test_or_string_matches_attribute_chaining():
    via_or = list(Pipeline(source=SRC) | "hash")
    via_attr = list(Pipeline(source=SRC).hash())
    assert via_or == via_attr
    assert len(via_or) == 3


def test_ror_preserves_definitional_conf_and_options():
    conf = TokenizerConf({"delimiter": " "})
    template = Pipeline.from_module("tokenizer", conf=conf, options={"emit": False})
    primed = SRC | template
    node = primed.workflow.nodes["tokenizer-1"]
    assert isinstance(node, ModuleNode)
    assert primed.source is SRC
    assert dict(node.conf) == conf
    assert node.options == {"emit": False}


def test_ror_seeds_source():
    items = [{"x": 1}]
    pipeline = items | Pipeline.from_module("sort")
    assert pipeline.source is items
    assert sorted(pipeline.workflow.nodes) == ["sort-1"]


def test_ror_seeds_async_stream():
    async def stream():
        yield {"x": 1}

    source = stream()
    pipeline = source | Pipeline.from_module("sort")
    assert pipeline.source is source


def test_ror_rejects_reseeding():
    with pytest.raises(TypeError):
        _ = [{"x": 1}] | Pipeline(source=[{"y": 1}])


def test_duplicate_names_mint_unique_ids():
    pipeline = Pipeline.from_module("sort").pipe("sort")
    assert sorted(pipeline.workflow.nodes) == ["sort-1", "sort-2"]


def test_iterating_a_source_only_pipeline_streams_the_source():
    assert list(Pipeline(source=[{"x": 1}, {"x": 2}])) == [{"x": 1}, {"x": 2}]
    assert list(Pipeline(source={"x": 1})) == [{"x": 1}]


@async_test
async def test_async_iterating_a_source_only_pipeline_streams_the_source():
    async def source():
        yield {"x": 1}

    assert [item async for item in Pipeline(source=source())] == [{"x": 1}]


def test_first_on_an_empty_pipeline_raises_a_lookup_error():
    with pytest.raises(EmptyPipelineError, match="no items") as info:
        Pipeline(source=[]).first()

    assert isinstance(info.value, PipelineError)
    assert isinstance(info.value, LookupError)


def test_first_does_not_leak_stop_iteration_into_an_outer_iterator():
    pipelines = [Pipeline(source=[{"x": 1}]), Pipeline(source=[])]

    with pytest.raises(EmptyPipelineError):
        list(map(Pipeline.first, pipelines))


def test_first_returns_the_default_on_an_empty_pipeline():
    assert Pipeline(source=[]).first(default=None) is None
    assert Pipeline(source=[]).first(default={"x": 0}) == {"x": 0}
    assert Pipeline(source=[{"x": 1}]).first(default=None) == {"x": 1}


@async_test
async def test_afirst_on_an_empty_pipeline_raises_a_lookup_error():
    with pytest.raises(EmptyPipelineError):
        await Pipeline(source=[]).afirst()

    assert await Pipeline(source=[]).afirst(default=None) is None
    assert await Pipeline(source=[{"x": 1}]).afirst() == {"x": 1}


def test_iterating_an_empty_pipeline_raises():
    with pytest.raises(InvalidPipelineError, match="no nodes"):
        list(Pipeline())


def test_iterating_a_split_pipeline_raises_before_running():
    consumed = []

    def source():
        consumed.append(1)
        yield {"x": 1}

    with pytest.raises(InvalidPipelineError, match="splitter"):
        list(source() | Pipeline.from_module("split"))

    assert consumed == []


@async_test
async def test_async_iterating_a_split_pipeline_raises_before_running():
    consumed = []

    def source():
        consumed.append(1)
        yield {"x": 1}

    with pytest.raises(InvalidPipelineError, match="splitter"):
        _ = [item async for item in source() | Pipeline.from_module("split")]

    assert consumed == []


def test_pipeline_is_generic_over_item_type():
    alias = Pipeline[int]

    assert get_origin(alias) is Pipeline
    assert get_args(alias) == (int,)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "owned by the pending callable-pipes work: Pipeline.map(callable) chains "
        "a callable node; today attribute chaining treats 'map' as a module name. "
        "That work also owns concrete item-type threading: the callable's return "
        "type should flow through as the pipeline's item type instead of the current "
        "Pipeline[Any] fallback"
    ),
)
def test_map_chains_a_callable_node() -> None:
    def double(item):
        return {"x": item["x"] * 2}

    pipeline = Pipeline(source=[{"x": 1}, {"x": 2}]).map(double)

    assert isinstance(pipeline, Pipeline)
    assert list(pipeline) == [{"x": 2}, {"x": 4}]


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
