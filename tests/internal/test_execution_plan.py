# vim: sw=4:ts=4:expandtab
"""Provides internal tests for building and running execution plans and embeds."""

from __future__ import annotations

import pickle  # noqa: S403
from functools import partial
from itertools import pairwise
from threading import get_ident
from types import NoneType
from typing import TYPE_CHECKING, Any, cast

import pytest
from attrs import evolve

from riko.bado import run
from riko.bado._util import (
    asyncify,
    maybe_aclosing,
    maybe_async,
    maybe_closing,
    syncify,
)
from riko.bado.itertools import as_async
from riko.base._exceptions import InvalidPipelineError, UnsupportedModuleError
from riko.definitions import _inputs as inputs_module
from riko.definitions import _workflow_definition as workflow_definitions
from riko.definitions._context import Context
from riko.definitions._module_definition import ModuleDefinition
from riko.definitions._nodes import CallableNode, ModuleNode, StreamEdge, WriteNode
from riko.definitions._workflow_definition import Workflow
from riko.definitions._wrapping import stamp_wrapper_meta
from riko.execution import _prepared as prepared_module
from riko.execution._adapt import adapt_embed, async_adapt_embed, to_async, to_sync
from riko.execution._async_execution import AsyncExecution
from riko.execution._prepared import (
    AsyncInterface,
    ExecutionPlan,
    PreparedNode,
    PreparedSplitter,
    ResolvedModule,
    SyncInterface,
    _agen_stream_results,
    _gen_stream_results,
)
from riko.execution._sync_execution import SyncExecution
from riko.modules._decorators import Module, processor, splitter
from riko.modules.hash import pipe as hash_pipe
from riko.modules.loop import async_pipe as async_loop
from riko.modules.loop import pipe as loop_pipe
from riko.modules.split import async_pipe as async_split
from riko.modules.split import pipe as split_pipe
from riko.modules.strreplace import pipe as strreplace_pipe
from riko.runtime._module_registry import ModuleRegistry
from riko.runtime._resolver import ResolverDispatcher, dispatcher
from riko.runtime._workflow_pipes import workflow
from riko.runtime._workflow_resolver import workflow_resolver
from riko.types import _frozendict as frozendict_module
from riko.types._enums import BasicCastType, IdentityMode
from riko.types._options import CallOptions
from riko.types._workflow import Endpoint, InputRef, WorkflowIndex
from riko.types.modules import RenameRawConf
from tests import async_test, skipif_sync
from tests._execution import (
    EMPTY,
    OUTPUT_A,
    ClosingAsyncIterator,
    arun_plan,
    build_chain_plan,
    build_dispatcher,
    build_workflow,
    echo_pipe,
    gen_closing_seed,
    module_workflow,
    passthrough_pipe,
    run_plan,
    tag_source,
    tagged_source,
)
from tests._streams import Closable

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable, Generator

    from riko.types._streams import Cascade, Item, Stream
    from riko.types._wrappers import AsyncModuleWrapper, SyncModuleWrapper
    from riko.types.modules import Conf

_ASYNC_PIPE = cast("AsyncModuleWrapper", lambda source, **_: as_async(source or {}))
_BOTH = {"sync_pipe": passthrough_pipe, "async_pipe": _ASYNC_PIPE}
_SYNC_ONLY = {"sync_pipe": passthrough_pipe}
_ASYNC_ONLY = {"async_pipe": _ASYNC_PIPE}
_HASH = ResolvedModule("hash", sync_pipe=hash_pipe)
_COUNT_NO_OUTPUT = build_workflow([ModuleNode(id="n", name="count")], outputs={})
_NODELESS = Workflow(nodes=[], outputs={"default": Endpoint("x", "out")})
_FETCH, _SORT = ModuleNode(id="a", name="fetch"), ModuleNode(id="b", name="sort")


def _split_workflow(splits: int | str | InputRef, port: str) -> Workflow:
    split = ModuleNode(id="s", name="split", conf={"splits": splits})
    edges = (
        StreamEdge(Endpoint("a", "out"), Endpoint("s", "in")),
        StreamEdge(Endpoint("s", port), Endpoint("b", "in")),
    )
    return build_workflow([_FETCH, split, _SORT], edges=edges)


_SPLIT_PAST_COUNT = _split_workflow(2, "out:2")
_NO_SPLITS = _split_workflow(0, "out")


def _get_node(plan: ExecutionPlan, node_id: str) -> PreparedNode:
    node = plan.nodes[node_id]
    assert isinstance(node, PreparedNode)
    return node


def _flagged(func, flag: str) -> Any:
    setattr(func, flag, True)
    return func


def _mismatched(attr: str, sync_value: str, async_value: str) -> dict[str, Any]:
    def sync_pipe(source, **_):
        return iter(source or {})

    def async_pipe(source, **_):
        return as_async(source or {})

    setattr(sync_pipe, attr, sync_value)
    setattr(async_pipe, attr, async_value)
    return {"sync_pipe": sync_pipe, "async_pipe": async_pipe}


_LOOPABLE_SYNC = _flagged(lambda source, **_: iter(source or {}), "loopable")

_SEQUENTIAL_ASYNC = _flagged(
    lambda source, **_: as_async(source or {}), "sequential_inputs"
)
_SYNC_MODULE = ResolvedModule("m", sync_pipe=passthrough_pipe)
_ASYNC_MODULE = ResolvedModule("m", async_pipe=_ASYNC_PIPE)
_BOTH_MODULE = ResolvedModule("m", sync_pipe=passthrough_pipe, async_pipe=_ASYNC_PIPE)
_MAPPED_MODULE = ResolvedModule("m", sync_pipe=_LOOPABLE_SYNC)
_SYNC_SPLITTER = ResolvedModule("split", {"splits": 1}, sync_pipe=split_pipe)

_REPLACE_ITEMS = [{"content": "abc"}, {"content": "aa"}]
_STATIC_REPLACE = cast("Conf", {"rule": [{"find": "a", "replace": "Z"}]})

_DYNAMIC_REPLACE = cast(
    "Conf", {"rule": [{"find": "a", "replace": {"terminal": "rep", "type": "text"}}]}
)

_UPPER = cast("Conf", {"rule": {"transform": "upper"}})
_HASH_FLOW = Workflow(nodes=[ModuleNode(id="a", name="hash")], outputs=OUTPUT_A)
_LOOP_NODE = ModuleNode(id="a", name="loop", embed={"name": "hash", "conf": {}})
_LOOP_FLOW = Workflow(nodes=[_LOOP_NODE], outputs=OUTPUT_A)
_BARE_LOOP = Workflow(nodes=[ModuleNode(id="a", name="loop")], outputs=OUTPUT_A)
_WRITE = WriteNode(id="a", name="write", backend="file", dest="out.csv")
_WRITE_FLOW = Workflow(nodes=[_WRITE], outputs=OUTPUT_A)
_HASH_A = {"a": _HASH}
_HASH_AB = {"a": _HASH, "b": _HASH}
_SYNC, _ASYNC = "sync_interface", "async_interface"


def _stamp_embed(up, *, is_async: bool) -> None:
    stamp_wrapper_meta(
        up,
        name="up",
        module_type="processor",
        subtype="transformer",
        subtypes={"transformer"},
        pollable=False,
        loopable=True,
        is_async=is_async,
    )


