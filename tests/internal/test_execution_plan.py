# vim: sw=4:ts=4:expandtab
"""Provides internal tests for building and running execution plans and embeds."""

from __future__ import annotations

import pickle  # noqa: S403
from threading import get_ident
from typing import TYPE_CHECKING, Any, cast

import pytest

from riko.bado._util import maybe_async
from riko.bado.itertools import as_async
from riko.base._exceptions import InvalidPipelineError, UnsupportedModuleError
from riko.definitions import _workflow_definition as workflow_definitions
from riko.definitions._module_definition import ModuleDefinition
from riko.definitions._nodes import CallableNode, ModuleNode, StreamEdge, WriteNode
from riko.definitions._workflow_definition import Workflow
from riko.definitions._wrapping import stamp_wrapper_meta
from riko.execution._adapt import (
    adapt_embed,
    async_adapt_embed,
    require_async_stream,
    require_stream,
)
from riko.execution._async_execution import AsyncExecution
from riko.execution._prepared import ExecutionPlan, PreparedNode, ResolvedModule
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
from riko.types._enums import BasicCastType
from riko.types._options import CallOptions
from riko.types._workflow import Endpoint, GraphIndex
from tests import async_test, skipif_issync
from tests._execution import (
    OUTPUT_A,
    arun_plan,
    build_chain,
    build_chain_plan,
    build_dispatcher,
    build_workflow,
    mark_loopable,
    module_workflow,
    passthrough_pipe,
    run_plan,
    tag_source,
    tagged_source,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from riko.types._streams import Cascade, Item
    from riko.types._wrappers import AsyncModuleWrapper, SyncModuleWrapper
    from riko.types.modules import Conf


def _flagged(func, flag: str) -> Any:
    setattr(func, flag, True)
    return func


_ASYNC_PIPE = cast("AsyncModuleWrapper", lambda source, **_: as_async(source or {}))
_BOTH = {"sync_pipe": passthrough_pipe, "async_pipe": _ASYNC_PIPE}
_SYNC_ONLY = {"sync_pipe": passthrough_pipe}
_ASYNC_ONLY = {"async_pipe": _ASYNC_PIPE}
_HASH = ResolvedModule("hash", sync_pipe=hash_pipe)
_COUNT_NO_OUTPUT = build_workflow([ModuleNode(id="n", name="count")], outputs={})
_NODELESS = Workflow(nodes=[], outputs={"default": Endpoint("x", "out")})
_LOOPABLE_SYNC = _flagged(lambda source, **_: iter(source or {}), "loopable")

_SEQUENTIAL_ASYNC = _flagged(
    lambda source, **_: as_async(source or {}), "sequential_inputs"
)

_REPLACE_ITEMS = [{"content": "abc"}, {"content": "aa"}]
_STATIC_REPLACE = cast("Conf", {"rule": [{"find": "a", "replace": "Z"}]})

_DYNAMIC_REPLACE = cast(
    "Conf", {"rule": [{"find": "a", "replace": {"terminal": "rep", "type": "text"}}]}
)

_UPPER = cast("Conf", {"rule": {"transform": "upper"}})
_EMPTY = Workflow(nodes=[], outputs={})
_HASH_FLOW = Workflow(nodes=[ModuleNode(id="a", name="hash")], outputs=OUTPUT_A)
_LOOP_NODE = ModuleNode(id="a", name="loop", embed={"name": "hash", "conf": {}})
_LOOP_FLOW = Workflow(nodes=[_LOOP_NODE], outputs=OUTPUT_A)
_BARE_LOOP = Workflow(nodes=[ModuleNode(id="a", name="loop")], outputs=OUTPUT_A)
_WRITE = WriteNode(id="a", name="write", backend="file", dest="out.csv")
_WRITE_FLOW = Workflow(nodes=[_WRITE], outputs=OUTPUT_A)
_HASH_A = {"a": _HASH}
_HASH_AB = {"a": _HASH, "b": _HASH}
_SYNC, _ASYNC = "sync_interface", "async_interface"


def _stamp_embed(up, *, isasync: bool) -> None:
    stamp_wrapper_meta(
        up,
        name="up",
        module_type="processor",
        subtype="transformer",
        subtypes={"transformer"},
        pollable=False,
        loopable=True,
        isasync=isasync,
    )


def _loop(loop_name="fakeloop", embed_name="up"):
    src = ModuleNode(id="s", name="src")
    loop = ModuleNode(
        id="loop",
        name=loop_name,
        embed={"name": embed_name, "conf": {}},
        options={"emit": True, "count": "first"},
    )
    return build_chain(src, loop)


@tag_source
def _titled_source(_items=None, **_):
    yield {"title": "a"}
    yield {"title": "b"}


def _real_loop_workflow(embed_name="child"):
    return _loop(loop_name="loop", embed_name=embed_name)


SELECTIONS = [
    pytest.param(_BOTH, "sync", passthrough_pipe, id="native-sync"),
    pytest.param(_BOTH, "async", _ASYNC_PIPE, id="native-async"),
    pytest.param(_SYNC_ONLY, "async", passthrough_pipe, id="sync-only"),
    pytest.param(_ASYNC_ONLY, "sync", _ASYNC_PIPE, id="async-only"),
]


BUILD_REJECTIONS = [
    pytest.param(_COUNT_NO_OUTPUT, "output", id="validates-the-graph"),
    pytest.param(_NODELESS, "no nodes", id="nodeless-with-outputs"),
]


CONSTRUCTION_REJECTIONS = [
    pytest.param({"nodes": []}, {}, {}, "ExecutionPlan 'workflow'", id="workflow"),
    pytest.param(_EMPTY, {"n": 1}, {}, "ExecutionPlan module 'n'", id="unresolved"),
    pytest.param(_EMPTY, "abc", {}, "ExecutionPlan 'modules'", id="modules-str"),
    pytest.param(_EMPTY, None, {}, "ExecutionPlan 'modules'", id="modules-none"),
    pytest.param(_HASH_FLOW, {}, {}, "modules must match", id="missing"),
    pytest.param(_HASH_FLOW, _HASH_AB, {}, "modules must match", id="extra"),
    pytest.param(_LOOP_FLOW, _HASH_A, {}, "embeds must match", id="embed-missing"),
    pytest.param(_BARE_LOOP, _HASH_A, _HASH_A, "embeds must match", id="embed-extra"),
    pytest.param(_WRITE_FLOW, _HASH_A, {}, "not yet supported", id="non-module"),
]


class TestExecutionPlan:
    @pytest.mark.parametrize(("pipes", "mode", "expected"), SELECTIONS)
    def test_build_selects_the_pipe_for_each_mode(self, pipes, mode, expected) -> None:
        definition = ModuleDefinition(name="m", **pipes)
        plan = ExecutionPlan.from_workflow(
            module_workflow(), dispatcher=build_dispatcher(definition)
        )
        node = plan.nodes["n"]
        interface = node.sync_interface if mode == "sync" else node.async_interface
        module = node.module
        selected = module.select_sync() if mode == "sync" else module.select_async()

        assert selected is interface.pipe is expected
        assert interface.native is (f"{mode}_pipe" in pipes)

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

        def counting(*args: object) -> GraphIndex:
            calls.append(args)
            return GraphIndex(*args)  # pyright: ignore[reportArgumentType]

        monkeypatch.setattr(workflow_definitions, "GraphIndex", counting)
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
        prepared = plan.nodes["a"]
        assert (prepared.node, prepared.module, prepared.embed) == (node, _HASH, _HASH)

    def test_a_lone_source_is_the_seed_target(self) -> None:
        dispatcher = build_dispatcher(
            ModuleDefinition(name="src", sync_pipe=tagged_source("a"))
        )
        plan = ExecutionPlan.from_workflow(module_workflow("src"), dispatcher)

        assert plan.require_seed_target("default") == "n"

    @pytest.mark.parametrize(("flow", "match"), BUILD_REJECTIONS)
    def test_build_rejects_an_invalid_graph(self, flow, match) -> None:
        with pytest.raises(InvalidPipelineError, match=match):
            ExecutionPlan.from_workflow(flow, dispatcher)

    def test_build_rejects_unresolved_module(self) -> None:
        flow = module_workflow(name="does_not_exist_module")

        with pytest.raises(UnsupportedModuleError):
            ExecutionPlan.from_workflow(flow, dispatcher=build_dispatcher())

    def test_build_plan_rejects_fan_out_from_one_source_port(self) -> None:
        # Two stream edges leaving the same source port would hand both consumers
        # one shared one-shot iterator, so whichever drained first would steal the
        # other's items. The plan refuses the shape before any node runs. This
        # guard is removed once port-keyed fan-out delivery becomes executable.
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

        with pytest.raises(InvalidPipelineError, match=r"fan-out.*\('a', 'out'\)"):
            ExecutionPlan.from_workflow(flow, dispatcher=dispatcher)

    def test_build_plan_rejects_splitter_by_declared_type_not_output_shape(
        self,
    ) -> None:
        # The refusal keys on the module type the pipe was decorated with, not on the
        # shape of what it yields, so a splitter whose branches are lists rather than
        # iterators is refused too instead of delivering whole lists as items.
        @splitter(objectify=False)
        def listy(stream, _objconf, _tuples, **_):
            items = list(stream)
            return cast("Cascade", iter([list(items), list(items)]))

        dispatcher = build_dispatcher(ModuleDefinition(name="listy", sync_pipe=listy))

        with pytest.raises(InvalidPipelineError, match="splitter"):
            ExecutionPlan.from_workflow(module_workflow("listy"), dispatcher=dispatcher)

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
        reason="owned by the module port contracts: a positional input into a module "
        "that declares no positional ports is accepted and silently ignored",
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
    pytest.param({"sync_pipe": split_pipe}, r"'sync_pipe'.*split", id="sync-split"),
    pytest.param({"async_pipe": async_split}, r"'async_pipe'.*split", id="async-split"),
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
        {"sync_pipe": passthrough_pipe, "async_pipe": _SEQUENTIAL_ASYNC},
        "disagree on 'sequential_inputs'",
        id="mismatched-sequential-inputs",
    ),
]


