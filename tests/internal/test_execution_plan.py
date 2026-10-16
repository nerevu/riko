# vim: sw=4:ts=4:expandtab
"""Provides internal tests for building and running execution plans and embeds."""

from __future__ import annotations

import pickle  # noqa: S403
from threading import get_ident
from typing import TYPE_CHECKING, cast

import pytest

from riko.bado._backend import fail_after
from riko.bado._util import maybe_async
from riko.bado.itertools import as_async
from riko.base.exceptions import InvalidPipelineError, UnsupportedModuleError
from riko.definitions import _workflow_definition as workflow_definitions
from riko.definitions._context import Context
from riko.definitions._module_definition import ModuleDefinition
from riko.definitions._nodes import ModuleNode, StreamEdge
from riko.definitions._resource_definition import Resource
from riko.definitions._workflow_definition import Workflow
from riko.execution._adapt import (
    adapt_embed,
    async_adapt_embed,
    require_async_stream,
    require_stream,
)
from riko.execution._async_execution import AsyncExecution
from riko.execution._prepared import ExecutionPlan, PreparedNode, ResolvedModule
from riko.execution._sync_execution import SyncExecution
from riko.modules._decorators import Module, operator, processor, splitter
from riko.modules.loop import async_pipe as async_loop
from riko.modules.loop import pipe as loop_pipe
from riko.modules.split import async_pipe as async_split
from riko.modules.split import pipe as split_pipe
from riko.modules.strreplace import pipe as strreplace_pipe
from riko.modules.union import async_pipe as async_union
from riko.modules.union import pipe as union_pipe
from riko.runtime._module_registry import ModuleRegistry
from riko.runtime._resolver import ResolverDispatcher, dispatcher
from riko.runtime._workflow_pipes import workflow
from riko.runtime._workflow_resolver import workflow_resolver
from riko.types._enums import BasicCastType
from riko.types._workflow import Endpoint, GraphIndex
from riko.types._wrappers import stamp_wrapper_meta
from tests import async_test, skipif_issync
from tests._execution import (
    agen_source,
    awaitable_source,
    build_dispatcher,
    module_workflow,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from riko.types._streams import AsyncItemGenerator, Cascade, Item
    from riko.types._wrappers import AsyncModuleWrapper, SyncModuleWrapper
    from riko.types.modules import Conf


_sync_pipe = cast("SyncModuleWrapper", lambda source, **_: iter(source or {}))


_async_pipe = cast("AsyncModuleWrapper", lambda source, **_: as_async(source or {}))


def _build_flow(nodes, outputs, edges=(), resources=()):
    return Workflow(
        nodes=nodes, outputs=outputs, inputs={}, edges=edges, resources=resources
    )


def _tagged_source(tag):
    def src(_items=None, **_):
        yield {"t": tag}

    return cast("SyncModuleWrapper", src)


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


def _run(flow, dispatcher, output="default"):
    plan = ExecutionPlan.from_workflow(flow, dispatcher=dispatcher)

    with SyncExecution() as execution:
        return list(execution.run(plan, output))


async def _arun(flow, dispatcher, output="default"):
    plan = ExecutionPlan.from_workflow(flow, dispatcher=dispatcher)

    async with AsyncExecution() as execution:
        stream = await execution.arun(plan, output)
        return [item async for item in stream]


def _plain_reader(stream, **kwargs):
    yield {"got": kwargs["resources"]["slot"]}


@operator()
def _decorated_reader(stream, objconf, tuples, **kwargs):
    yield {"got": kwargs["resources"]["slot"]}


def _resource_reader_plan(reader=_decorated_reader):
    sync_pipe = cast("SyncModuleWrapper", reader)
    dispatcher = build_dispatcher(ModuleDefinition(name="reader", sync_pipe=sync_pipe))
    nodes = [ModuleNode(id="n", name="reader", resources={"slot": "primary"})]
    flow = _build_flow(nodes, {"default": Endpoint("n", "out")}, resources=("primary",))
    return ExecutionPlan.from_workflow(flow, dispatcher=dispatcher)


def _lifecycle(events: list[str]):
    def db():
        events.append("open")

        try:
            yield "conn"
        finally:
            events.append("close")

    return db


def _doubler_dispatcher():
    def double(source, **_):
        return ({"x": row["x"] * 2} for row in source)

    async def adouble(source, **_):
        async for row in source:
            yield {"x": row["x"] * 2}

    sync_pipe = cast("SyncModuleWrapper", double)
    async_pipe = cast("AsyncModuleWrapper", adouble)
    definition = ModuleDefinition(name="double", sync_pipe=sync_pipe)
    adefinition = ModuleDefinition(name="adouble", async_pipe=async_pipe)
    return build_dispatcher(definition, adefinition)


# An async stream seed is the stream itself, never one item holding the stream
# object, and an awaitable seed is awaited once for its items.
SEEDS = [
    pytest.param(lambda: [{"x": 1}, {"x": 2}], [{"x": 2}, {"x": 4}], id="list"),
    pytest.param(lambda: {"x": 5}, [{"x": 10}], id="one-item"),
    pytest.param(
        agen_source, [{"x": 2}, {"x": 4}], id="async-stream", marks=skipif_issync
    ),
    pytest.param(
        awaitable_source, [{"x": 2}, {"x": 4}], id="awaitable", marks=skipif_issync
    ),
]


def _loop(loop_name="fakeloop", embed_name="up"):
    src = ModuleNode(id="s", name="src")
    loop = ModuleNode(
        id="loop",
        name=loop_name,
        embed={"name": embed_name, "conf": {}},
        options={"emit": True, "count": "first"},
    )
    edge = StreamEdge(Endpoint("s", "out"), Endpoint("loop", "in"))
    return _build_flow([src, loop], {"default": Endpoint("loop", "out")}, edges=(edge,))


def _titled_source(_items=None, **_):
    yield {"title": "a"}
    yield {"title": "b"}


def _real_loop_workflow(embed_name="child"):
    return _loop(loop_name="loop", embed_name=embed_name)


SELECTIONS = [
    pytest.param(
        {"sync_pipe": _sync_pipe, "async_pipe": _async_pipe},
        "sync",
        _sync_pipe,
        id="native-sync",
    ),
    pytest.param(
        {"sync_pipe": _sync_pipe, "async_pipe": _async_pipe},
        "async",
        _async_pipe,
        id="native-async",
    ),
    pytest.param({"sync_pipe": _sync_pipe}, "async", _sync_pipe, id="sync-only"),
    pytest.param({"async_pipe": _async_pipe}, "sync", _async_pipe, id="async-only"),
]


class TestExecutionPlan:
    @pytest.mark.parametrize(("pipes", "mode", "expected"), SELECTIONS)
    def test_build_selects_the_pipe_for_each_mode(self, pipes, mode, expected) -> None:
        definition = ModuleDefinition(name="m", **pipes)
        plan = ExecutionPlan.from_workflow(
            module_workflow(), dispatcher=build_dispatcher(definition)
        )
        module = plan.nodes["n"].module
        selected = module.select_sync() if mode == "sync" else module.select_async()
        assert selected is expected

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
        plan = ExecutionPlan.from_workflow(module_workflow("count"), dispatcher)
        assert plan.index is plan.workflow.index
        assert len(calls) == 1

    def test_execution_plan_snapshots_resolution(self) -> None:
        # The plan resolves each node's callable once at build time, so replacing a
        # module afterward does not change what a built plan runs.
        registry = ModuleRegistry()
        registry.register(ModuleDefinition(name="src", sync_pipe=_tagged_source("a")))
        dispatcher = ResolverDispatcher(registry, workflow_resolver)
        plan = ExecutionPlan.from_workflow(
            module_workflow("src"), dispatcher=dispatcher
        )
        registry.register(
            ModuleDefinition(name="src", sync_pipe=_tagged_source("b")), replace=True
        )

        with SyncExecution() as execution:
            assert list(execution.run(plan)) == [{"t": "a"}]

    def test_build_carries_conf_index_and_resources(self) -> None:
        definition = ModuleDefinition(name="m", sync_pipe=_sync_pipe)
        node = ModuleNode(id="n", name="m", conf={"url": "x"}, resources={"db": "db"})
        flow = _build_flow([node], {"default": Endpoint("n", "out")}, resources=("db",))
        dispatcher = build_dispatcher(definition)
        plan = ExecutionPlan.from_workflow(flow, dispatcher=dispatcher)
        prepared = plan.nodes["n"]

        assert prepared.module.conf == {"url": "x"}
        assert set(prepared.resources.values()) == {"db"}
        assert plan.index.outputs["default"].node == "n"

    def test_build_rejects_unresolved_module(self) -> None:
        flow = module_workflow(name="does_not_exist_module")

        with pytest.raises(UnsupportedModuleError):
            ExecutionPlan.from_workflow(flow, dispatcher=build_dispatcher())

    def test_build_validates_the_graph(self) -> None:
        flow = _build_flow([ModuleNode(id="n", name="count")], {})

        with pytest.raises(InvalidPipelineError, match="output"):
            ExecutionPlan.from_workflow(flow, dispatcher)

    def test_build_plan_rejects_a_nodeless_workflow_with_outputs(self) -> None:
        flow = Workflow(nodes=[], outputs={"default": Endpoint("x", "out")})

        with pytest.raises(InvalidPipelineError, match="no nodes"):
            ExecutionPlan.from_workflow(flow, dispatcher)

    def test_build_plan_rejects_fan_out_from_one_source_port(self) -> None:
        # Two stream edges leaving the same source port would hand both consumers
        # one shared one-shot iterator, so whichever drained first would steal the
        # other's items. The plan refuses the shape before any node runs. This
        # guard is removed once port-keyed fan-out delivery becomes executable.
        dispatcher = build_dispatcher(
            ModuleDefinition(name="src", sync_pipe=_tagged_source("a")),
            ModuleDefinition(name="sink", sync_pipe=_sync_pipe),
        )
        a = ModuleNode(id="a", name="src")
        b = ModuleNode(id="b", name="sink")
        c = ModuleNode(id="c", name="sink")
        edges = (
            StreamEdge(Endpoint("a", "out"), Endpoint("b", "in")),
            StreamEdge(Endpoint("a", "out"), Endpoint("c", "in")),
        )
        flow = _build_flow([a, b, c], {"default": Endpoint("b", "out")}, edges=edges)

        with pytest.raises(InvalidPipelineError, match=r"fan-out.*\('a', 'out'\)"):
            ExecutionPlan.from_workflow(flow, dispatcher=dispatcher)

    def test_build_plan_rejects_splitter_node_before_any_node_runs(self) -> None:
        # A multi-output (splitter) node is refused when the plan is built, so its
        # upstream is never consumed first. This is removed once port-keyed
        # fan-out/split delivery becomes executable.
        consumed: list[int] = []

        def src(_items=None, **_):
            consumed.append(1)
            yield {"t": "a"}

        dispatcher = build_dispatcher(
            ModuleDefinition(name="src", sync_pipe=cast("SyncModuleWrapper", src)),
            ModuleDefinition(
                name="split", sync_pipe=split_pipe, async_pipe=async_split
            ),
        )
        a = ModuleNode(id="a", name="src")
        s = ModuleNode(id="s", name="split")
        edge = StreamEdge(Endpoint("a", "out"), Endpoint("s", "in"))
        flow = _build_flow([a, s], {"default": Endpoint("s", "out")}, edges=(edge,))

        with pytest.raises(InvalidPipelineError, match="splitter"):
            ExecutionPlan.from_workflow(flow, dispatcher=dispatcher)

        assert consumed == []

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

    @pytest.mark.xfail(
        strict=True,
        reason="owned by the module port contracts: a positional input into a module "
        "that declares no positional ports is accepted and silently ignored",
    )
    def test_build_plan_rejects_undeclared_positional_input(self) -> None:
        dispatcher = build_dispatcher(
            ModuleDefinition(name="src", sync_pipe=_tagged_source("a")),
            ModuleDefinition(name="sink", sync_pipe=_sync_pipe),
        )
        a = ModuleNode(id="a", name="src")
        b = ModuleNode(id="b", name="src")
        s = ModuleNode(id="s", name="sink")
        edges = (
            StreamEdge(Endpoint("a", "out"), Endpoint("s", "in")),
            StreamEdge(Endpoint("b", "out"), Endpoint("s", "in:1")),
        )
        flow = _build_flow([a, b, s], {"default": Endpoint("s", "out")}, edges=edges)

        with pytest.raises(InvalidPipelineError, match="positional"):
            ExecutionPlan.from_workflow(flow, dispatcher=dispatcher)


class TestResolvedModule:
    def test_resolved_module_refuses_a_splitter_pipe_on_construction(self) -> None:
        # The invariant lives on the resolved module itself, so every construction
        # path (plan build, embeds, direct construction) is covered.
        with pytest.raises(InvalidPipelineError, match=r"'sync_pipe'.*splitter"):
            ResolvedModule("split", {}, sync_pipe=split_pipe)

        with pytest.raises(InvalidPipelineError, match=r"'async_pipe'.*splitter"):
            ResolvedModule("split", {}, async_pipe=async_split)

    def test_resolved_module_reads_mode_from_the_slot(self) -> None:
        # Plain undecorated callables carry no mode marker, so the slot decides.
        module = ResolvedModule("m", {}, sync_pipe=_sync_pipe, async_pipe=_async_pipe)
        sync_only = ResolvedModule("m", {}, sync_pipe=_sync_pipe)
        async_only = ResolvedModule("m", {}, async_pipe=_async_pipe)

        assert not module.is_async_pipe(module.select_sync())
        assert module.is_async_pipe(module.select_async())
        assert not sync_only.is_async_pipe(sync_only.select_async())
        assert async_only.is_async_pipe(async_only.select_sync())

    def test_resolved_module_rejects_one_callable_in_both_slots(self) -> None:
        shared = cast("AsyncModuleWrapper", _sync_pipe)

        with pytest.raises(InvalidPipelineError, match="both sync and async"):
            ResolvedModule("m", {}, sync_pipe=_sync_pipe, async_pipe=shared)


class _EmbedStub:
    """Carries the discovery metadata an adapter must copy onto its wrapper."""

    name = "up"
    type = "processor"
    subtype = "transformer"
    subtypes = frozenset({"transformer"})
    pollable = False
    loopable = True
    isasync = True

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
        assert list(require_stream(_sync_pipe([{"x": 1}]), _sync_pipe)) == [{"x": 1}]


READERS = [
    pytest.param(_plain_reader, id="plain"),
    pytest.param(_decorated_reader, id="decorated"),
]


class TestPlanRun:
    def test_empty_plan_streams_its_seeded_source(self) -> None:
        plan = ExecutionPlan.from_workflow(Workflow(nodes=[], outputs={}), dispatcher)

        with SyncExecution() as execution:
            assert list(execution.run(plan, source=[{"x": 1}])) == [{"x": 1}]

    def test_empty_plan_without_a_source_raises(self) -> None:
        plan = ExecutionPlan.from_workflow(Workflow(nodes=[], outputs={}), dispatcher)

        with (
            SyncExecution() as execution,
            pytest.raises(InvalidPipelineError, match="no nodes"),
        ):
            execution.run(plan)

    def test_empty_plan_exposes_only_the_default_output(self) -> None:
        plan = ExecutionPlan.from_workflow(Workflow(nodes=[], outputs={}), dispatcher)

        with (
            SyncExecution() as execution,
            pytest.raises(InvalidPipelineError, match="'extra'"),
        ):
            execution.run(plan, "extra", source=[{"x": 1}])

    def test_run_executes_single_source_node(self) -> None:
        def src(_items=None, **_):
            yield {"x": 1}
            yield {"x": 2}

        sync_pipe = cast("SyncModuleWrapper", src)
        dispatcher = build_dispatcher(ModuleDefinition(name="src", sync_pipe=sync_pipe))
        assert _run(module_workflow("src"), dispatcher) == [{"x": 1}, {"x": 2}]

    def test_run_chains_nodes_through_stream_edge(self) -> None:
        def src(_items=None, **_):
            yield {"x": 1}
            yield {"x": 2}

        def double(items, **_):
            return ({"x": row["x"] * 2} for row in items)

        dispatcher = build_dispatcher(
            ModuleDefinition(name="src", sync_pipe=cast("SyncModuleWrapper", src)),
            ModuleDefinition(
                name="double", sync_pipe=cast("SyncModuleWrapper", double)
            ),
        )
        a = ModuleNode(id="a", name="src")
        b = ModuleNode(id="b", name="double")
        edge = StreamEdge(Endpoint("a", "out"), Endpoint("b", "in"))
        flow = _build_flow([a, b], {"default": Endpoint("b", "out")}, edges=(edge,))

        assert _run(flow, dispatcher) == [{"x": 2}, {"x": 4}]

    def test_run_forwards_node_options_as_call_kwargs(self) -> None:
        seen: dict[str, object] = {}

        def probe(source, **kwargs):
            seen["emit"] = kwargs.get("emit")
            seen["conf"] = dict(kwargs["conf"])
            return iter(())

        sync_pipe = cast("SyncModuleWrapper", probe)
        dispatcher = build_dispatcher(
            ModuleDefinition(name="probe", sync_pipe=sync_pipe)
        )
        node = ModuleNode(id="n", name="probe", options={"emit": True})
        flow = _build_flow([node], {"default": Endpoint("n", "out")})

        assert _run(flow, dispatcher) == []
        assert seen["emit"] is True
        assert seen["conf"] == {}

    def test_run_wires_others_ordered_by_port_index(self) -> None:
        def merge(items, others=None, **_):
            yield from items

            for other in others or ():
                yield from other

        dispatcher = build_dispatcher(
            ModuleDefinition(name="a", sync_pipe=_tagged_source("a")),
            ModuleDefinition(name="b", sync_pipe=_tagged_source("b")),
            ModuleDefinition(name="c", sync_pipe=_tagged_source("c")),
            ModuleDefinition(name="merge", sync_pipe=cast("SyncModuleWrapper", merge)),
        )
        a = ModuleNode(id="a", name="a")
        b = ModuleNode(id="b", name="b")
        c = ModuleNode(id="c", name="c")
        m = ModuleNode(id="m", name="merge")
        edges = (
            StreamEdge(Endpoint("a", "out"), Endpoint("m", "in")),
            StreamEdge(Endpoint("c", "out"), Endpoint("m", "in:2")),
            StreamEdge(Endpoint("b", "out"), Endpoint("m", "in:1")),
        )
        flow = _build_flow([a, b, c, m], {"default": Endpoint("m", "out")}, edges=edges)

        assert _run(flow, dispatcher) == [{"t": "a"}, {"t": "b"}, {"t": "c"}]

    def test_run_wires_named_input_port_as_kwarg(self) -> None:
        def joiner(items, side=None, **_):
            yield from items
            yield from side or ()

        dispatcher = build_dispatcher(
            ModuleDefinition(name="a", sync_pipe=_tagged_source("a")),
            ModuleDefinition(name="side", sync_pipe=_tagged_source("side")),
            ModuleDefinition(
                name="joiner", sync_pipe=cast("SyncModuleWrapper", joiner)
            ),
        )
        a = ModuleNode(id="a", name="a")
        s = ModuleNode(id="s", name="side")
        j = ModuleNode(id="j", name="joiner")
        edges = (
            StreamEdge(Endpoint("a", "out"), Endpoint("j", "in")),
            StreamEdge(Endpoint("s", "out"), Endpoint("j", "in:side")),
        )
        flow = _build_flow([a, s, j], {"default": Endpoint("j", "out")}, edges=edges)

        assert _run(flow, dispatcher) == [{"t": "a"}, {"t": "side"}]

    def test_run_leaves_the_default_input_empty_when_only_indexed_ports_are_wired(
        self,
    ) -> None:
        # An operator whose default input is unconnected but whose secondary inputs are
        # wired must not receive the seed item as data.
        seen: dict[str, object] = {}

        def merge(source, others=None, **_):
            seen["source"] = list(source)

            for other in others or ():
                yield from other

        dispatcher = build_dispatcher(
            ModuleDefinition(name="src", sync_pipe=_tagged_source("a")),
            ModuleDefinition(name="merge", sync_pipe=cast("SyncModuleWrapper", merge)),
        )
        a = ModuleNode(id="a", name="src")
        m = ModuleNode(id="m", name="merge")
        edge = StreamEdge(Endpoint("a", "out"), Endpoint("m", "in:1"))
        flow = _build_flow([a, m], {"default": Endpoint("m", "out")}, edges=(edge,))

        assert _run(flow, dispatcher) == [{"t": "a"}]
        assert seen["source"] == []

    def test_run_still_seeds_a_node_wired_only_through_a_named_value_port(self) -> None:
        seen: dict[str, object] = {}

        def probe(source, count=None, **_):
            seen["source"] = list(source)
            seen["count"] = list(count or ())
            return iter(())

        dispatcher = build_dispatcher(
            ModuleDefinition(name="src", sync_pipe=_tagged_source("a")),
            ModuleDefinition(name="probe", sync_pipe=cast("SyncModuleWrapper", probe)),
        )
        a = ModuleNode(id="a", name="src")
        b = ModuleNode(id="b", name="probe")
        edge = StreamEdge(Endpoint("a", "out"), Endpoint("b", "in:count"))
        flow = _build_flow([a, b], {"default": Endpoint("b", "out")}, edges=(edge,))

        assert _run(flow, dispatcher) == []
        assert seen["source"] == [{"forever": True}]
        assert seen["count"] == [{"t": "a"}]

    def test_run_rejects_nondefault_source_output_port(self) -> None:
        # Execution fails closed on non-default output ports: only the bare 'out' port
        # is executable. A distinct 'out:1' source port is rejected rather than
        # silently aliased to the node's 'out' stream. This guard is removed once
        # port-keyed fan-out/split delivery becomes executable.
        sync_pipe = cast("SyncModuleWrapper", lambda items, **_: iter(list(items)))
        dispatcher = build_dispatcher(
            ModuleDefinition(name="src", sync_pipe=_tagged_source("a")),
            ModuleDefinition(name="sink", sync_pipe=sync_pipe),
        )
        a = ModuleNode(id="a", name="src")
        b = ModuleNode(id="b", name="sink")
        edge = StreamEdge(Endpoint("a", "out:1"), Endpoint("b", "in"))
        flow = _build_flow([a, b], {"default": Endpoint("b", "out")}, edges=(edge,))

        with pytest.raises(InvalidPipelineError, match="non-default output port"):
            _run(flow, dispatcher)

    def test_run_rejects_nondefault_selected_output_port(self) -> None:
        # The fail-closed guard also covers a selected workflow output whose port is
        # not the default 'out'. This is removed once positional/named output ports
        # become addressable.
        dispatcher = build_dispatcher(
            ModuleDefinition(name="src", sync_pipe=_tagged_source("a"))
        )
        node = ModuleNode(id="n", name="src")
        flow = _build_flow([node], {"default": Endpoint("n", "out:1")})

        with pytest.raises(InvalidPipelineError, match="non-default output port"):
            _run(flow, dispatcher)

    def test_run_accepts_sparse_positional_inputs(self) -> None:
        # A variadic fan-in reads its positional inputs as one ordered list, so a gap
        # in the numbering (a legacy _OTHER3 with no _OTHER2) executes, and the port
        # number rather than edge order still decides where each operand lands.
        dispatcher = build_dispatcher(
            ModuleDefinition(name="a", sync_pipe=_tagged_source("a")),
            ModuleDefinition(name="b", sync_pipe=_tagged_source("b")),
            ModuleDefinition(name="c", sync_pipe=_tagged_source("c")),
            ModuleDefinition(
                name="union", sync_pipe=union_pipe, async_pipe=async_union
            ),
        )
        a = ModuleNode(id="a", name="a")
        b = ModuleNode(id="b", name="b")
        c = ModuleNode(id="c", name="c")
        u = ModuleNode(id="u", name="union")
        edges = (
            StreamEdge(Endpoint("a", "out"), Endpoint("u", "in")),
            StreamEdge(Endpoint("c", "out"), Endpoint("u", "in:3")),
            StreamEdge(Endpoint("b", "out"), Endpoint("u", "in:1")),
        )
        flow = _build_flow([a, b, c, u], {"default": Endpoint("u", "out")}, edges=edges)

        assert _run(flow, dispatcher) == [{"t": "a"}, {"t": "b"}, {"t": "c"}]

    @pytest.mark.parametrize("reader", READERS)
    def test_run_module_reads_execution_resources(self, reader) -> None:
        plan = _resource_reader_plan(reader)
        external = Context().with_resource("primary", Resource.from_external("ext"))

        with SyncExecution(external) as execution:
            assert list(execution.run(plan)) == [{"got": "ext"}]

        events: list[str] = []
        owned = Context().with_resource("primary", _lifecycle(events))

        with SyncExecution(owned) as execution:
            assert list(execution.run(plan)) == [{"got": "conn"}]
            assert events == ["open"]

        assert events == ["open", "close"]

    def test_run_rejects_unprovided_resource(self) -> None:
        def reader(items, **_):
            yield {}

        sync_pipe = cast("SyncModuleWrapper", reader)
        definition = ModuleDefinition(name="reader", sync_pipe=sync_pipe)
        dispatcher = build_dispatcher(definition)
        nodes = [ModuleNode(id="n", name="reader", resources={"slot": "primary"})]
        endpoint = Endpoint("n", "out")
        flow = _build_flow(nodes, {"default": endpoint}, resources=("primary",))
        plan = ExecutionPlan.from_workflow(flow, dispatcher=dispatcher)

        with (
            SyncExecution() as execution,
            pytest.raises(InvalidPipelineError, match="not provided"),
        ):
            list(execution.run(plan))

    def test_run_executes_only_selected_output_subgraph(self) -> None:
        ran: list[str] = []

        def a_src(_items=None, **_):
            ran.append("a")
            yield {"x": 1}

        def b_src(_items=None, **_):
            ran.append("b")
            yield {"y": 1}

        dispatcher = build_dispatcher(
            ModuleDefinition(name="a_src", sync_pipe=cast("SyncModuleWrapper", a_src)),
            ModuleDefinition(name="b_src", sync_pipe=cast("SyncModuleWrapper", b_src)),
        )
        a = ModuleNode(id="a", name="a_src")
        b = ModuleNode(id="b", name="b_src")
        outputs = {"default": Endpoint("a", "out"), "other": Endpoint("b", "out")}

        assert _run(_build_flow([a, b], outputs), dispatcher) == [{"x": 1}]
        assert ran == ["a"]

    def test_run_rejects_missing_output(self) -> None:
        dispatcher = build_dispatcher(
            ModuleDefinition(name="src", sync_pipe=_sync_pipe)
        )
        plan = ExecutionPlan.from_workflow(
            module_workflow("src"), dispatcher=dispatcher
        )

        with (
            SyncExecution() as execution,
            pytest.raises(InvalidPipelineError, match="no workflow output 'nope'"),
        ):
            execution.run(plan, "nope")

    @skipif_issync
    def test_run_drives_async_only_module_via_portal(self) -> None:
        async def src(_items=None, **_):
            yield {"x": 1}
            yield {"x": 2}

        async_pipe = cast("AsyncModuleWrapper", src)
        dispatcher = build_dispatcher(
            ModuleDefinition(name="src", async_pipe=async_pipe)
        )
        assert _run(module_workflow("src"), dispatcher) == [{"x": 1}, {"x": 2}]

    @skipif_issync
    def test_run_chains_async_only_node_after_sync_node(self) -> None:
        def src(_items=None, **_):
            yield {"x": 1}

        async def atag(items, **_):
            for row in items:
                yield {**row, "seen": True}

        dispatcher = build_dispatcher(
            ModuleDefinition(name="src", sync_pipe=cast("SyncModuleWrapper", src)),
            ModuleDefinition(name="atag", async_pipe=cast("AsyncModuleWrapper", atag)),
        )
        a = ModuleNode(id="a", name="src")
        b = ModuleNode(id="b", name="atag")
        edge = StreamEdge(Endpoint("a", "out"), Endpoint("b", "in"))
        flow = _build_flow([a, b], {"default": Endpoint("b", "out")}, edges=(edge,))

        assert _run(flow, dispatcher) == [{"x": 1, "seen": True}]

    @pytest.mark.parametrize(("make_seed", "expected"), SEEDS)
    def test_run_seeds_the_root_from_each_seed_shape(self, make_seed, expected) -> None:
        plan = ExecutionPlan.from_workflow(
            module_workflow("double"), _doubler_dispatcher()
        )

        with SyncExecution() as execution:
            assert list(execution.run(plan, source=make_seed())) == expected

    def test_run_without_seed_keeps_forever_source(self) -> None:
        seen: list[object] = []

        def probe(source, **_):
            seen.extend(source)
            return iter(())

        sync_pipe = cast("SyncModuleWrapper", probe)
        dispatcher = build_dispatcher(
            ModuleDefinition(name="probe", sync_pipe=sync_pipe)
        )
        plan = ExecutionPlan.from_workflow(
            module_workflow("probe"), dispatcher=dispatcher
        )

        with SyncExecution() as execution:
            assert list(execution.run(plan)) == []

        assert seen == [{"forever": True}]

    def test_run_rejects_seed_with_multiple_open_inputs(self) -> None:
        dispatcher = build_dispatcher(
            ModuleDefinition(name="a_src", sync_pipe=_tagged_source("a")),
            ModuleDefinition(name="b_src", sync_pipe=_tagged_source("b")),
            ModuleDefinition(name="merge", sync_pipe=_sync_pipe),
        )
        a = ModuleNode(id="a", name="a_src")
        b = ModuleNode(id="b", name="b_src")
        m = ModuleNode(id="m", name="merge")
        edges = (
            StreamEdge(Endpoint("a", "out"), Endpoint("m", "in:1")),
            StreamEdge(Endpoint("b", "out"), Endpoint("m", "in:2")),
        )
        flow = _build_flow([a, b, m], {"default": Endpoint("m", "out")}, edges=edges)
        plan = ExecutionPlan.from_workflow(flow, dispatcher=dispatcher)

        with (
            SyncExecution() as execution,
            pytest.raises(InvalidPipelineError, match="exactly one open input"),
        ):
            execution.run(plan, source=[{"x": 1}])

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "pending lazy resource acquisition: a lazy resource bound to a node is "
            "acquired when the run starts even though the node never reads it"
        ),
    )
    def test_run_defers_an_unused_lazy_resource(self) -> None:
        def ignore(items, **_):
            yield from items

        sync_pipe = cast("SyncModuleWrapper", ignore)
        dispatcher = build_dispatcher(
            ModuleDefinition(name="ignore", sync_pipe=sync_pipe)
        )
        nodes = [ModuleNode(id="n", name="ignore", resources={"slot": "primary"})]
        flow = _build_flow(
            nodes, {"default": Endpoint("n", "out")}, resources=("primary",)
        )
        plan = ExecutionPlan.from_workflow(flow, dispatcher=dispatcher)
        events: list[str] = []
        context = Context().with_resource("primary", _lifecycle(events), lazy=True)

        with SyncExecution(context) as execution:
            assert list(execution.run(plan, source=[{"x": 1}])) == [{"x": 1}]

        assert events == []