def _loop(loop_name="fakeloop", embed_name="up"):
    src = ModuleNode(id="s", name="src")
    loop = ModuleNode(
        id="loop",
        name=loop_name,
        embed={"name": embed_name, "conf": {}},
        options={"emit": True, "count": "first"},
    )
    return Workflow().with_nodes(src, loop)


@tag_source
def _titled_source(_items=None, **_):
    yield {"title": "a"}
    yield {"title": "b"}


def _real_loop_workflow(embed_name="child"):
    return _loop(loop_name="loop", embed_name=embed_name)


SELECTIONS = [
    pytest.param(_BOTH, _SYNC, SyncInterface, passthrough_pipe, id="native-sync"),
    pytest.param(_BOTH, _ASYNC, AsyncInterface, _ASYNC_PIPE, id="native-async"),
    pytest.param(_SYNC_ONLY, _ASYNC, NoneType, None, id="sync-only"),
    pytest.param(_ASYNC_ONLY, _SYNC, NoneType, None, id="async-only"),
]


BUILD_REJECTIONS = [
    pytest.param(_COUNT_NO_OUTPUT, "output", id="validates-the-graph"),
    pytest.param(_NODELESS, "no nodes", id="nodeless-with-outputs"),
    pytest.param(
        _SPLIT_PAST_COUNT,
        r"node 's' has no output port 'out:2'; it produces \('out', 'out:1'\)",
        id="split-port-past-its-count",
    ),
    pytest.param(
        _NO_SPLITS, "node 's' needs at least one split, got 0", id="no-splits"
    ),
    pytest.param(
        _split_workflow("x", "out"),
        "a split count must be an integer, got 'x'",
        id="non-integer-splits",
    ),
]


CONSTRUCTION_REJECTIONS = [
    pytest.param({"nodes": []}, {}, {}, "ExecutionPlan 'workflow'", id="workflow"),
    pytest.param(EMPTY, {"n": 1}, {}, "ExecutionPlan module 'n'", id="unresolved"),
    pytest.param(EMPTY, "abc", {}, "ExecutionPlan 'modules'", id="modules-str"),
    pytest.param(EMPTY, None, {}, "ExecutionPlan 'modules'", id="modules-none"),
    pytest.param(_HASH_FLOW, {}, {}, "modules must match", id="missing"),
    pytest.param(_HASH_FLOW, _HASH_AB, {}, "modules must match", id="extra"),
    pytest.param(_LOOP_FLOW, _HASH_A, {}, "embeds must match", id="embed-missing"),
    pytest.param(_BARE_LOOP, _HASH_A, _HASH_A, "embeds must match", id="embed-extra"),
    pytest.param(_WRITE_FLOW, _HASH_A, {}, "not yet supported", id="non-module"),
]


# A truncate count, its input schemas and given inputs, and how many modules rebuild.
INPUT_REBUILDS = [
    pytest.param(2, {}, None, 0, id="none"),
    pytest.param({"input": "n"}, {"n": {"type": "integer"}}, {"n": 2}, 1, id="one"),
]

NON_SPLITTERS = [
    pytest.param({"sync_pipe": passthrough_pipe}, _SYNC, id="sync"),
    pytest.param({"async_pipe": _ASYNC_PIPE}, _ASYNC, id="async"),
]


def _closing_embed_plan(build, closed: list[str]) -> ExecutionPlan:
    """Builds a sync-only ``loop`` over an async-only embed that ``build`` makes."""
    child = workflow()(lambda _item, context=None, **_: build(closed))
    dispatcher = build_dispatcher(
        ModuleDefinition(name="src", sync_pipe=tagged_source("x")),
        ModuleDefinition(name="loop", sync_pipe=loop_pipe),
        ModuleDefinition(name="child", async_pipe=cast("AsyncModuleWrapper", child)),
    )
    loop = ModuleNode(
        id="loop",
        name="loop",
        embed={"name": "child", "conf": {}},
        options={"emit": True, "count": "all"},
    )
    flow = Workflow().with_nodes(ModuleNode(id="s", name="src"), loop)
    return ExecutionPlan.from_workflow(flow, dispatcher)


async def _gen_closing_rows(closed: list[str]):
    try:
        while True:
            yield {"x": 1}
    finally:
        closed.append("closed")


def _two_output_plan() -> ExecutionPlan:
    """Builds a sync-only ``a`` on ``default`` and an async-only ``b`` on ``other``."""
    dispatcher = build_dispatcher(
        ModuleDefinition(name="s", sync_pipe=passthrough_pipe),
        ModuleDefinition(name="m", async_pipe=_ASYNC_PIPE),
    )
    nodes = [ModuleNode(id="a", name="s"), ModuleNode(id="b", name="m")]
    outputs = {"default": Endpoint("a", "out"), "other": Endpoint("b", "out")}
    return ExecutionPlan.from_workflow(
        Workflow(nodes=nodes, outputs=outputs), dispatcher
    )


# Whether a sync run of the output reads anything through the portal.
PORTAL_USES = [
    pytest.param(_two_output_plan, "default", False, id="sync-only"),
    pytest.param(_two_output_plan, "other", True, id="async-only"),
    pytest.param(
        lambda: _closing_embed_plan(_gen_closing_rows, []),
        "default",
        True,
        id="async-only-embed",
    ),
]


def _chain_plan(*modules: ResolvedModule) -> ExecutionPlan:
    """Builds a plan chaining one node per resolved module."""
    nodes = [ModuleNode(id=f"n{i}", name=m.name) for i, m in enumerate(modules)]
    resolved = {node.id: m for node, m in zip(nodes, modules, strict=True)}
    return ExecutionPlan(Workflow().with_nodes(*nodes), modules=resolved)


_SYNC_CHAIN = partial(_chain_plan, _SYNC_MODULE, _SYNC_MODULE)
_ASYNC_CHAIN = partial(_chain_plan, _ASYNC_MODULE, _ASYNC_MODULE)
_MIXED_CHAIN = partial(_chain_plan, *[_SYNC_MODULE, _ASYNC_MODULE] * 2)
_SPLITTER_CHAIN = partial(_chain_plan, _SYNC_SPLITTER, _BOTH_MODULE)
_MAPPED_CHAIN = partial(_chain_plan, _MAPPED_MODULE, _MAPPED_MODULE)

# How many node threads a sync or an async run may hold at once.
THREAD_DEMANDS = [
    pytest.param(_SYNC_CHAIN, True, 2, id="sync-only-async-run"),
    pytest.param(_SYNC_CHAIN, False, 0, id="sync-only-sync-run"),
    pytest.param(_ASYNC_CHAIN, True, 0, id="async-only-async-run"),
    pytest.param(_ASYNC_CHAIN, False, 2, id="async-only-sync-run"),
    pytest.param(_MIXED_CHAIN, False, 2, id="alternating-sync-run"),
    pytest.param(_SPLITTER_CHAIN, True, 1, id="sync-only-splitter-async-run"),
    pytest.param(_SPLITTER_CHAIN, False, 0, id="sync-only-splitter-sync-run"),
    pytest.param(_MAPPED_CHAIN, True, 0, id="mapped"),
]