class TestResolvedModule:
    @pytest.mark.parametrize(("pipes", "match"), INVALID_MODULES)
    def test_resolved_module_refuses_invalid_pipes(self, pipes, match) -> None:
        with pytest.raises(InvalidPipelineError, match=match):
            ResolvedModule("m", {}, **pipes)

    def test_resolved_module_reads_mode_from_the_slot(self) -> None:
        # Plain undecorated callables carry no mode marker, so the slot decides.
        module = ResolvedModule(
            "m", {}, sync_pipe=passthrough_pipe, async_pipe=_ASYNC_PIPE
        )
        sync_only = ResolvedModule("m", {}, sync_pipe=passthrough_pipe)
        async_only = ResolvedModule("m", {}, async_pipe=_ASYNC_PIPE)

        assert not module.is_async_pipe(module.select_sync())
        assert module.is_async_pipe(module.select_async())
        assert not sync_only.is_async_pipe(sync_only.select_async())
        assert async_only.is_async_pipe(async_only.select_sync())


class _EmbedStub:
    """Carries the discovery metadata an adapter must copy onto its wrapper."""

    name = "up"
    type = "processor"
    subtype = "transformer"
    subtypes = frozenset({"transformer"})
    pollable = False
    loopable = True
    isasync = True
    sequential_inputs = False

    def __call__(self, item=None, **kwargs):
        return iter(())


