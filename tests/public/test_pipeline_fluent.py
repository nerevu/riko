# vim: sw=4:ts=4:expandtab
"""
Structural tests for the immutable fluent authoring surface on ``Pipeline``.

These cover spec derivation only: each fluent operation returns a new ``Pipeline``
whose spec shares the prior structure. No node runs here except the deferred-``map``
tripwire, which is expected to fail until callable pipes land.
"""

from dataclasses import asdict
from typing import get_args, get_origin

import pytest

from riko import Pipeline
from riko.base.exceptions import InvalidPipelineError
from riko.definitions._workflow import ModuleNode, StreamEdge, WorkflowSpec
from riko.types._guards import is_mapping
from riko.types._workflow import Endpoint
from riko.types.modules import (
    ConfArg,
    Embed,
    ModuleOptions,
    SortConf,
    SortConfRule,
    TokenizerRawConf,
)
from tests import async_test

_SORT_CONF_RULE = SortConfRule(dir="desc")
_SORT_CONF = SortConf({"rule": _SORT_CONF_RULE})
_OPTIONS = ModuleOptions(emit=True, field="title")

tokenizer_conf = TokenizerRawConf(delimiter=ConfArg(type="text", value=" "))
_EMBED = Embed(name="tokenizer", conf=tokenizer_conf)


def _spec():
    node = Pipeline.from_module("fetch").spec.nodes["fetch-1"]
    return WorkflowSpec(
        nodes={node.id: node}, outputs={"default": Endpoint(node.id, "out")}, inputs={}
    )


def test_module_seed_builds_single_node_spec():
    flow = Pipeline.from_module("fetch")
    assert sorted(flow.spec.nodes) == ["fetch-1"]
    assert flow.spec.outputs["default"] == Endpoint("fetch-1", "out")
    assert flow.spec.edges == ()
    assert flow.spec.isvalid
    assert flow.source is None


def test_spec_constructor_is_canonical():
    spec = _spec()
    assert Pipeline(spec).spec is spec


def test_empty_seed_builds_template():
    flow = Pipeline()
    assert dict(flow.spec.nodes) == {}
    assert flow.source is None
    assert not flow.spec.isvalid


def test_items_seed_builds_template():
    items = [{"x": 1}]
    flow = Pipeline(source=items)
    assert dict(flow.spec.nodes) == {}
    assert flow.source is items
    assert not flow.spec.isvalid


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

    assert sorted(p2.spec.nodes) == ["fetch-1", "sort-1"]
    assert p2.spec.outputs["default"] == Endpoint("sort-1", "out")
    expected = StreamEdge(Endpoint("fetch-1", "out"), Endpoint("sort-1", "in"))
    assert p2.spec.edges == (expected,)
    p2.spec.validate()


def test_pipe_leaves_prior_pipeline_unchanged():
    p1 = Pipeline.from_module("fetch")
    p2 = p1.pipe("sort")

    assert sorted(p1.spec.nodes) == ["fetch-1"]
    assert p1.spec.outputs["default"] == Endpoint("fetch-1", "out")
    assert p2 is not p1


def test_pipe_shares_prior_node_identity():
    p1 = Pipeline.from_module("fetch")
    p2 = p1.pipe("sort")
    assert p2.spec.nodes["fetch-1"] is p1.spec.nodes["fetch-1"]


def test_getattr_chains_sort():
    flow = Pipeline.from_module("fetch").sort(conf=_SORT_CONF)
    assert flow.spec.nodes["sort-1"].name == "sort"


def test_getattr_chains_filter():
    flow = Pipeline.from_module("fetch").filter(conf={"rule": []})
    assert flow.spec.nodes["filter-1"].name == "filter"


@pytest.mark.parametrize("name", ["_hidden", "keys", "values", "items", "get"])
def test_getattr_rejects_reserved_names(name):
    with pytest.raises(AttributeError):
        getattr(Pipeline.from_module("fetch"), name)


def test_or_chains_str():
    flow = Pipeline.from_module("fetch") | "sort"
    assert sorted(flow.spec.nodes) == ["fetch-1", "sort-1"]


def test_or_chains_name_conf_pair():
    flow = Pipeline.from_module("fetch") | ("sort", _SORT_CONF)
    node = flow.spec.nodes["sort-1"]
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
    flow = Pipeline.from_module("itembuilder").loop(embed=_EMBED, options=_OPTIONS)
    node = flow.spec.nodes["loop-1"]
    _assert_embed(node)
    assert isinstance(node, ModuleNode)
    assert node.conf == {}


def test_or_copies_a_loop_template_embed_and_options():
    template = Pipeline.from_module("loop", embed=_EMBED, options=_OPTIONS)
    flow = Pipeline.from_module("itembuilder") | template
    _assert_embed(flow.spec.nodes["loop-1"])


def test_or_chains_single_module_template():
    flow = Pipeline.from_module("fetch") | Pipeline.from_module("sort")
    assert sorted(flow.spec.nodes) == ["fetch-1", "sort-1"]


def test_or_rejects_multi_node_template():
    template = Pipeline.from_module("a").pipe("b")
    with pytest.raises(InvalidPipelineError):
        _ = Pipeline.from_module("fetch") | template


def test_or_rejects_unsupported_operand():
    with pytest.raises(TypeError):
        _ = Pipeline.from_module("fetch") | 3


def test_ror_seeds_source():
    items = [{"x": 1}]
    flow = items | Pipeline.from_module("sort")
    assert flow.source is items
    assert sorted(flow.spec.nodes) == ["sort-1"]


def test_ror_seeds_async_stream():
    async def stream():
        yield {"x": 1}

    source = stream()
    flow = source | Pipeline.from_module("sort")
    assert flow.source is source


def test_ror_rejects_reseeding():
    with pytest.raises(TypeError):
        _ = [{"x": 1}] | Pipeline(source=[{"y": 1}])


def test_duplicate_names_mint_unique_ids():
    flow = Pipeline.from_module("sort").pipe("sort")
    assert sorted(flow.spec.nodes) == ["sort-1", "sort-2"]


def test_iterating_source_only_pipeline_raises():
    with pytest.raises(InvalidPipelineError):
        list(Pipeline(source=[{"x": 1}]))


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

    flow = Pipeline(source=[{"x": 1}, {"x": 2}]).map(double)

    assert isinstance(flow, Pipeline)
    assert list(flow) == [{"x": 2}, {"x": 4}]