class TestExecutionPlan:
    @pytest.mark.parametrize(("build", "is_async", "expected"), THREAD_DEMANDS)
    def test_thread_demand_counts_adapted_nodes(
        self, build, is_async, expected
    ) -> None:
        assert build().get_thread_demand("default", is_async=is_async) == expected

    @pytest.mark.parametrize(("build", "output", "expected"), PORTAL_USES)
    def test_uses_portal_sees_async_only_nodes_and_embeds(
        self, build, output, expected
    ) -> None:
        assert build().uses_portal(output) is expected

    @pytest.mark.parametrize(("pipes", "attr", "kind", "expected"), SELECTIONS)
    def test_build_selects_the_pipe_for_each_mode(
        self, pipes, attr, kind, expected
    ) -> None:
        definition = ModuleDefinition(name="m", **pipes)
        plan = ExecutionPlan.from_workflow(
            module_workflow(), dispatcher=build_dispatcher(definition)
        )
        interface = getattr(plan.nodes["n"], attr)

        assert isinstance(interface, kind)
        assert getattr(interface, "pipe", None) is expected

    def test_an_empty_plan_is_not_self_starting(self) -> None:
        plan = ExecutionPlan.from_workflow(Workflow(), dispatcher)
        assert plan.is_self_starting_output() is False

        with pytest.raises(
            InvalidPipelineError, match="empty workflow requires a seed"
        ):
            plan.require_self_starting_output("default")

    def test_build_does_not_invoke_the_pipe(self) -> None:
        calls: list[int] = []

        def pipe(source, **_):
            calls.append(1)
            return source

        sync_pipe = cast("SyncModuleWrapper", pipe)
        definition = ModuleDefinition(name="m", sync_pipe=sync_pipe)
        ExecutionPlan.from_workflow(
            module_workflow(), dispatcher=build_dispatcher(definition)
        )
        assert calls == []

    def test_execution_plan_indexes_the_workflow_once(self, monkeypatch) -> None:
        # Validation and the plan share the workflow's cached index rather than each
        # re-interpreting its topology.
        calls: list[tuple[object, ...]] = []

        def counting(*args: object) -> WorkflowIndex:
            calls.append(args)
            return WorkflowIndex(*args)  # pyright: ignore[reportArgumentType]

        monkeypatch.setattr(workflow_definitions, "WorkflowIndex", counting)
        ExecutionPlan.from_workflow(module_workflow("count"), dispatcher)
        assert len(calls) == 1

    def test_execution_plan_snapshots_resolution(self) -> None:
        # The plan resolves each node's callable once at build time, so replacing a
        # module afterward does not change what a built plan runs.
        registry = ModuleRegistry()
        registry.register(ModuleDefinition(name="src", sync_pipe=tagged_source("a")))
        dispatcher = ResolverDispatcher(registry, workflow_resolver)
        plan = ExecutionPlan.from_workflow(
            module_workflow("src"), dispatcher=dispatcher
        )
        registry.register(
            ModuleDefinition(name="src", sync_pipe=tagged_source("b")), replace=True
        )

        with SyncExecution() as execution:
            assert list(execution.run(plan)) == [{"t": "a"}]

    def test_build_carries_conf_index_and_resources(self) -> None:
        definition = ModuleDefinition(name="m", sync_pipe=passthrough_pipe)
        node = ModuleNode(id="n", name="m", conf={"url": "x"}, resources={"db": "db"})
        flow = build_workflow([node], resources=("db",))
        dispatcher = build_dispatcher(definition)
        plan = ExecutionPlan.from_workflow(flow, dispatcher=dispatcher)
        prepared = plan.nodes["n"]

        assert prepared.module.conf == {"url": "x"}
        assert set(prepared.resources.values()) == {"db"}
        assert plan.index.outputs["default"].node == "n"

    def test_nodes_pair_workflow_nodes_with_their_modules(self):
        node = ModuleNode(id="a", name="loop", embed={"name": "hash", "conf": {}})
        flow = Workflow(nodes=[node], outputs=OUTPUT_A)
        plan = ExecutionPlan(workflow=flow, modules={"a": _HASH}, embeds={"a": _HASH})
        prepared = _get_node(plan, "a")
        assert (prepared.node, prepared.module, prepared.embed) == (node, _HASH, _HASH)

    def test_a_lone_source_is_the_seed_target(self) -> None:
        dispatcher = build_dispatcher(
            ModuleDefinition(name="src", sync_pipe=tagged_source("a"))
        )
        plan = ExecutionPlan.from_workflow(module_workflow("src"), dispatcher)

        assert plan.require_seed_target("default") == "n"

    def test_inputs_are_only_set_with_the_confs_built_from_them(self):
        conf = cast("Conf", {"attrs": {"key": "q", "value": {"input": "q"}}})
        node = ModuleNode(id="b", name="itembuilder", conf=conf)
        flow = Workflow(input_schemas={"q": {"type": "integer"}}).with_nodes(node)
        plan = ExecutionPlan.from_workflow(flow, dispatcher)
        planned = plan.with_inputs({"q": 5})

        assert planned.inputs == {"q": 5}
        assert planned.modules["b"].conf == {"attrs": {"key": "q", "value": 5}}

        with pytest.raises(TypeError, match="inputs"):
            evolve(plan, inputs={"q": 5})

        with pytest.raises(InvalidPipelineError, match="already built"):
            planned.with_inputs({"q": 6})

    def test_a_run_compiles_each_input_schema_once(self, monkeypatch) -> None:
        compiled = []
        fjs_compile = inputs_module.fjs_compile

        def counted(schema, **kwargs):
            compiled.append(schema)
            return fjs_compile(schema, **kwargs)

        monkeypatch.setattr(inputs_module, "fjs_compile", counted)
        conf = cast("Conf", {"attrs": {"key": "q", "value": {"input": "q"}}})
        node = ModuleNode(id="b", name="itembuilder", conf=conf)
        flow = Workflow(input_schemas={"q": {"type": "integer"}}).with_nodes(node)
        plan = ExecutionPlan.from_workflow(flow, dispatcher)

        with SyncExecution(context=Context(inputs={"q": 5})) as execution:
            assert list(execution.run(plan)) == [{"q": 5}]

        assert compiled == [{"type": "integer"}]

    @pytest.mark.parametrize(("count", "schemas", "given", "rebuilt"), INPUT_REBUILDS)
    def test_a_run_rebuilds_only_the_modules_that_read_an_input(
        self, monkeypatch, count, schemas, given, rebuilt
    ) -> None:
        nodes = [
            ModuleNode(id="a", name="hash"),
            ModuleNode(id="b", name="truncate", conf={"count": count}),
            ModuleNode(id="c", name="hash"),
        ]
        edges = [
            StreamEdge(Endpoint("a", "out"), Endpoint("b", "in")),
            StreamEdge(Endpoint("b", "out"), Endpoint("c", "in")),
        ]
        outputs = {"default": Endpoint("c", "out")}
        flow = Workflow(nodes, outputs, schemas, edges)
        plan = ExecutionPlan.from_workflow(flow, dispatcher)
        validated, positional = [], []
        validate = ExecutionPlan.validate
        gen_positional_names = prepared_module.gen_positional_names

        def counted_validate(self: ExecutionPlan) -> None:
            validated.append(self)
            validate(self)

        def counted_names(*args: Any) -> Any:
            positional.append(args)
            return gen_positional_names(*args)

        monkeypatch.setattr(ExecutionPlan, "validate", counted_validate)
        monkeypatch.setattr(prepared_module, "gen_positional_names", counted_names)
        seed = [{"x": 1}, {"x": 2}, {"x": 3}]

        with SyncExecution(context=Context(inputs=given)) as execution:
            assert len(list(execution.run(plan, seed=seed))) == 2

        # Each rebuilt module reads the names its sync and async pipes fill by position.
        assert (len(validated), len(positional)) == (rebuilt, 2 * rebuilt)

    def test_each_module_name_resolves_once_per_plan(self, monkeypatch) -> None:
        names = ["hash", "truncate", "hash", "truncate"]
        ids = "abcd"
        nodes = [ModuleNode(id=i, name=n) for i, n in zip(ids, names, strict=True)]
        edges = [
            StreamEdge(Endpoint(source, "out"), Endpoint(target, "in"))
            for source, target in pairwise(ids)
        ]
        flow = Workflow(nodes, {"default": Endpoint("d", "out")}, edges=edges)
        validated, lookups = [], []
        validate, resolve = ResolverDispatcher.validate, ResolverDispatcher.resolve

        def counted_validate(self: ResolverDispatcher, name: str) -> None:
            validated.append(name)
            validate(self, name)

        def counted_resolve(
            self: ResolverDispatcher, name: str, is_async: bool = False
        ) -> Any:
            lookups.append((name, is_async))
            return resolve(self, name, is_async)

        monkeypatch.setattr(ResolverDispatcher, "validate", counted_validate)
        monkeypatch.setattr(ResolverDispatcher, "resolve", counted_resolve)
        plan = ExecutionPlan.from_workflow(flow, dispatcher)
        expected = [("hash", False), ("hash", True), ("truncate", False)]
        expected.append(("truncate", True))

        assert plan.modules["c"].sync_pipe is plan.modules["a"].sync_pipe
        assert (sorted(validated), sorted(lookups)) == (["hash", "truncate"], expected)

    def test_a_plan_never_refreezes_a_frozen_conf(self, monkeypatch) -> None:
        nodes = [
            ModuleNode(id="a", name="truncate", conf={"count": 2}),
            ModuleNode(
                id="b",
                name="rename",
                conf=RenameRawConf(
                    {
                        "rule": [
                            {
                                "field": {"type": "text", "value": "x"},
                                "newval": {"type": "text", "value": "y"},
                            }
                        ]
                    }
                ),
            ),
        ]
        edges = [StreamEdge(Endpoint("a", "out"), Endpoint("b", "in"))]
        flow = Workflow(nodes, {"default": Endpoint("b", "out")}, edges=edges)
        kept, refrozen = [], []
        freeze_value = frozendict_module._freeze_value

        def counted(value: Any, *args: Any, **kwargs: Any) -> Any:
            result = freeze_value(value, *args, **kwargs)

            if isinstance(value, frozendict_module.FrozenDict):
                (kept if result is value else refrozen).append(value)

            return result

        monkeypatch.setattr(frozendict_module, "_freeze_value", counted)
        plan = ExecutionPlan.from_workflow(flow, dispatcher)

        with SyncExecution() as execution:
            assert len(list(execution.run(plan, seed=[{"x": 1}] * 3))) == 2

        assert (bool(kept), refrozen) == (True, [])

    def test_build_plan_accepts_fan_out_from_one_source_port(self) -> None:
        dispatcher = build_dispatcher(
            ModuleDefinition(name="src", sync_pipe=tagged_source("a")),
            ModuleDefinition(name="sink", sync_pipe=passthrough_pipe),
        )
        a = ModuleNode(id="a", name="src")
        b = ModuleNode(id="b", name="sink")
        c = ModuleNode(id="c", name="sink")
        edges = (
            StreamEdge(Endpoint("a", "out"), Endpoint("b", "in")),
            StreamEdge(Endpoint("a", "out"), Endpoint("c", "in")),
        )
        flow = build_workflow(
            [a, b, c], edges=edges, outputs={"default": Endpoint("b", "out")}
        )
        plan = ExecutionPlan.from_workflow(flow, dispatcher=dispatcher)

        assert plan.workflow.get_family_sources()["a", "out"] == 2

    @pytest.mark.parametrize("splits", [3, "3"], ids=["integer", "numeric-string"])
    def test_build_plan_prepares_a_split_node_as_a_splitter(self, splits) -> None:
        flow = _split_workflow(splits, "out:2")
        plan = ExecutionPlan.from_workflow(flow, dispatcher)
        node = plan.nodes["s"]

        assert isinstance(node, PreparedSplitter)
        assert node.output_ports == ("out", "out:1", "out:2")
        assert isinstance(plan.nodes["b"], PreparedNode)

    def test_build_plan_checks_a_split_count_input_once_it_is_given(self) -> None:
        flow = evolve(
            _split_workflow({"input": "n"}, "out:2"),
            input_schemas={"n": {"type": "integer"}},
        )
        plan = ExecutionPlan.from_workflow(flow, dispatcher)
        node = plan.with_inputs({"n": 3}).nodes["s"]

        assert isinstance(node, PreparedSplitter)
        assert node.output_ports == ("out", "out:1", "out:2")

        with pytest.raises(InvalidPipelineError, match="no output port 'out:2'"):
            plan.with_inputs({"n": 2})

    @pytest.mark.parametrize(("flow", "match"), BUILD_REJECTIONS)
    def test_build_rejects_an_invalid_graph(self, flow, match) -> None:
        with pytest.raises(InvalidPipelineError, match=match):
            ExecutionPlan.from_workflow(flow, dispatcher)

    def test_build_rejects_unresolved_module(self) -> None:
        flow = module_workflow(name="does_not_exist_module")

        with pytest.raises(UnsupportedModuleError):
            ExecutionPlan.from_workflow(flow, dispatcher=build_dispatcher())

    @pytest.mark.parametrize(("pipes", "attr"), NON_SPLITTERS)
    def test_a_splitter_rejects_a_module_that_is_not_a_splitter(
        self, pipes, attr
    ) -> None:
        module = ResolvedModule("m", **pipes)
        node = PreparedSplitter(ModuleNode(id="s", name="m"), module)

        with pytest.raises(InvalidPipelineError, match="is not a splitter"):
            getattr(node, attr)

    @pytest.mark.parametrize(
        ("flow", "modules", "embeds", "match"), CONSTRUCTION_REJECTIONS
    )
    def test_construction_is_validated(
        self, flow: Any, modules: Any, embeds: Any, match: str
    ):
        with pytest.raises(InvalidPipelineError, match=match):
            ExecutionPlan(workflow=flow, modules=modules, embeds=embeds)

    @pytest.mark.xfail(
        strict=True,
        raises=InvalidPipelineError,
        reason="declared output ports for splitter modules are not yet implemented: "
        "the plan reads every splitter's port count from its `splits` conf",
    )
    def test_build_plan_reads_an_extension_splitters_declared_ports(self) -> None:
        @splitter(objectify=False)
        def three_way(stream: Stream, _: object, __: object, **___: object) -> Cascade:
            items = list(stream)
            return iter([iter(items), iter(items), iter(items)])

        dispatcher = build_dispatcher(
            ModuleDefinition(name="src", sync_pipe=tagged_source("a")),
            ModuleDefinition(name="three_way", sync_pipe=three_way),
            ModuleDefinition(name="sink", sync_pipe=passthrough_pipe),
        )
        nodes = [
            ModuleNode(id="a", name="src"),
            ModuleNode(id="s", name="three_way", conf={"ways": 3}),
            ModuleNode(id="b", name="sink"),
        ]
        edges = (
            StreamEdge(Endpoint("a", "out"), Endpoint("s", "in")),
            StreamEdge(Endpoint("s", "out:2"), Endpoint("b", "in")),
        )
        flow = build_workflow(nodes, edges=edges)
        plan = ExecutionPlan.from_workflow(flow, dispatcher=dispatcher)
        node = plan.nodes["s"]

        assert isinstance(node, PreparedSplitter)
        assert node.output_ports == ("out", "out:1", "out:2")

    @pytest.mark.xfail(
        strict=True,
        raises=pytest.fail.Exception,
        reason="rejecting a positional input into a module that declares no positional "
        "ports is not yet implemented: the input is accepted and silently ignored",
    )
    def test_build_plan_rejects_undeclared_positional_input(self) -> None:
        dispatcher = build_dispatcher(
            ModuleDefinition(name="src", sync_pipe=tagged_source("a")),
            ModuleDefinition(name="sink", sync_pipe=passthrough_pipe),
        )
        a = ModuleNode(id="a", name="src")
        b = ModuleNode(id="b", name="src")
        s = ModuleNode(id="s", name="sink")
        edges = (
            StreamEdge(Endpoint("a", "out"), Endpoint("s", "in")),
            StreamEdge(Endpoint("b", "out"), Endpoint("s", "in:1")),
        )
        flow = build_workflow([a, b, s], edges=edges)

        with pytest.raises(InvalidPipelineError, match="positional"):
            ExecutionPlan.from_workflow(flow, dispatcher=dispatcher)