def _unused_drain(source):
    return iter(())


async def _unused_worker(func, *args):
    return func(*args)


ADAPTERS = [
    pytest.param(
        lambda stub: adapt_embed(cast("AsyncModuleWrapper", stub), _unused_drain),
        True,
        id="for-sync",
    ),
    pytest.param(
        lambda stub: async_adapt_embed(cast("SyncModuleWrapper", stub), _unused_worker),
        False,
        id="for-async",
    ),
]


class TestEmbedAdaptation:
    @pytest.mark.parametrize(("adapt", "isasync"), ADAPTERS)
    def test_adapt_embed_copies_metadata(self, adapt, isasync: bool) -> None:
        stub = _EmbedStub()
        stub.isasync = isasync
        adapted = adapt(stub)

        assert adapted.name == "up"
        assert adapted.type == "processor"
        assert adapted.subtype == "transformer"
        assert adapted.subtypes == frozenset({"transformer"})
        assert adapted.pollable is False
        assert adapted.loopable is True
        assert adapted.isasync is not isasync
        assert not hasattr(adapted, "__wrapped__")

    def test_require_stream_refuses_a_splitter_pipe_without_consuming(self) -> None:
        # The execution-side boundary earns its narrowing from the pipe's declared
        # type, so a splitter's output is refused before any of it is read.
        consumed: list[int] = []

        def src():
            consumed.append(1)
            yield {"x": 1}

        with pytest.raises(InvalidPipelineError, match="splitter"):
            require_stream(split_pipe(src()), split_pipe)

        with pytest.raises(InvalidPipelineError, match="splitter"):
            require_async_stream(async_split(src()), async_split)

        assert consumed == []
        assert list(require_stream(passthrough_pipe([{"x": 1}]), passthrough_pipe)) == [
            {"x": 1}
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
        "AsyncModuleWrapper", processor(isasync=True, ptype=BasicCastType.NONE)(shout)
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


EMBED_ADAPTATIONS = [
    pytest.param(
        _SYNC_ONLY, _ASYNC_ONLY, "select_sync", _ASYNC_PIPE, id="async-only-under-sync"
    ),
    pytest.param(
        _ASYNC_ONLY,
        _SYNC_ONLY,
        "select_async",
        passthrough_pipe,
        id="sync-only-under-async",
    ),
]


class TestEmbed:
    @pytest.mark.parametrize(("loop", "embed", "select", "expected"), EMBED_ADAPTATIONS)
    def test_build_adapts_an_embed_to_the_loop_mode(
        self, loop, embed, select, expected
    ) -> None:
        dispatcher = build_dispatcher(
            ModuleDefinition(name="fakeloop", **loop),
            ModuleDefinition(name="up", **embed),
        )
        plan = ExecutionPlan.from_workflow(_lone_loop(), dispatcher=dispatcher)
        adapted = plan.nodes["loop"].embed
        assert adapted is not None
        assert getattr(adapted, select)() is expected

    def test_build_resolves_nested_embed(self) -> None:
        up = cast("SyncModuleWrapper", lambda item, **_: item)
        dispatcher = build_dispatcher(
            ModuleDefinition(name="fakeloop", sync_pipe=passthrough_pipe),
            ModuleDefinition(name="up", sync_pipe=up),
        )
        plan = ExecutionPlan.from_workflow(
            _lone_loop({"case": "upper"}), dispatcher=dispatcher
        )
        node = plan.nodes["loop"]

        assert node.embed == ResolvedModule("up", {"case": "upper"}, sync_pipe=up)
        assert node.module.name == "fakeloop"
        assert node.options.kwargs == {"emit": True, "count": "first"}

    @skipif_issync
    def test_run_adapts_async_only_embed_under_sync(self) -> None:
        async def up(item, **_):
            yield {"up": item["t"].upper()}

        def fakeloop(items, embed=passthrough_pipe, **_):
            for row in items:
                yield from embed(row)

        _stamp_embed(up, isasync=True)
        dispatcher = build_dispatcher(
            ModuleDefinition(name="src", sync_pipe=tagged_source("x")),
            ModuleDefinition(
                name="fakeloop", sync_pipe=cast("SyncModuleWrapper", fakeloop)
            ),
            ModuleDefinition(name="up", async_pipe=cast("AsyncModuleWrapper", up)),
        )

        assert run_plan(_loop(), dispatcher=dispatcher) == [{"up": "X"}]

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

    @skipif_issync
    def test_run_loops_async_only_embed_through_the_real_loop(self) -> None:
        embed = _build_async_embed()
        dispatcher = build_dispatcher(
            ModuleDefinition(name="src", sync_pipe=tagged_source("x")),
            ModuleDefinition(name="loop", sync_pipe=loop_pipe, async_pipe=async_loop),
            ModuleDefinition(name=embed.name, async_pipe=embed),
        )
        flow = _loop(loop_name="loop", embed_name=embed.name)
        assert run_plan(flow, dispatcher=dispatcher) == [{"up": "X"}]

    @skipif_issync
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


class TestAsyncEmbed:
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

        _stamp_embed(up, isasync=False)
        dispatcher = build_dispatcher(
            ModuleDefinition(name="src", sync_pipe=tagged_source("x")),
            ModuleDefinition(
                name="fakeloop", async_pipe=cast("AsyncModuleWrapper", fakeloop)
            ),
            ModuleDefinition(name="up", sync_pipe=cast("SyncModuleWrapper", up)),
        )
        plan = ExecutionPlan.from_workflow(_loop(), dispatcher=dispatcher)
        embed = plan.nodes["loop"].embed
        loop_thread = get_ident()

        assert embed is not None
        assert embed.select_async() is up

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

        _stamp_embed(up, isasync=True)
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
        reason="owned by the pending lazy sync-under-async embed work: a sync-only "
        "embed under an async loop is collected to a list on the worker before the "
        "loop takes its first result, so count='first' cannot stop the child early",
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
    return build_workflow(nodes, edges=edges, outputs={"default": Endpoint("r", "out")})


FALLBACKS = [
    pytest.param(_SYNC_ONLY, _ASYNC, _SYNC, id="sync-only"),
    pytest.param(_ASYNC_ONLY, _SYNC, _ASYNC, id="async-only"),
]


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
        call = plan.nodes["r"].sync_interface.call
        restored = pickle.loads(pickle.dumps(call))  # noqa: S301

        restored_items = cast("Iterator[Item]", restored(_REPLACE_ITEMS))
        call_items = cast("Iterator[Item]", call(_REPLACE_ITEMS))

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

    @pytest.mark.parametrize(("pipes", "missing", "present"), FALLBACKS)
    def test_a_missing_pipe_reuses_the_other_prepared_call(
        self, pipes, missing, present
    ) -> None:
        node = PreparedNode(ModuleNode(id="n", name="m"), ResolvedModule("m", **pipes))
        fallback, native = getattr(node, missing), getattr(node, present)

        assert native.native is True
        assert fallback == native._replace(native=False)


class TestPreparedNode:
    def test_a_callable_node_prepares_with_no_call_options(self):
        node = CallableNode(id="a", name="len", fn=len, resources="db")
        prepared = PreparedNode(node, _HASH)
        assert (prepared.options, prepared.extras) == (CallOptions(), ("resources",))

    def test_prepared_node_reports_loopable(self) -> None:
        plan = build_chain_plan("hash", "count")
        assert plan.nodes["n0"].loopable is True
        assert plan.nodes["n1"].loopable is False

    @pytest.mark.parametrize("port", ["in:1", "in:side"])
    def test_secondary_input_stream_makes_a_node_unmappable(self, port) -> None:
        def echo(item, **_):
            return iter([item])

        dispatcher = build_dispatcher(
            ModuleDefinition(name="echo", sync_pipe=mark_loopable(echo))
        )
        nodes = [ModuleNode(id=id_, name="echo") for id_ in ("a", "b", "c")]
        edges = (
            StreamEdge(Endpoint("a", "out"), Endpoint("c", "in")),
            StreamEdge(Endpoint("b", "out"), Endpoint("c", port)),
        )
        plan = ExecutionPlan.from_workflow(
            build_workflow(nodes, edges=edges), dispatcher
        )
        assert plan.nodes["a"].is_mappable is True
        assert plan.nodes["c"].is_mappable is False

    def test_prepared_module_must_be_resolved(self):
        with pytest.raises(InvalidPipelineError, match="PreparedNode 'module'"):
            PreparedNode(ModuleNode(id="a", name="hash"), "hash")  # pyright: ignore[reportArgumentType]

    def test_prepared_node_must_wrap_a_module_node(self):
        node = WriteNode(id="a", name="write", backend="file", dest="out.csv")

        with pytest.raises(InvalidPipelineError, match="write node execution"):
            PreparedNode(node, _HASH)