async def _acollect(stream, seen):
    async for item in stream:
        seen.append(item)


class TestAsyncPlanRun:
    @async_test
    async def test_empty_plan_streams_its_seeded_source_async(self) -> None:
        plan = ExecutionPlan.from_workflow(Workflow(nodes=[], outputs={}), dispatcher)

        async with AsyncExecution() as execution:
            stream = await execution.arun(plan, source={"x": 1})
            assert [item async for item in stream] == [{"x": 1}]

    @async_test
    async def test_arun_executes_native_async_source(self) -> None:
        async def src(_items=None, **_):
            yield {"x": 1}
            yield {"x": 2}

        async_pipe = cast("AsyncModuleWrapper", src)
        dispatcher = build_dispatcher(
            ModuleDefinition(name="src", async_pipe=async_pipe)
        )
        assert await _arun(module_workflow("src"), dispatcher) == [{"x": 1}, {"x": 2}]

    @async_test
    async def test_arun_runs_sync_only_node_via_worker(self) -> None:
        def src(_items=None, **_):
            yield {"x": 1}
            yield {"x": 2}

        sync_pipe = cast("SyncModuleWrapper", src)
        dispatcher = build_dispatcher(ModuleDefinition(name="src", sync_pipe=sync_pipe))
        assert await _arun(module_workflow("src"), dispatcher) == [{"x": 1}, {"x": 2}]

    @async_test
    async def test_arun_chains_async_and_sync_worker_nodes(self) -> None:
        async def src(_items=None, **_):
            yield {"n": 1}

        def double(items, **_):
            return ({"n": row["n"] * 2} for row in items)

        async def atag(items, **_):
            async for row in items:
                yield {**row, "seen": True}

        dispatcher = build_dispatcher(
            ModuleDefinition(name="src", async_pipe=cast("AsyncModuleWrapper", src)),
            ModuleDefinition(
                name="double", sync_pipe=cast("SyncModuleWrapper", double)
            ),
            ModuleDefinition(name="atag", async_pipe=cast("AsyncModuleWrapper", atag)),
        )
        a = ModuleNode(id="a", name="src")
        b = ModuleNode(id="b", name="double")
        c = ModuleNode(id="c", name="atag")
        edges = (
            StreamEdge(Endpoint("a", "out"), Endpoint("b", "in")),
            StreamEdge(Endpoint("b", "out"), Endpoint("c", "in")),
        )
        flow = _build_flow([a, b, c], {"default": Endpoint("c", "out")}, edges=edges)

        assert await _arun(flow, dispatcher) == [{"n": 2, "seen": True}]

    @async_test
    async def test_arun_forwards_node_options_as_call_kwargs(self) -> None:
        seen: dict[str, object] = {}

        async def aprobe(source, **kwargs):
            seen["emit"] = kwargs.get("emit")
            seen["conf"] = dict(kwargs["conf"])

            for item in ():
                yield item

        async_pipe = cast("AsyncModuleWrapper", aprobe)
        dispatcher = build_dispatcher(
            ModuleDefinition(name="aprobe", async_pipe=async_pipe)
        )
        node = ModuleNode(id="n", name="aprobe", options={"emit": True})
        flow = _build_flow([node], {"default": Endpoint("n", "out")})

        assert await _arun(flow, dispatcher) == []
        assert seen["emit"] is True
        assert seen["conf"] == {}

    @async_test
    async def test_arun_leaves_the_default_input_empty_for_indexed_ports(self) -> None:
        seen: dict[str, object] = {}

        async def asrc(_items=None, **_):
            yield {"t": "a"}

        async def amerge(source, others=None, **_):
            seen["source"] = [row async for row in source]

            for other in others or ():
                async for row in other:
                    yield row

        dispatcher = build_dispatcher(
            ModuleDefinition(name="asrc", async_pipe=cast("AsyncModuleWrapper", asrc)),
            ModuleDefinition(
                name="amerge", async_pipe=cast("AsyncModuleWrapper", amerge)
            ),
        )
        a = ModuleNode(id="a", name="asrc")
        m = ModuleNode(id="m", name="amerge")
        edge = StreamEdge(Endpoint("a", "out"), Endpoint("m", "in:1"))
        flow = _build_flow([a, m], {"default": Endpoint("m", "out")}, edges=(edge,))

        assert await _arun(flow, dispatcher) == [{"t": "a"}]
        assert seen["source"] == []

    @async_test
    async def test_arun_sync_worker_node_adapts_secondary_inputs(self) -> None:
        async def asrc(_items=None, **_):
            yield {"t": "a"}

        async def bsrc(_items=None, **_):
            yield {"t": "b"}

        async def csrc(_items=None, **_):
            yield {"t": "c"}

        def merge(items, others=None, label=None, **_):
            yield from items

            for other in others or ():
                yield from other

            for row in label or ():
                yield {"labeled": row["t"]}

        dispatcher = build_dispatcher(
            ModuleDefinition(name="asrc", async_pipe=cast("AsyncModuleWrapper", asrc)),
            ModuleDefinition(name="bsrc", async_pipe=cast("AsyncModuleWrapper", bsrc)),
            ModuleDefinition(name="csrc", async_pipe=cast("AsyncModuleWrapper", csrc)),
            ModuleDefinition(name="merge", sync_pipe=cast("SyncModuleWrapper", merge)),
        )
        a = ModuleNode(id="a", name="asrc")
        b = ModuleNode(id="b", name="bsrc")
        c = ModuleNode(id="c", name="csrc")
        m = ModuleNode(id="m", name="merge")
        edges = (
            StreamEdge(Endpoint("a", "out"), Endpoint("m", "in")),
            StreamEdge(Endpoint("b", "out"), Endpoint("m", "in:1")),
            StreamEdge(Endpoint("c", "out"), Endpoint("m", "in:label")),
        )
        flow = _build_flow([a, b, c, m], {"default": Endpoint("m", "out")}, edges=edges)

        assert await _arun(flow, dispatcher) == [
            {"t": "a"},
            {"t": "b"},
            {"labeled": "c"},
        ]

    @async_test
    async def test_arun_decorated_module_reads_execution_resources(self) -> None:
        plan = _resource_reader_plan()
        events: list[str] = []
        context = Context().with_resource("primary", _lifecycle(events))

        async with AsyncExecution(context) as execution:
            stream = await execution.arun(plan)
            assert [item async for item in stream] == [{"got": "conn"}]

        assert events == ["open", "close"]

    @pytest.mark.parametrize(("make_seed", "expected"), SEEDS)
    @async_test
    async def test_arun_seeds_the_root_from_each_seed_shape(
        self, make_seed, expected
    ) -> None:
        plan = ExecutionPlan.from_workflow(
            module_workflow("adouble"), _doubler_dispatcher()
        )

        async with AsyncExecution() as execution:
            stream = await execution.arun(plan, source=make_seed())
            assert [item async for item in stream] == expected

    @async_test
    async def test_arun_without_seed_keeps_forever_source(self) -> None:
        seen: list[object] = []

        async def aprobe(source, **_):
            seen.extend([row async for row in source])

            for item in ():
                yield item

        async_pipe = cast("AsyncModuleWrapper", aprobe)
        dispatcher = build_dispatcher(
            ModuleDefinition(name="aprobe", async_pipe=async_pipe)
        )
        plan = ExecutionPlan.from_workflow(
            module_workflow("aprobe"), dispatcher=dispatcher
        )

        async with AsyncExecution() as execution:
            stream = await execution.arun(plan)
            assert [item async for item in stream] == []

        assert seen == [{"forever": True}]

    @async_test
    async def test_arun_sync_only_source_streams_lazily(self) -> None:
        def src(_items=None, **_):
            yield {"x": 1}
            raise RuntimeError("later")

        sync_pipe = cast("SyncModuleWrapper", src)
        dispatcher = build_dispatcher(ModuleDefinition(name="src", sync_pipe=sync_pipe))
        plan = ExecutionPlan.from_workflow(
            module_workflow("src"), dispatcher=dispatcher
        )
        first = None

        async with AsyncExecution() as execution:
            stream = await execution.arun(plan)
            first = await anext(aiter(stream))

        assert first == {"x": 1}

    @async_test
    async def test_arun_sync_only_source_raises_after_yielding_earlier_items(
        self,
    ) -> None:
        def src(_items=None, **_):
            yield {"x": 1}
            yield {"x": 2}
            raise RuntimeError("later")

        sync_pipe = cast("SyncModuleWrapper", src)
        dispatcher = build_dispatcher(ModuleDefinition(name="src", sync_pipe=sync_pipe))
        plan = ExecutionPlan.from_workflow(
            module_workflow("src"), dispatcher=dispatcher
        )
        seen = []

        async with AsyncExecution() as execution:
            stream = await execution.arun(plan)

            with pytest.raises(RuntimeError, match="later"):
                await _acollect(stream, seen)

        assert seen == [{"x": 1}, {"x": 2}]

    @async_test
    async def test_arun_sync_only_source_closes_on_early_exit(self) -> None:
        closed = []

        def src(_items=None, **_):
            index = 0

            try:
                while True:
                    yield {"x": index}
                    index += 1
            finally:
                closed.append(True)

        sync_pipe = cast("SyncModuleWrapper", src)
        dispatcher = build_dispatcher(ModuleDefinition(name="src", sync_pipe=sync_pipe))
        plan = ExecutionPlan.from_workflow(
            module_workflow("src"), dispatcher=dispatcher
        )
        seen = []

        with fail_after(5):
            async with AsyncExecution() as execution:
                stream = cast("AsyncItemGenerator", await execution.arun(plan))

                async for item in stream:
                    seen.append(item)

                    if len(seen) == 3:
                        break

                await stream.aclose()

        assert seen == [{"x": 0}, {"x": 1}, {"x": 2}]
        assert closed == [True]

    @async_test
    async def test_arun_unconsumed_sync_only_source_does_not_block_exit(self) -> None:
        def src(_items=None, **_):
            index = 0

            while True:
                yield {"x": index}
                index += 1

        sync_pipe = cast("SyncModuleWrapper", src)
        dispatcher = build_dispatcher(ModuleDefinition(name="src", sync_pipe=sync_pipe))
        plan = ExecutionPlan.from_workflow(
            module_workflow("src"), dispatcher=dispatcher
        )

        with fail_after(5):
            async with AsyncExecution() as execution:
                stream = await execution.arun(plan)
                assert stream is not None

    @async_test
    async def test_arun_sync_worker_node_reads_secondary_inputs_lazily(self) -> None:
        async def asrc(_items=None, **_):
            yield {"t": "a"}

        async def bsrc(_items=None, **_):
            yield {"t": "b"}
            raise RuntimeError("secondary later")

        def merge(items, others=None, **_):
            yield from items

            for other in others or ():
                yield from other

        dispatcher = build_dispatcher(
            ModuleDefinition(name="asrc", async_pipe=cast("AsyncModuleWrapper", asrc)),
            ModuleDefinition(name="bsrc", async_pipe=cast("AsyncModuleWrapper", bsrc)),
            ModuleDefinition(name="merge", sync_pipe=cast("SyncModuleWrapper", merge)),
        )
        a = ModuleNode(id="a", name="asrc")
        b = ModuleNode(id="b", name="bsrc")
        m = ModuleNode(id="m", name="merge")
        edges = (
            StreamEdge(Endpoint("a", "out"), Endpoint("m", "in")),
            StreamEdge(Endpoint("b", "out"), Endpoint("m", "in:1")),
        )
        flow = _build_flow([a, b, m], {"default": Endpoint("m", "out")}, edges=edges)
        plan = ExecutionPlan.from_workflow(flow, dispatcher=dispatcher)
        seen = []

        async with AsyncExecution() as execution:
            stream = await execution.arun(plan)

            with pytest.raises(RuntimeError, match="secondary later"):
                await _acollect(stream, seen)

        assert seen == [{"t": "a"}, {"t": "b"}]

    @async_test
    async def test_arun_sync_worker_node_runs_off_the_event_loop(self) -> None:
        threads = []

        def src(_items=None, **_):
            threads.append(get_ident())
            yield {"x": 1}
            threads.append(get_ident())

        sync_pipe = cast("SyncModuleWrapper", src)
        dispatcher = build_dispatcher(ModuleDefinition(name="src", sync_pipe=sync_pipe))
        loop_thread = get_ident()

        assert await _arun(module_workflow("src"), dispatcher) == [{"x": 1}]
        assert threads
        assert loop_thread not in threads