# The invariants live on the resolved module itself, so every construction path
# (plan build, embeds, direct construction) is covered.
INVALID_MODULES = [
    pytest.param(
        {
            "sync_pipe": passthrough_pipe,
            "async_pipe": cast("AsyncModuleWrapper", passthrough_pipe),
        },
        "both sync and async",
        id="one-callable",
    ),
    pytest.param({}, "neither a sync nor an async", id="no-callable"),
    pytest.param(
        {"sync_pipe": _LOOPABLE_SYNC, "async_pipe": _ASYNC_PIPE},
        "disagree on 'loopable'",
        id="mismatched-loopable",
    ),
    pytest.param(
        {"sync_pipe": passthrough_pipe, "async_pipe": async_split},
        "'splitter'",
        id="sync-non-splitter",
    ),
    pytest.param(
        {"sync_pipe": split_pipe, "async_pipe": _ASYNC_PIPE},
        "'splitter'",
        id="async-non-splitter",
    ),
    pytest.param(
        {"sync_pipe": passthrough_pipe, "async_pipe": _SEQUENTIAL_ASYNC},
        "disagree on 'sequential_inputs'",
        id="mismatched-sequential-inputs",
    ),
    pytest.param(
        _mismatched("subtype", "source", "transformer"),
        "disagree on 'subtype'",
        id="mismatched-subtype",
    ),
    pytest.param(
        _mismatched("type", "processor", "operator"),
        "disagree on 'type'",
        id="mismatched-type",
    ),
    pytest.param(
        _mismatched("identity", "preserve", "derive"),
        "disagree on 'identity'",
        id="mismatched-identity",
    ),
]


