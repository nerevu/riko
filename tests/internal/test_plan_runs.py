"""Provides internal tests for running an ``ExecutionPlan``."""

from __future__ import annotations

from threading import get_ident
from typing import TYPE_CHECKING, Self, cast

import pytest

from riko.bado._backend import fail_after
from riko.bado.itertools import as_async
from riko.base._exceptions import InvalidPipelineError
from riko.definitions._context import Context
from riko.definitions._module_definition import ModuleDefinition
from riko.definitions._nodes import ModuleNode, StreamEdge
from riko.definitions._resource_definition import Resource
from riko.definitions._workflow_definition import Workflow
from riko.execution._async_execution import AsyncExecution
from riko.execution._prepared import ExecutionPlan
from riko.execution._sync_execution import SyncExecution
from riko.modules._decorators import operator
from riko.modules.union import async_pipe as async_union
from riko.modules.union import pipe as union_pipe
from riko.runtime._module_registry import module_registry
from riko.runtime._resolver import ResolverDispatcher, dispatcher
from riko.runtime._workflow_resolver import WorkflowResolver, _build_resolved_workflow
from riko.runtime._workflow_stores import MappingStore
from riko.types._workflow import Endpoint
from tests import async_test, skipif_issync
from tests._execution import (
    ClosingAsyncIterator,
    agen_source,
    arun_plan,
    awaitable_source,
    build_chain,
    build_dispatcher,
    build_workflow,
    gen_closing_seed,
    module_workflow,
    passthrough_pipe,
    run_plan,
    tag_source,
    tagged_source,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from riko.types._streams import AsyncItemGenerator, Item
    from riko.types._wrappers import AsyncModuleWrapper, SyncModuleWrapper
    from riko.types.modules import Conf


_SRC = ModuleDefinition(name="src", sync_pipe=tagged_source("a"))
_ECHO = cast("SyncModuleWrapper", lambda items, **_: iter(list(items)))
_SINK = ModuleDefinition(name="sink", sync_pipe=_ECHO)
_PROBE = ModuleDefinition(name="probe", sync_pipe=passthrough_pipe)
_DOUBLED = [{"x": 2}, {"x": 4}]
_SRC_SINK = [ModuleNode(id="a", name="src"), ModuleNode(id="b", name="sink")]
_PORT_1_EDGE = StreamEdge(Endpoint("a", "out:1"), Endpoint("b", "in"))
_SRC_NODE = [ModuleNode(id="n", name="src")]
_PORT_1_OUTPUT = {"default": Endpoint("n", "out:1")}
_NEEDS_SEED = r"'b'.*requires a seed"
_NON_DEFAULT = "non-default output port"
_SRC_ECHO = ModuleDefinition(name="src", sync_pipe=passthrough_pipe)
_EMPTY = Workflow(nodes=[], outputs={})
_NOPE = "no workflow output 'nope'"


@tag_source
def _plain_reader(stream, **kwargs):
    yield {"got": kwargs["resources"]["slot"]}


@tag_source
@operator()
def _decorated_reader(stream, objconf, tuples, **kwargs):
    yield {"got": kwargs["resources"]["slot"]}


def _named_port_workflow() -> Workflow:
    a, b = ModuleNode(id="a", name="src"), ModuleNode(id="b", name="probe")
    edge = StreamEdge(Endpoint("a", "out"), Endpoint("b", "in:count"))
    return build_workflow([a, b], edges=(edge,))


READERS = [
    pytest.param(_plain_reader, id="plain"),
    pytest.param(_decorated_reader, id="decorated"),
]


# Execution fails closed on non-default output ports: only the bare 'out' port is
# executable, so a distinct 'out:1' source port or selected output is rejected
# rather than silently aliased to the node's 'out' stream.
RUN_REJECTIONS = [
    pytest.param(
        build_workflow(_SRC_SINK, edges=(_PORT_1_EDGE,)),
        (_SRC, _SINK),
        _NON_DEFAULT,
        id="nondefault-source-output-port",
    ),
    pytest.param(
        build_workflow(_SRC_NODE, outputs=_PORT_1_OUTPUT),
        (_SRC,),
        _NON_DEFAULT,
        id="nondefault-selected-output-port",
    ),
    pytest.param(
        _named_port_workflow(),
        (_SRC, _PROBE),
        _NEEDS_SEED,
        id="transformer-fed-only-through-a-named-port",
    ),
]


UNKNOWN_OUTPUTS = [
    pytest.param(_EMPTY, (), "extra", [{"x": 1}], "'extra'", id="empty-plan"),
    pytest.param(
        module_workflow("src"), (_SRC_ECHO,), "nope", None, _NOPE, id="missing"
    ),
]


class _DualSeed:
    """A seed that is both sync- and async-iterable, with different items each way."""

    def __iter__(self):
        return iter([{"x": 1}])

    def __aiter__(self):
        return as_async([{"x": 100}])


# An async stream seed is the stream itself, never one item holding the stream
# object, and an awaitable seed is awaited once for its items.
SEEDS = [
    pytest.param(lambda: {"x": 5}, [{"x": 10}], id="one-item"),
    pytest.param(agen_source, _DOUBLED, id="async-stream", marks=skipif_issync),
    pytest.param(awaitable_source, _DOUBLED, id="awaitable", marks=skipif_issync),
]


async def _agen_closing_seed(closed: list[str]) -> AsyncItemGenerator:
    try:
        yield {"x": 1}
        yield {"x": 2}
    finally:
        closed.append("closed")


CLOSING_SEEDS = [
    pytest.param(gen_closing_seed, id="generator"),
    pytest.param(_agen_closing_seed, id="async-generator", marks=skipif_issync),
    pytest.param(ClosingAsyncIterator, id="async-iterator", marks=skipif_issync),
]


def _resource_reader_plan(reader=_decorated_reader):
    sync_pipe = cast("SyncModuleWrapper", reader)
    dispatcher = build_dispatcher(ModuleDefinition(name="reader", sync_pipe=sync_pipe))
    nodes = [ModuleNode(id="n", name="reader", resources={"slot": "primary"})]
    flow = build_workflow(
        nodes, resources=("primary",), outputs={"default": Endpoint("n", "out")}
    )
    return ExecutionPlan.from_workflow(flow, dispatcher=dispatcher)


def _lifecycle(events: list[str]):
    def db():
        events.append("open")

        try:
            yield "conn"
        finally:
            events.append("close")

    return db


def _doubler_plan(name: str) -> ExecutionPlan:
    def double(source, **_):
        return ({"x": row["x"] * 2} for row in source)

    async def adouble(source, **_):
        async for row in source:
            yield {"x": row["x"] * 2}

    sync_pipe = cast("SyncModuleWrapper", double)
    async_pipe = cast("AsyncModuleWrapper", adouble)
    definition = ModuleDefinition(name="double", sync_pipe=sync_pipe)
    adefinition = ModuleDefinition(name="adouble", async_pipe=async_pipe)
    dispatcher = build_dispatcher(definition, adefinition)
    return ExecutionPlan.from_workflow(module_workflow(name), dispatcher)


class TestPlanRun:
    def test_run_executes_single_source_node(self) -> None:
        @tag_source
        def src(_items=None, **_):
            yield {"x": 1}
            yield {"x": 2}

        sync_pipe = cast("SyncModuleWrapper", src)
        dispatcher = build_dispatcher(ModuleDefinition(name="src", sync_pipe=sync_pipe))
        assert run_plan(module_workflow("src"), dispatcher=dispatcher) == [
            {"x": 1},
            {"x": 2},
        ]

    def test_run_chains_nodes_through_stream_edge(self) -> None:
        @tag_source
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
        flow = build_chain(
            ModuleNode(id="a", name="src"), ModuleNode(id="b", name="double")
        )

        assert run_plan(flow, dispatcher=dispatcher) == _DOUBLED

    def test_run_forwards_node_options_as_call_kwargs(self) -> None:
        seen: dict[str, object] = {}

        @tag_source
        def probe(source, **kwargs):
            seen["emit"] = kwargs.get("emit")
            seen["conf"] = dict(kwargs["conf"])
            return iter(())

        sync_pipe = cast("SyncModuleWrapper", probe)
        dispatcher = build_dispatcher(
            ModuleDefinition(name="probe", sync_pipe=sync_pipe)
        )
        node = ModuleNode(id="n", name="probe", options={"emit": True})
        flow = build_workflow([node])

        assert run_plan(flow, dispatcher=dispatcher) == []
        assert seen["emit"] is True
        assert seen["conf"] == {}

    def test_run_wires_named_input_port_as_kwarg(self) -> None:
        def joiner(items, side=None, **_):
            yield from items
            yield from side or ()

        dispatcher = build_dispatcher(
            ModuleDefinition(name="a", sync_pipe=tagged_source("a")),
            ModuleDefinition(name="side", sync_pipe=tagged_source("side")),
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
        flow = build_workflow([a, s, j], edges=edges)

        assert run_plan(flow, dispatcher=dispatcher) == [{"t": "a"}, {"t": "side"}]

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
            ModuleDefinition(name="src", sync_pipe=tagged_source("a")),
            ModuleDefinition(name="merge", sync_pipe=cast("SyncModuleWrapper", merge)),
        )
        a = ModuleNode(id="a", name="src")
        m = ModuleNode(id="m", name="merge")
        edge = StreamEdge(Endpoint("a", "out"), Endpoint("m", "in:1"))
        flow = build_workflow([a, m], edges=(edge,))

        assert run_plan(flow, dispatcher=dispatcher) == [{"t": "a"}]
        assert seen["source"] == []

    def test_run_keeps_the_default_seed_for_a_source_fed_only_through_a_named_port(
        self,
    ) -> None:
        seen: dict[str, object] = {}

        @tag_source
        def probe(source, count=None, **_):
            seen["source"] = list(source)
            seen["count"] = list(count or ())
            return iter(())

        dispatcher = build_dispatcher(
            ModuleDefinition(name="src", sync_pipe=tagged_source("a")),
            ModuleDefinition(name="probe", sync_pipe=cast("SyncModuleWrapper", probe)),
        )
        flow = _named_port_workflow()

        assert run_plan(flow, dispatcher=dispatcher) == []
        assert seen["source"] == [{"forever": True}]
        assert seen["count"] == [{"t": "a"}]

    def test_run_seeds_the_transformer_fed_only_through_a_named_port(self) -> None:
        seen: dict[str, object] = {}
        ran: list[str] = []

        @tag_source
        def src(_items=None, **_):
            ran.append("a")
            yield {"t": "a"}

        def probe(source, count=None, **_):
            seen["source"] = list(source)
            seen["count"] = list(count or ())
            return iter(())

        dispatcher = build_dispatcher(
            ModuleDefinition(name="src", sync_pipe=cast("SyncModuleWrapper", src)),
            ModuleDefinition(name="probe", sync_pipe=cast("SyncModuleWrapper", probe)),
        )
        plan = ExecutionPlan.from_workflow(_named_port_workflow(), dispatcher)

        assert plan.require_seed_target("default") == "b"

        with SyncExecution() as execution:
            assert list(execution.run(plan, seed=[{"x": 1}])) == []

        assert seen == {"source": [{"x": 1}], "count": [{"t": "a"}]}
        assert ran == ["a"]

    def test_run_starts_a_transformer_that_only_feeds_named_ports(self) -> None:
        # A value feeder: its items fill another node's named input, so it never
        # needs a seed of its own.
        concat = ModuleNode(
            id="c",
            name="strconcat",
            conf={"part": {"type": "text", "value": "extVal"}},
            options={"emit": True},
        )
        attr = {
            "key": {"type": "text", "value": "k"},
            "value": {"terminal": "v", "type": "text"},
        }
        conf = cast("Conf", {"attrs": [attr]})
        builder = ModuleNode(id="b", name="itembuilder", conf=conf)
        edge = StreamEdge(Endpoint("c", "out"), Endpoint("b", "in:v"))
        flow = build_workflow([concat, builder], edges=(edge,))
        plan = ExecutionPlan.from_workflow(flow, dispatcher)

        assert plan.is_self_starting("c")
        assert not plan.nodes["c"].is_source

        with SyncExecution() as execution:
            assert list(execution.run(plan)) == [{"k": "extVal"}]

    def test_run_never_starts_a_workflow_output_node_unseeded(self) -> None:
        dispatcher = build_dispatcher(
            ModuleDefinition(name="pass", sync_pipe=passthrough_pipe),
            ModuleDefinition(name="src", sync_pipe=tagged_source("b")),
        )
        a, b = ModuleNode(id="a", name="pass"), ModuleNode(id="b", name="src")
        edge = StreamEdge(Endpoint("a", "out"), Endpoint("b", "in:count"))
        outputs = {"default": Endpoint("a", "out"), "other": Endpoint("b", "out")}
        flow = build_workflow([a, b], edges=(edge,), outputs=outputs)
        plan = ExecutionPlan.from_workflow(flow, dispatcher)

        assert not plan.is_self_starting("a")

        with (
            SyncExecution() as execution,
            pytest.raises(InvalidPipelineError, match="requires a seed"),
        ):
            execution.run(plan)

    def test_run_accepts_sparse_positional_inputs(self) -> None:
        # A variadic fan-in reads its positional inputs as one ordered list, so a gap
        # in the numbering (a legacy _OTHER3 with no _OTHER2) executes, and the port
        # number rather than edge order still decides where each operand lands.
        dispatcher = build_dispatcher(
            ModuleDefinition(name="a", sync_pipe=tagged_source("a")),
            ModuleDefinition(name="b", sync_pipe=tagged_source("b")),
            ModuleDefinition(name="c", sync_pipe=tagged_source("c")),
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
        flow = build_workflow([a, b, c, u], edges=edges)

        assert run_plan(flow, dispatcher=dispatcher) == [
            {"t": "a"},
            {"t": "b"},
            {"t": "c"},
        ]

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

    def test_run_executes_only_selected_output_subgraph(self) -> None:
        ran: list[str] = []

        @tag_source
        def a_src(_items=None, **_):
            ran.append("a")
            yield {"x": 1}

        @tag_source
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

        assert run_plan(
            build_workflow([a, b], outputs=outputs), dispatcher=dispatcher
        ) == [{"x": 1}]
        assert ran == ["a"]

    @skipif_issync
    def test_run_drives_async_only_module_via_portal(self) -> None:
        @tag_source
        async def src(_items=None, **_):
            yield {"x": 1}
            yield {"x": 2}

        async_pipe = cast("AsyncModuleWrapper", src)
        dispatcher = build_dispatcher(
            ModuleDefinition(name="src", async_pipe=async_pipe)
        )
        assert run_plan(module_workflow("src"), dispatcher=dispatcher) == [
            {"x": 1},
            {"x": 2},
        ]

    @skipif_issync
    def test_run_chains_async_only_node_after_sync_node(self) -> None:
        @tag_source
        def src(_items=None, **_):
            yield {"x": 1}

        async def atag(items, **_):
            for row in items:
                yield {**row, "seen": True}

        dispatcher = build_dispatcher(
            ModuleDefinition(name="src", sync_pipe=cast("SyncModuleWrapper", src)),
            ModuleDefinition(name="atag", async_pipe=cast("AsyncModuleWrapper", atag)),
        )
        flow = build_chain(
            ModuleNode(id="a", name="src"), ModuleNode(id="b", name="atag")
        )

        assert run_plan(flow, dispatcher=dispatcher) == [{"x": 1, "seen": True}]

    @pytest.mark.parametrize(("make_seed", "expected"), SEEDS)
    def test_run_seeds_the_root_from_each_seed_shape(self, make_seed, expected) -> None:
        plan = _doubler_plan("double")

        with SyncExecution() as execution:
            assert list(execution.run(plan, seed=make_seed())) == expected

    def test_run_reads_a_dual_iterable_seed_synchronously(self) -> None:
        plan = _doubler_plan("double")

        with SyncExecution() as execution:
            assert list(execution.run(plan, seed=_DualSeed())) == [{"x": 2}]

    @pytest.mark.parametrize("make_seed", CLOSING_SEEDS)
    def test_run_closes_an_unfinished_seed_on_exit(self, make_seed) -> None:
        closed: list[str] = []
        plan = _doubler_plan("double")

        with SyncExecution() as execution:
            stream = execution.run(plan, seed=make_seed(closed))
            assert next(stream) == {"x": 2}
            assert closed == []

        assert closed == ["closed"]

    @skipif_issync
    def test_run_closes_an_async_native_source_on_exit(self) -> None:
        # Not an async generator, so only an explicit aclose can end it.
        closed: list[str] = []

        @tag_source
        def src(_items=None, **_):
            return ClosingAsyncIterator(closed)

        dispatcher = build_dispatcher(
            ModuleDefinition(name="asrc", async_pipe=cast("AsyncModuleWrapper", src))
        )
        plan = ExecutionPlan.from_workflow(module_workflow("asrc"), dispatcher)

        with SyncExecution() as execution:
            stream = execution.run(plan)
            assert next(stream) == {"x": 1}
            assert closed == []

        assert closed == ["closed"]

    def test_run_without_seed_keeps_forever_source(self) -> None:
        seen: list[object] = []

        @tag_source
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

    def test_run_seeds_a_positional_fan_in_rather_than_its_sources(self) -> None:
        dispatcher = build_dispatcher(
            ModuleDefinition(name="a_src", sync_pipe=tagged_source("a")),
            ModuleDefinition(name="b_src", sync_pipe=tagged_source("b")),
            ModuleDefinition(name="union", sync_pipe=union_pipe),
        )
        a = ModuleNode(id="a", name="a_src")
        b = ModuleNode(id="b", name="b_src")
        u = ModuleNode(id="u", name="union")
        edges = (
            StreamEdge(Endpoint("a", "out"), Endpoint("u", "in:1")),
            StreamEdge(Endpoint("b", "out"), Endpoint("u", "in:2")),
        )
        flow = build_workflow([a, b, u], edges=edges)
        plan = ExecutionPlan.from_workflow(flow, dispatcher=dispatcher)
        expected = [{"x": 1}, {"t": "a"}, {"t": "b"}]

        with SyncExecution() as execution:
            assert list(execution.run(plan, seed=[{"x": 1}])) == expected

    @pytest.mark.parametrize(("flow", "definitions", "match"), RUN_REJECTIONS)
    def test_run_rejects(self, flow, definitions, match) -> None:
        with pytest.raises(InvalidPipelineError, match=match):
            run_plan(flow, dispatcher=build_dispatcher(*definitions))

    @pytest.mark.parametrize(
        ("flow", "definitions", "output", "seed", "match"), UNKNOWN_OUTPUTS
    )
    def test_run_refuses_an_unknown_output_name(
        self, flow, definitions, output, seed, match
    ) -> None:
        plan = ExecutionPlan.from_workflow(flow, build_dispatcher(*definitions))

        with (
            SyncExecution() as execution,
            pytest.raises(InvalidPipelineError, match=match),
        ):
            execution.run(plan, output, seed=seed)

    def test_run_rejects_unprovided_resource(self) -> None:
        @tag_source
        def reader(items, **_):
            yield {}

        sync_pipe = cast("SyncModuleWrapper", reader)
        definition = ModuleDefinition(name="reader", sync_pipe=sync_pipe)
        dispatcher = build_dispatcher(definition)
        nodes = [ModuleNode(id="n", name="reader", resources={"slot": "primary"})]
        endpoint = Endpoint("n", "out")
        flow = build_workflow(
            nodes, resources=("primary",), outputs={"default": endpoint}
        )
        plan = ExecutionPlan.from_workflow(flow, dispatcher=dispatcher)

        with (
            SyncExecution() as execution,
            pytest.raises(InvalidPipelineError, match="not provided"),
        ):
            list(execution.run(plan))

    def test_run_rejects_seed_with_multiple_open_inputs(self) -> None:
        dispatcher = build_dispatcher(
            ModuleDefinition(name="pass", sync_pipe=passthrough_pipe),
            ModuleDefinition(name="merge", sync_pipe=passthrough_pipe),
        )
        a = ModuleNode(id="a", name="pass")
        b = ModuleNode(id="b", name="pass")
        m = ModuleNode(id="m", name="merge")
        edges = (
            StreamEdge(Endpoint("a", "out"), Endpoint("m", "in")),
            StreamEdge(Endpoint("b", "out"), Endpoint("m", "in:1")),
        )
        flow = build_workflow([a, b, m], edges=edges)
        plan = ExecutionPlan.from_workflow(flow, dispatcher=dispatcher)

        with (
            SyncExecution() as execution,
            pytest.raises(InvalidPipelineError, match="exactly one open input"),
        ):
            execution.run(plan, seed=[{"x": 1}])

    @pytest.mark.xfail(
        strict=True, reason="declaring a node as a value source is not yet implemented"
    )
    def test_run_never_starts_an_undeclared_value_feeder_unseeded(self) -> None:
        attr = {
            "key": {"type": "text", "value": "k"},
            "value": {"terminal": "v", "type": "text"},
        }
        conf = cast("Conf", {"attrs": [attr]})
        feeder = ModuleNode(id="h", name="hash", options={"emit": True})
        builder = ModuleNode(id="b", name="itembuilder", conf=conf)
        edge = StreamEdge(Endpoint("h", "out"), Endpoint("b", "in:v"))
        flow = build_workflow([feeder, builder], edges=(edge,))
        plan = ExecutionPlan.from_workflow(flow, dispatcher)

        with (
            SyncExecution() as execution,
            pytest.raises(InvalidPipelineError, match="requires a seed"),
        ):
            execution.run(plan)

    @pytest.mark.xfail(
        strict=True,
        raises=InvalidPipelineError,
        reason="root-derived stored-workflow subtypes are not yet implemented",
    )
    def test_run_starts_a_stored_source_workflow_that_declares_inputs(self) -> None:
        raw = '{"inputs": {"q": {"type": "string"}}, "nodes": [{"name": "forever"}]}'
        resolved = _build_resolved_workflow(
            "pipe_demo", Workflow.parse(raw), dispatcher
        )
        resolver = WorkflowResolver(module_store=MappingStore({"pipe_demo": resolved}))
        stored = ResolverDispatcher(module_registry, resolver)
        plan = ExecutionPlan.from_workflow(module_workflow("pipe_demo"), stored)

        with SyncExecution() as execution:
            assert next(iter(execution.run(plan))) == {"forever": True}

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
        flow = build_workflow(
            nodes, resources=("primary",), outputs={"default": Endpoint("n", "out")}
        )
        plan = ExecutionPlan.from_workflow(flow, dispatcher=dispatcher)
        events: list[str] = []
        context = Context().with_resource("primary", _lifecycle(events), lazy=True)

        with SyncExecution(context) as execution:
            assert list(execution.run(plan, seed=[{"x": 1}])) == [{"x": 1}]

        assert events == []


def _gen_counting(closed: list[bool]) -> Iterator[Item]:
    index = 0

    try:
        while True:
            yield {"x": index}
            index += 1
    finally:
        closed.append(True)


class _CountingIterator:
    """An endless closeable item iterator that is not a generator."""

    def __init__(self, closed: list[bool]) -> None:
        self.closed, self.index = closed, -1

    def __iter__(self) -> Self:
        return self

    def __next__(self) -> Item:
        self.index += 1
        return {"x": self.index}

    def close(self) -> None:
        self.closed.append(True)


COUNTING_SOURCES = [
    pytest.param(_gen_counting, id="generator"),
    pytest.param(_CountingIterator, id="closeable-iterator"),
]


async def _acollect(stream, seen):
    async for item in stream:
        seen.append(item)


class TestAsyncPlanRun:
    @async_test
    async def test_arun_executes_async_native_source(self) -> None:
        @tag_source
        async def src(_items=None, **_):
            yield {"x": 1}
            yield {"x": 2}

        async_pipe = cast("AsyncModuleWrapper", src)
        dispatcher = build_dispatcher(
            ModuleDefinition(name="src", async_pipe=async_pipe)
        )
        assert await arun_plan(module_workflow("src"), dispatcher=dispatcher) == [
            {"x": 1},
            {"x": 2},
        ]

    @async_test
    async def test_arun_chains_async_and_sync_worker_nodes(self) -> None:
        @tag_source
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
        flow = build_chain(a, b, ModuleNode(id="c", name="atag"))

        assert await arun_plan(flow, dispatcher=dispatcher) == [{"n": 2, "seen": True}]

    @async_test
    async def test_arun_forwards_node_options_as_call_kwargs(self) -> None:
        seen: dict[str, object] = {}

        @tag_source
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
        flow = build_workflow([node])

        assert await arun_plan(flow, dispatcher=dispatcher) == []
        assert seen["emit"] is True
        assert seen["conf"] == {}

    @async_test
    async def test_arun_leaves_the_default_input_empty_for_indexed_ports(self) -> None:
        seen: dict[str, object] = {}

        @tag_source
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
        flow = build_workflow([a, m], edges=(edge,))

        assert await arun_plan(flow, dispatcher=dispatcher) == [{"t": "a"}]
        assert seen["source"] == []

    @async_test
    async def test_arun_sync_worker_node_adapts_secondary_inputs(self) -> None:
        @tag_source
        async def asrc(_items=None, **_):
            yield {"t": "a"}

        @tag_source
        async def bsrc(_items=None, **_):
            yield {"t": "b"}

        @tag_source
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
        flow = build_workflow([a, b, c, m], edges=edges)

        assert await arun_plan(flow, dispatcher=dispatcher) == [
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

    @async_test
    async def test_arun_seeds_the_root_from_one_item(self) -> None:
        plan = _doubler_plan("adouble")

        async with AsyncExecution() as execution:
            stream = await execution.arun(plan, seed={"x": 5})
            assert [item async for item in stream] == [{"x": 10}]

    @async_test
    async def test_arun_reads_a_dual_iterable_seed_asynchronously(self) -> None:
        plan = _doubler_plan("adouble")

        async with AsyncExecution() as execution:
            stream = await execution.arun(plan, seed=_DualSeed())
            assert [item async for item in stream] == [{"x": 200}]

    @pytest.mark.parametrize("make_seed", CLOSING_SEEDS)
    @async_test
    async def test_arun_closes_an_unfinished_seed_on_exit(self, make_seed) -> None:
        closed: list[str] = []
        plan = _doubler_plan("adouble")

        async with AsyncExecution() as execution:
            stream = aiter(await execution.arun(plan, seed=make_seed(closed)))
            assert await anext(stream) == {"x": 2}
            assert closed == []

        assert closed == ["closed"]

    @async_test
    async def test_arun_without_seed_keeps_forever_source(self) -> None:
        seen: list[object] = []

        @tag_source
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
    async def test_arun_sync_only_source_raises_after_yielding_earlier_items(
        self,
    ) -> None:
        @tag_source
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

    @pytest.mark.parametrize("build", COUNTING_SOURCES)
    @async_test
    async def test_arun_sync_only_source_closes_on_early_exit(self, build) -> None:
        closed = []
        src = tag_source(lambda _items=None, **_: build(closed))
        sync_pipe = cast("SyncModuleWrapper", src)
        dispatcher = build_dispatcher(ModuleDefinition(name="src", sync_pipe=sync_pipe))
        plan = ExecutionPlan.from_workflow(
            module_workflow("src"), dispatcher=dispatcher
        )
        seen = []

        with fail_after(1):
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
    async def test_arun_sync_worker_node_closes_its_async_inputs_on_early_exit(
        self,
    ) -> None:
        # The sources stay referenced, so only the stream's own close can end them.
        closed, sources = [], []

        def tagged(tag):
            async def gen():
                try:
                    while True:
                        yield {"t": tag}
                finally:
                    closed.append(tag)

            @tag_source
            def src(_items=None, **_):
                sources.append(gen())
                return sources[-1]

            return cast("AsyncModuleWrapper", src)

        def interleave(items, others=None, **_):
            for row in zip(items, *(others or ()), strict=False):
                yield from row

        dispatcher = build_dispatcher(
            ModuleDefinition(name="asrc", async_pipe=tagged("a")),
            ModuleDefinition(name="bsrc", async_pipe=tagged("b")),
            ModuleDefinition(
                name="interleave", sync_pipe=cast("SyncModuleWrapper", interleave)
            ),
        )
        nodes = [
            ModuleNode(id="a", name="asrc"),
            ModuleNode(id="b", name="bsrc"),
            ModuleNode(id="m", name="interleave"),
        ]
        edges = (
            StreamEdge(Endpoint("a", "out"), Endpoint("m", "in")),
            StreamEdge(Endpoint("b", "out"), Endpoint("m", "in:1")),
        )
        flow = build_workflow(
            nodes, edges=edges, outputs={"default": Endpoint("m", "out")}
        )
        plan = ExecutionPlan.from_workflow(flow, dispatcher=dispatcher)
        upstream_closed = []

        with fail_after(1):
            async with AsyncExecution() as execution:
                stream = cast("AsyncItemGenerator", await execution.arun(plan))
                await anext(stream)
                await stream.aclose()
                upstream_closed = sorted(closed)

        assert upstream_closed == ["a", "b"]

    @async_test
    async def test_arun_native_async_node_closes_its_input_stream_on_early_exit(
        self,
    ) -> None:
        # The source stays referenced, so only the run's own close can end it.
        closed, sources = [], []

        async def gen():
            try:
                while True:
                    yield {"t": "a"}
            finally:
                closed.append("a")

        @tag_source
        def src(_items=None, **_):
            sources.append(gen())
            return sources[-1]

        async def passthrough(items, **_):
            async for item in items:
                yield item

        dispatcher = build_dispatcher(
            ModuleDefinition(name="asrc", async_pipe=cast("AsyncModuleWrapper", src)),
            ModuleDefinition(
                name="apass", async_pipe=cast("AsyncModuleWrapper", passthrough)
            ),
        )
        nodes = [ModuleNode(id="a", name="asrc"), ModuleNode(id="p", name="apass")]
        edges = (StreamEdge(Endpoint("a", "out"), Endpoint("p", "in")),)
        flow = build_workflow(
            nodes, edges=edges, outputs={"default": Endpoint("p", "out")}
        )
        plan = ExecutionPlan.from_workflow(flow, dispatcher=dispatcher)
        upstream_closed = []

        with fail_after(1):
            async with AsyncExecution() as execution:
                stream = cast("AsyncItemGenerator", await execution.arun(plan))
                await anext(stream)
                await stream.aclose()
                upstream_closed = list(closed)

        assert upstream_closed == ["a"]

    @async_test
    async def test_arun_unconsumed_sync_only_source_does_not_block_exit(self) -> None:
        @tag_source
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

        with fail_after(1):
            async with AsyncExecution() as execution:
                stream = await execution.arun(plan)
                assert stream is not None

    @async_test
    async def test_arun_sync_worker_node_reads_secondary_inputs_lazily(self) -> None:
        @tag_source
        async def asrc(_items=None, **_):
            yield {"t": "a"}

        @tag_source
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
        flow = build_workflow([a, b, m], edges=edges)
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

        @tag_source
        def src(_items=None, **_):
            threads.append(get_ident())
            yield {"x": 1}
            threads.append(get_ident())

        sync_pipe = cast("SyncModuleWrapper", src)
        dispatcher = build_dispatcher(ModuleDefinition(name="src", sync_pipe=sync_pipe))
        loop_thread = get_ident()

        assert await arun_plan(module_workflow("src"), dispatcher=dispatcher) == [
            {"x": 1}
        ]
        assert threads
        assert loop_thread not in threads