def _lone_loop(embed_conf=None):
    loop = ModuleNode(
        id="loop",
        name="fakeloop",
        embed={"name": "up", "conf": embed_conf or {}},
        options={"emit": True, "count": "first"},
    )
    return _build_flow([loop], {"default": Endpoint("loop", "out")})


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


class TestEmbed:
    def test_build_resolves_nested_embed(self) -> None:
        up = cast("SyncModuleWrapper", lambda item, **_: item)
        dispatcher = build_dispatcher(
            ModuleDefinition(name="fakeloop", sync_pipe=_sync_pipe),
            ModuleDefinition(name="up", sync_pipe=up),
        )
        plan = ExecutionPlan.from_workflow(
            _lone_loop({"case": "upper"}), dispatcher=dispatcher
        )
        node = plan.nodes["loop"]

        assert node.embed == ResolvedModule("up", {"case": "upper"}, sync_pipe=up)
        assert node.module.name == "fakeloop"
        assert node.options.kwargs == {"emit": True, "count": "first"}

    def test_build_adapts_async_only_embed_under_sync(self) -> None:
        dispatcher = build_dispatcher(
            ModuleDefinition(name="fakeloop", sync_pipe=_sync_pipe),
            ModuleDefinition(name="up", async_pipe=_async_pipe),
        )
        plan = ExecutionPlan.from_workflow(_lone_loop(), dispatcher=dispatcher)
        embed = plan.nodes["loop"].embed
        assert embed is not None
        assert embed.select_sync() is _async_pipe

    def test_build_adapts_sync_only_embed_under_async(self) -> None:
        dispatcher = build_dispatcher(
            ModuleDefinition(name="fakeloop", async_pipe=_async_pipe),
            ModuleDefinition(name="up", sync_pipe=_sync_pipe),
        )
        plan = ExecutionPlan.from_workflow(_lone_loop(), dispatcher=dispatcher)
        embed = plan.nodes["loop"].embed

        assert embed is not None
        assert embed.select_async() is _sync_pipe

    @skipif_issync
    def test_run_adapts_async_only_embed_under_sync(self) -> None:
        async def up(item, **_):
            yield {"up": item["t"].upper()}

        def fakeloop(items, embed=_sync_pipe, **_):
            for row in items:
                yield from embed(row)

        _stamp_embed(up, isasync=True)
        dispatcher = build_dispatcher(
            ModuleDefinition(name="src", sync_pipe=_tagged_source("x")),
            ModuleDefinition(
                name="fakeloop", sync_pipe=cast("SyncModuleWrapper", fakeloop)
            ),
            ModuleDefinition(name="up", async_pipe=cast("AsyncModuleWrapper", up)),
        )

        assert _run(_loop(), dispatcher) == [{"up": "X"}]

    def test_run_forwards_embed_and_options_to_loop(self) -> None:
        seen: dict[str, object] = {}

        def up(item, **_):
            yield {"up": item["t"].upper()}

        def fakeloop(items, embed=_sync_pipe, **kwargs):
            seen["embed"] = embed
            seen["options"] = {k: kwargs[k] for k in ("emit", "count") if k in kwargs}

            for row in items:
                yield from embed(row)

        sync_pipe = cast("SyncModuleWrapper", fakeloop)
        dispatcher = build_dispatcher(
            ModuleDefinition(name="src", sync_pipe=_tagged_source("x")),
            ModuleDefinition(name="fakeloop", sync_pipe=sync_pipe),
            ModuleDefinition(name="up", sync_pipe=cast("SyncModuleWrapper", up)),
        )

        assert _run(_loop(), dispatcher) == [{"up": "X"}]
        assert seen["embed"] is up
        assert seen["options"] == {"emit": True, "count": "first"}

    @skipif_issync
    def test_run_loops_async_only_embed_through_the_real_loop(self) -> None:
        embed = _build_async_embed()
        dispatcher = build_dispatcher(
            ModuleDefinition(name="src", sync_pipe=_tagged_source("x")),
            ModuleDefinition(name="loop", sync_pipe=loop_pipe, async_pipe=async_loop),
            ModuleDefinition(name=embed.name, async_pipe=embed),
        )
        flow = _loop(loop_name="loop", embed_name=embed.name)
        assert _run(flow, dispatcher) == [{"up": "X"}]

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
        assert _run(_real_loop_workflow(), dispatcher) == expected
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

        async def fakeloop(items, embed=_sync_pipe, **_):
            async for row in as_async(items):
                for value in await maybe_async(embed, row):
                    yield value

        _stamp_embed(up, isasync=False)
        dispatcher = build_dispatcher(
            ModuleDefinition(name="src", sync_pipe=_tagged_source("x")),
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

        def fakeloop(items, embed=_sync_pipe, **_):
            for row in items:
                yield from embed(row)

        _stamp_embed(up, isasync=True)
        dispatcher = build_dispatcher(
            ModuleDefinition(name="src", sync_pipe=_tagged_source("x")),
            ModuleDefinition(
                name="fakeloop", sync_pipe=cast("SyncModuleWrapper", fakeloop)
            ),
            ModuleDefinition(name="up", async_pipe=cast("AsyncModuleWrapper", up)),
        )

        assert await _arun(_loop(), dispatcher) == [{"up": "X"}]

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

        assert await _arun(_real_loop_workflow(), dispatcher) == [
            {"content": "a0"},
            {"content": "b0"},
        ]
        assert produced == [0, 0]
        assert closed == ["a", "b"]


def _replacements(_items=None, **_):
    yield "X"
    yield "Y"


def _replace_source(_items=None, **_):
    yield from _REPLACE_ITEMS


_REPLACE_ITEMS = [{"content": "abc"}, {"content": "aa"}]
_STATIC_REPLACE = cast("Conf", {"rule": [{"find": "a", "replace": "Z"}]})
_DYNAMIC_REPLACE = cast(
    "Conf", {"rule": [{"find": "a", "replace": {"terminal": "rep", "type": "text"}}]}
)
_UPPER = cast("Conf", {"rule": {"transform": "upper"}})


def _replace_workflow(conf, *edges, extra_nodes=()):
    node = ModuleNode(
        id="r", name="strreplace", conf=conf, options={"field": "content"}
    )
    nodes = [*extra_nodes, node]
    return _build_flow(nodes, {"default": Endpoint("r", "out")}, edges=edges)


class TestPreparedCall:
    def test_a_node_prepares_once_per_plan(self, monkeypatch) -> None:
        calls: list[str] = []
        prepare = Module.prepare

        def counting(self, module_name, *args, **kwargs):
            calls.append(module_name)
            return prepare(self, module_name, *args, **kwargs)

        monkeypatch.setattr(Module, "prepare", counting)
        node = ModuleNode(id="n", name="strtransform", conf=_UPPER)
        flow = _build_flow([node], {"default": Endpoint("n", "out")})
        plan = ExecutionPlan.from_workflow(flow, dispatcher)
        items = [{"content": f"item {i}"} for i in range(50)]

        with SyncExecution() as execution:
            assert len(list(execution.run(plan, source=items))) == 50

        assert calls == ["strtransform"]

    def test_a_static_conf_matches_the_direct_call(self) -> None:
        plan = ExecutionPlan.from_workflow(
            _replace_workflow(_STATIC_REPLACE), dispatcher
        )
        direct = strreplace_pipe(_REPLACE_ITEMS, conf=_STATIC_REPLACE, field="content")

        with SyncExecution() as execution:
            assert list(execution.run(plan, source=_REPLACE_ITEMS)) == list(direct)

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
        call = plan.nodes["r"].sync_call
        assert call is not None
        restored = pickle.loads(pickle.dumps(call))  # noqa: S301

        restored_items = cast("Iterator[Item]", restored(_REPLACE_ITEMS))
        call_items = cast("Iterator[Item]", call(_REPLACE_ITEMS))

        assert list(restored_items) == list(call_items)

    def test_the_plan_names_each_nodes_extras(self) -> None:
        dispatcher = build_dispatcher(
            ModuleDefinition(name="src", sync_pipe=_tagged_source("a")),
            ModuleDefinition(name="host", sync_pipe=_sync_pipe),
            ModuleDefinition(name="up", sync_pipe=_sync_pipe),
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
        flow = _build_flow([*sources, host], outputs, edges=edges, resources=("db",))
        plan = ExecutionPlan.from_workflow(flow, dispatcher)

        assert plan.nodes["n"].extras == ("label", "others", "resources", "embed")
        assert plan.nodes["a"].extras == ()

    def test_select_call_requires_a_matching_pipe(self) -> None:
        node = PreparedNode(
            ModuleNode(id="n", name="m"), ResolvedModule("m", async_pipe=_async_pipe)
        )

        with pytest.raises(UnsupportedModuleError, match="no such interface"):
            node.select_call(_sync_pipe)

    def test_a_missing_pipe_has_no_prepared_call(self) -> None:
        module = ResolvedModule("m", sync_pipe=_sync_pipe)
        node = PreparedNode(ModuleNode(id="n", name="m"), module)

        assert node.async_call is None
        assert node.select_call(_sync_pipe) is node.sync_call