class TestResolvedModule:
    @pytest.mark.parametrize(("pipes", "match"), INVALID_MODULES)
    def test_resolved_module_refuses_invalid_pipes(self, pipes, match) -> None:
        with pytest.raises(InvalidPipelineError, match=match):
            ResolvedModule("m", {}, **pipes)


class _EmbedStub:
    """Carries the discovery metadata an adapter must copy onto its wrapper."""

    name = "up"
    type = "processor"
    subtype = "transformer"
    subtypes = frozenset({"transformer"})
    pollable = False
    loopable = True
    is_async = True
    sequential_inputs = False

    def __call__(self, item=None, **kwargs):
        return iter(())


async def _unused_worker[R, **P](
    func: Callable[P, R], /, *args: P.args, **kwargs: P.kwargs
) -> R:
    return func(*args, **kwargs)


ADAPTERS = [
    pytest.param(
        lambda stub: adapt_embed(
            cast("AsyncModuleWrapper", stub), partial(to_sync, syncify)
        ),
        True,
        id="for-sync",
    ),
    pytest.param(
        lambda stub: async_adapt_embed(cast("SyncModuleWrapper", stub), _unused_worker),
        False,
        id="for-async",
    ),
]


def _lone_loop(embed_conf=None):
    loop = ModuleNode(
        id="loop",
        name="fakeloop",
        embed={"name": "up", "conf": embed_conf or {}},
        options={"emit": True, "count": "first"},
    )
    return build_workflow([loop])


def _build_async_embed():
    """Decorate a fresh async processor parser so it carries real pipe metadata."""

    async def shout(item, extraction, objconf, **kwargs):
        return {"up": str(item["t"]).upper()}

    return cast(
        "AsyncModuleWrapper", processor(is_async=True, ptype=BasicCastType.NONE)(shout)
    )


def _async_child(produced: list[int], closed: list[str]):
    async def child(tag: str):
        try:
            for index in range(50):
                produced.append(index)
                yield {"content": f"{tag}{index}"}
        finally:
            closed.append(tag)

    def _sub(item, context=None, **_):
        return child(str(item["title"]))

    return cast("AsyncModuleWrapper", workflow()(_sub))


def _sync_child(produced: list[int], closed: list[str]):
    def child(tag: str):
        try:
            for index in range(50):
                produced.append(index)
                yield {"content": f"{tag}{index}"}
        finally:
            closed.append(tag)

    def _sub(item, context=None, **_):
        return child(str(item["title"]))

    return workflow()(_sub)


EMBED_STREAMS = [
    pytest.param(_gen_closing_rows, id="async-generator"),
    pytest.param(ClosingAsyncIterator, id="aclose-only"),
]


class TestAdaptEmbed:
    @pytest.mark.parametrize(("adapt", "is_async"), ADAPTERS)
    def test_adapt_embed_copies_metadata(self, adapt, is_async: bool) -> None:
        stub = _EmbedStub()
        stub.is_async = is_async
        adapted = adapt(stub)

        assert adapted.name == "up"
        assert adapted.type == "processor"
        assert adapted.subtype == "transformer"
        assert adapted.subtypes == frozenset({"transformer"})
        assert adapted.pollable is False
        assert adapted.loopable is True
        assert adapted.is_async is not is_async
        assert not hasattr(adapted, "__wrapped__")

    def test_build_resolves_nested_embed(self) -> None:
        up = cast("SyncModuleWrapper", lambda item, **_: item)
        dispatcher = build_dispatcher(
            ModuleDefinition(name="fakeloop", sync_pipe=passthrough_pipe),
            ModuleDefinition(name="up", sync_pipe=up),
        )
        plan = ExecutionPlan.from_workflow(
            _lone_loop({"case": "upper"}), dispatcher=dispatcher
        )
        node = _get_node(plan, "loop")

        assert node.embed == ResolvedModule("up", {"case": "upper"}, sync_pipe=up)
        assert node.module.name == "fakeloop"
        assert node.options.kwargs == {"emit": True, "count": "first"}

    @skipif_sync
    def test_run_adapts_async_only_embed_under_sync(self) -> None:
        async def up(item, **_):
            yield {"up": item["t"].upper()}

        def fakeloop(items, embed=passthrough_pipe, **_):
            for row in items:
                yield from embed(row)

        _stamp_embed(up, is_async=True)
        dispatcher = build_dispatcher(
            ModuleDefinition(name="src", sync_pipe=tagged_source("x")),
            ModuleDefinition(
                name="fakeloop", sync_pipe=cast("SyncModuleWrapper", fakeloop)
            ),
            ModuleDefinition(name="up", async_pipe=cast("AsyncModuleWrapper", up)),
        )

        assert run_plan(_loop(), dispatcher=dispatcher) == [{"up": "X"}]

    @skipif_sync
    def test_run_runs_sync_only_embed_off_an_async_only_loop(self) -> None:
        threads: list[int] = []

        def up(item, **_):
            threads.append(get_ident())
            yield {"up": item["t"].upper()}

        async def fakeloop(items, embed=passthrough_pipe, **_):
            threads.append(get_ident())

            async for row in as_async(items):
                for value in await maybe_async(embed, row):
                    yield value

        _stamp_embed(up, is_async=False)
        dispatcher = build_dispatcher(
            ModuleDefinition(name="src", sync_pipe=tagged_source("x")),
            ModuleDefinition(
                name="fakeloop", async_pipe=cast("AsyncModuleWrapper", fakeloop)
            ),
            ModuleDefinition(name="up", sync_pipe=cast("SyncModuleWrapper", up)),
        )

        assert run_plan(_loop(), dispatcher=dispatcher) == [{"up": "X"}]
        loop_thread, embed_thread = threads
        assert embed_thread != loop_thread

    def test_run_forwards_embed_and_options_to_loop(self) -> None:
        seen: dict[str, object] = {}

        def up(item, **_):
            yield {"up": item["t"].upper()}

        def fakeloop(items, embed=passthrough_pipe, **kwargs):
            seen["embed"] = embed
            seen["options"] = {k: kwargs[k] for k in ("emit", "count") if k in kwargs}

            for row in items:
                yield from embed(row)

        sync_pipe = cast("SyncModuleWrapper", fakeloop)
        dispatcher = build_dispatcher(
            ModuleDefinition(name="src", sync_pipe=tagged_source("x")),
            ModuleDefinition(name="fakeloop", sync_pipe=sync_pipe),
            ModuleDefinition(name="up", sync_pipe=cast("SyncModuleWrapper", up)),
        )

        assert run_plan(_loop(), dispatcher=dispatcher) == [{"up": "X"}]
        assert seen["embed"] is up
        assert seen["options"] == {"emit": True, "count": "first"}

    @skipif_sync
    def test_run_loops_async_only_embed_through_the_real_loop(self) -> None:
        embed = _build_async_embed()
        dispatcher = build_dispatcher(
            ModuleDefinition(name="src", sync_pipe=tagged_source("x")),
            ModuleDefinition(name="loop", sync_pipe=loop_pipe, async_pipe=async_loop),
            ModuleDefinition(name=embed.name, async_pipe=embed),
        )
        flow = _loop(loop_name="loop", embed_name=embed.name)
        assert run_plan(flow, dispatcher=dispatcher) == [{"up": "X"}]

    @skipif_sync
    @pytest.mark.parametrize("build", EMBED_STREAMS)
    def test_run_closes_an_async_only_embed_stream_once_the_loop_closes(
        self, build
    ) -> None:
        closed: list[str] = []
        plan = _closing_embed_plan(build, closed)

        with SyncExecution() as execution:
            stream = cast("Generator[Item]", execution.run(plan))
            assert next(stream) == {"x": 1}
            stream.close()
            assert closed == ["closed"]

    @skipif_sync
    def test_run_count_first_stays_lazy_for_an_async_only_embed(self) -> None:
        produced: list[int] = []
        closed: list[str] = []
        sync_pipe = cast("SyncModuleWrapper", _titled_source)
        dispatcher = build_dispatcher(
            ModuleDefinition(name="src", sync_pipe=sync_pipe),
            ModuleDefinition(name="loop", sync_pipe=loop_pipe, async_pipe=async_loop),
            ModuleDefinition(name="child", async_pipe=_async_child(produced, closed)),
        )

        expected = [{"content": "a0"}, {"content": "b0"}]
        assert run_plan(_real_loop_workflow(), dispatcher=dispatcher) == expected
        assert produced == [0, 0]
        assert closed == ["a", "b"]


class TestAsyncAdaptEmbed:
    @pytest.mark.parametrize("build", EMBED_STREAMS)
    @async_test
    async def test_arun_closes_an_async_only_embed_stream_once_the_loop_closes(
        self, build
    ) -> None:
        closed: list[str] = []
        plan = _closing_embed_plan(build, closed)

        async with AsyncExecution() as execution:
            stream = cast("AsyncGenerator[Item]", await execution.arun(plan))
            assert await anext(stream) == {"x": 1}
            await stream.aclose()
            assert closed == ["closed"]

    @async_test
    async def test_arun_runs_sync_only_embed_off_the_event_loop(self) -> None:
        threads: list[int] = []

        def up(item, **_):
            threads.append(get_ident())
            yield {"up": item["t"].upper()}

        async def fakeloop(items, embed=passthrough_pipe, **_):
            async for row in as_async(items):
                for value in await maybe_async(embed, row):
                    yield value

        _stamp_embed(up, is_async=False)
        dispatcher = build_dispatcher(
            ModuleDefinition(name="src", sync_pipe=tagged_source("x")),
            ModuleDefinition(
                name="fakeloop", async_pipe=cast("AsyncModuleWrapper", fakeloop)
            ),
            ModuleDefinition(name="up", sync_pipe=cast("SyncModuleWrapper", up)),
        )
        plan = ExecutionPlan.from_workflow(_loop(), dispatcher=dispatcher)
        embed = _get_node(plan, "loop").embed
        loop_thread = get_ident()

        assert embed is not None
        assert (embed.sync_pipe, embed.async_pipe) == (up, None)

        async with AsyncExecution() as execution:
            stream = await execution.arun(plan)
            assert [item async for item in stream] == [{"up": "X"}]

        assert threads
        assert loop_thread not in threads

    @async_test
    async def test_arun_adapts_async_only_embed_for_a_sync_loop_on_a_worker(
        self,
    ) -> None:
        async def up(item, **_):
            yield {"up": item["t"].upper()}

        def fakeloop(items, embed=passthrough_pipe, **_):
            for row in items:
                yield from embed(row)

        _stamp_embed(up, is_async=True)
        dispatcher = build_dispatcher(
            ModuleDefinition(name="src", sync_pipe=tagged_source("x")),
            ModuleDefinition(
                name="fakeloop", sync_pipe=cast("SyncModuleWrapper", fakeloop)
            ),
            ModuleDefinition(name="up", async_pipe=cast("AsyncModuleWrapper", up)),
        )

        assert await arun_plan(_loop(), dispatcher=dispatcher) == [{"up": "X"}]

    @pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason="lazy sync-only embeds under an async loop are not yet implemented: the "
        "embed is collected to a list on the worker before the loop takes its first "
        "result, so count='first' cannot stop the child early",
    )
    @async_test
    async def test_arun_count_first_stays_lazy_for_a_sync_only_embed(self) -> None:
        produced: list[int] = []
        closed: list[str] = []
        dispatcher = build_dispatcher(
            ModuleDefinition(
                name="src", sync_pipe=cast("SyncModuleWrapper", _titled_source)
            ),
            ModuleDefinition(name="loop", sync_pipe=loop_pipe, async_pipe=async_loop),
            ModuleDefinition(name="child", sync_pipe=_sync_child(produced, closed)),
        )

        assert await arun_plan(_real_loop_workflow(), dispatcher=dispatcher) == [
            {"content": "a0"},
            {"content": "b0"},
        ]
        assert produced == [0, 0]
        assert closed == ["a", "b"]


@tag_source
def _replacements(_items=None, **_):
    yield "X"
    yield "Y"


@tag_source
def _replace_source(_items=None, **_):
    yield from _REPLACE_ITEMS


def _replace_workflow(conf, *edges, extra_nodes=()):
    node = ModuleNode(
        id="r", name="strreplace", conf=conf, options={"field": "content"}
    )
    nodes = [*extra_nodes, node]
    return build_workflow(nodes, edges=edges)


class _FailingClose(Closable):
    def close(self) -> None:
        super().close()
        raise OSError("close failed")


def _close_twice(stream: to_sync[int]) -> None:
    stream.close()
    stream.close()


def _close_to_sync(closes: list[str]) -> None:
    async def main() -> None:
        await asyncify(_close_twice, to_sync(syncify, Closable("source", closes)))

    run(main)


def _close_to_async(closes: list[str]) -> None:
    async def main() -> None:
        stream = to_async(_unused_worker, Closable("source", closes))
        await stream.aclose()
        await stream.aclose()

    run(main)


def _close_stream_results(closes: list[str]) -> None:
    stream = _gen_stream_results(len, Closable("source", closes))

    for _ in range(2):
        with maybe_closing(stream):
            pass


def _close_astream_results(closes: list[str]) -> None:
    async def main() -> None:
        stream = _agen_stream_results(len, Closable("source", closes))

        for _ in range(2):
            async with maybe_aclosing(stream):
                pass

    run(main)


STREAM_ADAPTER_CLOSERS = [
    pytest.param(_close_to_sync, id="to-sync", marks=skipif_sync),
    pytest.param(_close_to_async, id="to-async", marks=skipif_sync),
    pytest.param(_close_stream_results, id="callable-stream"),
    pytest.param(_close_astream_results, id="async-callable-stream", marks=skipif_sync),
]


class TestStreamAdapters:
    @pytest.mark.parametrize("close", STREAM_ADAPTER_CLOSERS)
    def test_close_before_read_closes_the_source_once(self, close) -> None:
        closes: list[str] = []
        close(closes)
        assert closes == ["source"]

    @skipif_sync
    def test_a_failed_read_notes_the_close_failure_on_the_read_error(self) -> None:
        closes: list[str] = []
        source = _FailingClose("source", closes, ValueError("boom"))

        async def main() -> None:
            await asyncify(next, to_sync(syncify, source))

        with pytest.raises(ValueError, match="boom") as raised:
            run(main)

        failure = "OSError('close failed')"
        assert raised.value.__notes__ == [f"closing the source also failed: {failure}"]
        assert closes == ["source"]


class TestPreparedCall:
    def test_a_node_prepares_once_per_plan(self, monkeypatch) -> None:
        calls: list[str] = []
        prepare = Module.prepare

        def counting(self, module_name, *args, **kwargs):
            calls.append(module_name)
            return prepare(self, module_name, *args, **kwargs)

        monkeypatch.setattr(Module, "prepare", counting)
        node = ModuleNode(id="n", name="strtransform", conf=_UPPER)
        flow = build_workflow([node])
        plan = ExecutionPlan.from_workflow(flow, dispatcher)
        items = [{"content": f"item {i}"} for i in range(50)]

        with SyncExecution() as execution:
            assert len(list(execution.run(plan, seed=items))) == 50

        assert calls == ["strtransform"]

    def test_a_static_conf_matches_the_direct_call(self) -> None:
        plan = ExecutionPlan.from_workflow(
            _replace_workflow(_STATIC_REPLACE), dispatcher
        )
        direct = strreplace_pipe(_REPLACE_ITEMS, conf=_STATIC_REPLACE, field="content")

        with SyncExecution() as execution:
            assert list(execution.run(plan, seed=_REPLACE_ITEMS)) == list(direct)

    def test_a_dynamic_conf_matches_the_direct_call(self) -> None:
        dispatcher = build_dispatcher(
            ModuleDefinition(
                name="reps", sync_pipe=cast("SyncModuleWrapper", _replacements)
            ),
            ModuleDefinition(
                name="items", sync_pipe=cast("SyncModuleWrapper", _replace_source)
            ),
            ModuleDefinition(name="strreplace", sync_pipe=strreplace_pipe),
        )
        sources = [ModuleNode(id="reps", name="reps"), ModuleNode(id="i", name="items")]
        edges = (
            StreamEdge(Endpoint("i", "out"), Endpoint("r", "in")),
            StreamEdge(Endpoint("reps", "out"), Endpoint("r", "in:rep")),
        )
        flow = _replace_workflow(_DYNAMIC_REPLACE, *edges, extra_nodes=sources)
        plan = ExecutionPlan.from_workflow(flow, dispatcher)
        direct = strreplace_pipe(
            _REPLACE_ITEMS, conf=_DYNAMIC_REPLACE, field="content", rep=_replacements()
        )
        expected = [
            {"content": "abc", "strreplace": "Xbc"},
            {"content": "aa", "strreplace": "YY"},
        ]

        assert plan.nodes["r"].extras == ("rep",)

        with SyncExecution() as execution:
            assert list(execution.run(plan)) == expected

        assert list(direct) == expected

    def test_a_prepared_call_survives_a_pickle_round_trip(self) -> None:
        plan = ExecutionPlan.from_workflow(
            _replace_workflow(_STATIC_REPLACE), dispatcher
        )
        interface = plan.nodes["r"].sync_interface
        assert interface is not None
        call = interface.call
        restored = pickle.loads(pickle.dumps(call))  # noqa: S301

        restored_items = cast("Stream", restored(_REPLACE_ITEMS))
        call_items = cast("Stream", call(_REPLACE_ITEMS))

        assert list(restored_items) == list(call_items)

    def test_the_plan_names_each_nodes_extras(self) -> None:
        dispatcher = build_dispatcher(
            ModuleDefinition(name="src", sync_pipe=tagged_source("a")),
            ModuleDefinition(name="host", sync_pipe=passthrough_pipe),
            ModuleDefinition(name="up", sync_pipe=passthrough_pipe),
        )
        sources = [ModuleNode(id=key, name="src") for key in ("a", "b", "c")]
        host = ModuleNode(
            id="n",
            name="host",
            resources={"db": "db"},
            embed={"name": "up", "conf": {}},
        )
        edges = (
            StreamEdge(Endpoint("a", "out"), Endpoint("n", "in")),
            StreamEdge(Endpoint("b", "out"), Endpoint("n", "in:label")),
            StreamEdge(Endpoint("c", "out"), Endpoint("n", "in:1")),
        )
        outputs = {"default": Endpoint("n", "out")}
        flow = build_workflow(
            [*sources, host], edges=edges, resources=("db",), outputs=outputs
        )
        plan = ExecutionPlan.from_workflow(flow, dispatcher)

        assert plan.nodes["n"].extras == ("label", "others", "resources", "embed")
        assert plan.nodes["a"].extras == ()


IDENTITIES = [
    pytest.param("hash", {}, IdentityMode.PRESERVE, id="hash"),
    pytest.param("strtransform", {}, IdentityMode.PRESERVE, id="strtransform"),
    pytest.param("tokenizer", {}, IdentityMode.DERIVE, id="tokenizer-emits"),
    pytest.param(
        "tokenizer", {"emit": False}, IdentityMode.PRESERVE, id="tokenizer-assigns"
    ),
    pytest.param("count", {}, IdentityMode.COMBINE, id="count"),
    pytest.param("sum", {}, IdentityMode.COMBINE, id="sum"),
    pytest.param("filter", {}, IdentityMode.PRESERVE, id="filter"),
    pytest.param("truncate", {}, IdentityMode.PRESERVE, id="truncate"),
    pytest.param("union", {}, IdentityMode.PRESERVE, id="union"),
    pytest.param("sort", {}, IdentityMode.PRESERVE, id="sort"),
    pytest.param("regex", {}, IdentityMode.PRESERVE, id="regex"),
    pytest.param("rename", {}, IdentityMode.PRESERVE, id="rename"),
    pytest.param("simplemath", {}, IdentityMode.PRESERVE, id="simplemath"),
    pytest.param("typecast", {}, IdentityMode.PRESERVE, id="typecast"),
    pytest.param("udf", {}, IdentityMode.PRESERVE, id="udf"),
    pytest.param("itembuilder", {}, IdentityMode.PRESERVE, id="itembuilder"),
    pytest.param("rssitembuilder", {}, IdentityMode.PRESERVE, id="rssitembuilder"),
    pytest.param("datebuilder", {}, IdentityMode.PRESERVE, id="datebuilder"),
    pytest.param("fetch", {}, IdentityMode.DERIVE, id="fetch"),
    pytest.param("fetchsitefeed", {}, IdentityMode.DERIVE, id="fetchsitefeed"),
    pytest.param("subelement", {}, IdentityMode.DERIVE, id="subelement"),
]

PLAIN_IDENTITIES = [
    pytest.param(None, None, id="undeclared"),
    pytest.param("preserve", IdentityMode.PRESERVE, id="preserve-value"),
    pytest.param(IdentityMode.DERIVE, IdentityMode.DERIVE, id="derive-member"),
]

CALLABLE_IDENTITIES = [
    pytest.param(None, IdentityMode.PRESERVE, id="undeclared"),
    pytest.param("derive", IdentityMode.DERIVE, id="derive"),
]


class TestPreparedNode:
    def test_a_callable_node_prepares_with_no_call_options(self):
        node = CallableNode(id="a", name="len", fn=len, resources="db")
        prepared = PreparedNode(node, _HASH)
        assert (prepared.options, prepared.extras) == (CallOptions(), ("resources",))

    @pytest.mark.parametrize(("name", "options", "expected"), IDENTITIES)
    def test_a_module_node_reports_its_result_identity(
        self, name, options, expected
    ) -> None:
        node = ModuleNode(id="n", name=name, options=options)
        module = ResolvedModule.from_dispatcher(dispatcher, name)
        prepared = PreparedNode(node, module)
        sync_interface = prepared.sync_interface
        async_interface = prepared.async_interface
        assert sync_interface is not None
        assert async_interface is not None
        assert sync_interface.identity is expected
        assert async_interface.identity is expected

    @pytest.mark.parametrize("name", ["count", "filter"])
    def test_an_operator_node_prepares_with_an_item_normalizer(self, name) -> None:
        node = ModuleNode(id="n", name=name)
        module = ResolvedModule.from_dispatcher(dispatcher, name)
        prepared = PreparedNode(node, module)
        sync_interface = prepared.sync_interface
        async_interface = prepared.async_interface
        assert sync_interface is not None
        assert async_interface is not None
        assert sync_interface.item_normalizer is not None
        assert async_interface.item_normalizer is not None

    @pytest.mark.parametrize(("identity", "expected"), PLAIN_IDENTITIES)
    def test_a_plain_wrapper_reports_its_declared_identity(
        self, identity, expected
    ) -> None:
        def pipe(source=None, **_):
            return iter(source or {})

        if identity is not None:
            setattr(pipe, "identity", identity)  # noqa: B010

        node = ModuleNode(id="p", name="probe")
        module = ResolvedModule("probe", sync_pipe=cast("SyncModuleWrapper", pipe))
        interface = PreparedNode(node, module).sync_interface
        assert interface is not None
        assert interface.identity is expected

    def test_a_plain_wrapper_rejects_an_invalid_identity(self) -> None:
        def pipe(source=None, **_):
            return iter(source or {})

        setattr(pipe, "identity", "split")  # noqa: B010
        node = ModuleNode(id="p", name="probe")
        module = ResolvedModule("probe", sync_pipe=cast("SyncModuleWrapper", pipe))

        with pytest.raises(InvalidPipelineError, match="module 'identity'"):
            _ = PreparedNode(node, module).sync_interface

    @pytest.mark.parametrize(("identity", "expected"), CALLABLE_IDENTITIES)
    def test_a_callable_node_reports_its_result_identity(
        self, identity, expected
    ) -> None:
        node = CallableNode(id="a", name="len", fn=len, identity=identity)
        interface = PreparedNode(node, _HASH).sync_interface
        assert interface is not None
        assert interface.identity is expected

    def test_a_callable_nodes_stream_call_closes_its_input_on_early_close(self) -> None:
        closed: list[str] = []
        source = gen_closing_seed(closed)
        node = CallableNode(id="a", name="len", fn=len)
        interface = PreparedNode(node, _HASH).sync_interface
        assert interface is not None
        with maybe_closing(interface.call(source, None)) as stream:
            assert next(stream) == 1

        assert closed == ["closed"]

    def test_prepared_node_reports_loopable(self) -> None:
        plan = build_chain_plan("hash", "count")
        assert _get_node(plan, "n0").loopable is True
        assert _get_node(plan, "n1").loopable is False

    @pytest.mark.parametrize("port", ["in:1", "in:side"])
    def test_secondary_input_stream_makes_a_node_unmappable(self, port) -> None:
        dispatcher = build_dispatcher(
            ModuleDefinition(name="echo", sync_pipe=echo_pipe)
        )
        nodes = [ModuleNode(id=id_, name="echo") for id_ in ("a", "b", "c")]
        edges = (
            StreamEdge(Endpoint("a", "out"), Endpoint("c", "in")),
            StreamEdge(Endpoint("b", "out"), Endpoint("c", port)),
        )
        plan = ExecutionPlan.from_workflow(
            build_workflow(nodes, edges=edges), dispatcher
        )
        assert _get_node(plan, "a").is_mappable is True
        assert _get_node(plan, "c").is_mappable is False

    def test_prepared_module_must_be_resolved(self):
        with pytest.raises(InvalidPipelineError, match="PreparedNode 'module'"):
            PreparedNode(ModuleNode(id="a", name="hash"), "hash")  # pyright: ignore[reportArgumentType]

    def test_prepared_node_must_wrap_a_module_node(self):
        node = WriteNode(id="a", name="write", backend="file", dest="out.csv")

        with pytest.raises(InvalidPipelineError, match="write node execution"):
            PreparedNode(node, _HASH)
