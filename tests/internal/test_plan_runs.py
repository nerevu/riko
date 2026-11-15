"""Provides internal tests for running an ``ExecutionPlan``."""

from __future__ import annotations

from threading import get_ident
from typing import TYPE_CHECKING, cast

import pytest

from riko.bado.itertools import as_async
from riko.base._exceptions import InvalidPipelineError
from riko.definitions._context import Context
from riko.definitions._module_definition import ModuleDefinition
from riko.definitions._nodes import CallableNode, ModuleNode, StreamEdge
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
from riko.types.modules import ItemBuilderConf
from tests import async_test, skipif_issync
from tests._execution import (
    EMPTY,
    agen_source,
    arun_plan,
    awaitable_source,
    build_chain,
    build_dispatcher,
    build_doubler_plan,
    build_workflow,
    mark_loopable,
    module_workflow,
    passthrough_pipe,
    run_plan,
    tag_source,
    tagged_source,
)

if TYPE_CHECKING:
    from riko.types._streams import Item
    from riko.types._wrappers import AsyncModuleWrapper, SyncModuleWrapper
    from riko.types.modules import Conf

_SRC = ModuleDefinition(name="src", sync_pipe=tagged_source("a"))
_ECHO = cast("SyncModuleWrapper", lambda items, **_: iter(list(items)))
_SINK = ModuleDefinition(name="sink", sync_pipe=_ECHO)
_PROBE = ModuleDefinition(name="probe", sync_pipe=passthrough_pipe)

_PROCESSOR_PROBE = ModuleDefinition(
    name="probe", sync_pipe=mark_loopable(lambda item, **_: iter([item]))
)

_DOUBLED = [{"x": 2}, {"x": 4}]
_SRC_SINK = [ModuleNode(id="a", name="src"), ModuleNode(id="b", name="sink")]
_PORT_1_EDGE = StreamEdge(Endpoint("a", "out:1"), Endpoint("b", "in"))
_SRC_NODE = [ModuleNode(id="n", name="src")]
_PORT_1_OUTPUT = {"default": Endpoint("n", "out:1")}
_NEEDS_SEED = r"'b'.*requires a seed"
_NON_DEFAULT = "instead of 'out'"
_SRC_ECHO = ModuleDefinition(name="src", sync_pipe=passthrough_pipe)
_NOPE = "no workflow output 'nope'"
_RESERVED = "use a reserved name"
_TERMINAL_PART = {"terminal": "p", "type": "text"}
_SUBKEY_PART = {"subkey": "word", "type": "text"}
_WRAPPED_PART = {"type": "text", "value": "extVal"}
_URL_TERMINAL = {"terminal": "1_URL", "type": "url"}
_FAN_IN_RESULT = [{"x": "1"}]


@tag_source
def _plain_reader(stream, **kwargs):
    yield {"got": kwargs["resources"]["slot"]}


@tag_source
@operator()
def _decorated_reader(stream, objconf, tuples, **kwargs):
    yield {"got": kwargs["resources"]["slot"]}


def _named_port_workflow(name: str = "part") -> Workflow:
    a, b = ModuleNode(id="a", name="src"), ModuleNode(id="b", name="probe")
    edge = StreamEdge(Endpoint("a", "out"), Endpoint("b", f"in:{name}"))
    return build_workflow([a, b], edges=(edge,))


READERS = [
    pytest.param(_plain_reader, id="plain"),
    pytest.param(_decorated_reader, id="decorated"),
]


# Execution fails closed on ports other than 'out': only the bare 'out' port is
# executable, so a distinct 'out:1' source port or selected output is rejected
# rather than silently aliased to the node's 'out' stream. A named input port that
# shares a name with an argument every module call takes is rejected rather than
# overwriting that argument or being overwritten by it.
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
    *(
        pytest.param(_named_port_workflow(name), (_SRC, _PROBE), _RESERVED, id=name)
        for name in (
            "conf",
            "context",
            "embed",
            "others",
            "resources",
            "item",
            "emit",
            "assign",
            "field",
        )
    ),
    pytest.param(
        _named_port_workflow("count"),
        (_SRC, _PROCESSOR_PROBE),
        _RESERVED,
        id="in:count-processor",
    ),
]


UNKNOWN_OUTPUTS = [
    pytest.param(EMPTY, (), "extra", [{"x": 1}], "'extra'", id="empty-plan"),
    pytest.param(
        module_workflow("src"), (_SRC_ECHO,), "nope", None, _NOPE, id="absent"
    ),
]


class _DualSeed:
    """A seed that is both sync- and async-iterable, with different items each way."""

    def __iter__(self):
        return iter([{"x": 1}])

    def __aiter__(self):
        return as_async([{"x": 100}])


async def _awaitable_none() -> None:
    return None


# An async stream seed is the stream itself, never one item holding the stream
# object, and an awaitable seed is awaited once for its items; one resolving to
# ``None`` feeds nothing, as a missing seed does.
SEEDS = [
    pytest.param(lambda: {"x": 5}, [{"x": 10}], id="one-item"),
    pytest.param(agen_source, _DOUBLED, id="async-stream", marks=skipif_issync),
    pytest.param(awaitable_source, _DOUBLED, id="awaitable", marks=skipif_issync),
    pytest.param(_awaitable_none, [], id="awaitable-none", marks=skipif_issync),
    pytest.param(_DualSeed, [{"x": 2}], id="dual-iterable"),
]
ASYNC_SEEDS = [
    pytest.param(lambda: {"x": 5}, [{"x": 10}], id="one-item"),
    pytest.param(_awaitable_none, [], id="awaitable-none"),
    pytest.param(_DualSeed, [{"x": 200}], id="dual-iterable"),
]


def _resource_reader_plan(reader=_decorated_reader):
    sync_pipe = cast("SyncModuleWrapper", reader)
    dispatcher = build_dispatcher(ModuleDefinition(name="reader", sync_pipe=sync_pipe))
    nodes = [ModuleNode(id="n", name="reader", resources={"slot": "primary"})]
    flow = build_workflow(nodes, resources=("primary",))
    return ExecutionPlan.from_workflow(flow, dispatcher=dispatcher)


def _lifecycle(events: list[str]):
    def db():
        events.append("open")

        try:
            yield "conn"
        finally:
            events.append("close")

    return db


# A strconcat part, whether a stream reaches its in:p port, and whether it self-starts.
STRCONCAT_STARTS = [
    pytest.param("extVal", False, "extVal", id="literal"),
    pytest.param(_WRAPPED_PART, False, "extVal", id="wrapped-literal"),
    pytest.param(_TERMINAL_PART, True, "x", id="connected-terminal"),
    pytest.param(_TERMINAL_PART, False, None, id="unconnected-terminal"),
    pytest.param(_SUBKEY_PART, False, None, id="subkey"),
]
# A fetch url, whether a stream reaches its in:_1_URL port, and whether it self-starts.
SOURCE_STARTS = [
    pytest.param("file://riko/data/feed.xml", False, True, id="literal"),
    pytest.param(_URL_TERMINAL, True, True, id="normalized-terminal"),
    pytest.param(_URL_TERMINAL, False, False, id="unconnected-terminal"),
    pytest.param({"subkey": "link", "type": "url"}, False, False, id="subkey"),
    pytest.param({**_URL_TERMINAL, "subkey": ""}, True, True, id="empty-subkey"),
]


INPUT_SOURCES = [
    pytest.param(None, None, 1, id="schema-default"),
    pytest.param(Context(inputs={"q": 2}), None, 2, id="context"),
    pytest.param(None, {"q": 5}, 5, id="planned"),
    pytest.param(Context(inputs={"q": 2}), {"q": 5}, 5, id="planned-over-context"),
]


def _build_default_input_plan(default: int) -> ExecutionPlan:
    """Builds a plan whose one node emits the ``q`` input, defaulted to ``default``."""
    conf = cast("Conf", {"attrs": {"key": "q", "value": {"input": "q"}}})
    node = ModuleNode(id="b", name="itembuilder", conf=conf)
    schemas = {"q": {"type": "integer", "default": default}}
    flow = Workflow(input_schemas=schemas).with_node(node)
    return ExecutionPlan.from_workflow(flow, dispatcher)


def _ignore_part(item: Item, part: object) -> Item:
    return item


def _build_callable_fan_in() -> Workflow:
    """Builds a callable node that reads a second stream, so it runs whole-stream."""
    a = ModuleNode(
        id="a",
        name="itembuilder",
        conf=ItemBuilderConf({"attrs": [{"key": "x", "value": "1"}]}),
    )
    b = ModuleNode(
        id="b",
        name="itembuilder",
        conf=ItemBuilderConf({"attrs": [{"key": "y", "value": "2"}]}),
    )
    c = CallableNode(id="c", name="ignore_part", fn=_ignore_part)
    edges = (
        StreamEdge(Endpoint("a", "out"), Endpoint("c", "in")),
        StreamEdge(Endpoint("b", "out"), Endpoint("c", "in:part")),
    )
    outputs = {"default": Endpoint("c", "out")}
    return Workflow(nodes=[a, b, c], edges=edges, outputs=outputs)


async def _acollect(stream, seen):
    async for item in stream:
        seen.append(item)


def atagged_source(tag: str) -> AsyncModuleWrapper:
    """Builds a source module whose async pipe yields one item tagged ``tag``."""

    @tag_source
    async def src(_items=None, **_):
        yield {"t": tag}

    return cast("AsyncModuleWrapper", src)


class TestPlanRun:
    def test_run_maps_a_callable_node_over_a_stream_beside_a_second_one(self) -> None:
        flow = _build_callable_fan_in()
        assert not ExecutionPlan.from_workflow(flow, dispatcher).nodes["c"].is_mappable
        assert run_plan(flow) == _FAN_IN_RESULT

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
        def probe(source, part=None, **_):
            seen["source"] = list(source)
            seen["part"] = list(part or ())
            return iter(())

        dispatcher = build_dispatcher(
            ModuleDefinition(name="src", sync_pipe=tagged_source("a")),
            ModuleDefinition(name="probe", sync_pipe=cast("SyncModuleWrapper", probe)),
        )
        flow = _named_port_workflow()

        assert run_plan(flow, dispatcher=dispatcher) == []
        assert seen["source"] == [{"forever": True}]
        assert seen["part"] == [{"t": "a"}]

    def test_run_seeds_the_transformer_fed_only_through_a_named_port(self) -> None:
        seen: dict[str, object] = {}
        ran: list[str] = []

        @tag_source
        def src(_items=None, **_):
            ran.append("a")
            yield {"t": "a"}

        def probe(source, part=None, **_):
            seen["source"] = list(source)
            seen["part"] = list(part or ())
            return iter(())

        dispatcher = build_dispatcher(
            ModuleDefinition(name="src", sync_pipe=cast("SyncModuleWrapper", src)),
            ModuleDefinition(name="probe", sync_pipe=cast("SyncModuleWrapper", probe)),
        )
        plan = ExecutionPlan.from_workflow(_named_port_workflow(), dispatcher)

        assert plan.require_seed_target("default") == "b"

        with SyncExecution() as execution:
            assert list(execution.run(plan, seed=[{"x": 1}])) == []

        assert seen == {"source": [{"x": 1}], "part": [{"t": "a"}]}
        assert ran == ["a"]

    @pytest.mark.parametrize(("part", "connected", "expected"), STRCONCAT_STARTS)
    def test_strconcat_starts_when_it_reads_no_default_input(
        self, part: object, connected: bool, expected: str | None
    ) -> None:
        conf, emit = cast("Conf", {"part": part}), {"emit": True}
        concat = ModuleNode(id="c", name="strconcat", conf=conf, options=emit)
        literal = ModuleNode(id="s", name="strconcat", conf={"part": "x"}, options=emit)
        edge = StreamEdge(Endpoint("s", "out"), Endpoint("c", "in:p"))
        nodes, edges = ([concat, literal], (edge,)) if connected else ([concat], ())
        outputs = {"default": Endpoint("c", "out")}
        flow = build_workflow(nodes, edges=edges, outputs=outputs)
        plan = ExecutionPlan.from_workflow(flow, dispatcher)

        assert plan.nodes["c"].is_self_starting is (expected is not None)
        assert not plan.nodes["c"].is_source

        with SyncExecution() as execution:
            if expected is None:
                with pytest.raises(InvalidPipelineError, match="requires a seed"):
                    execution.run(plan)
            else:
                assert list(execution.run(plan)) == [expected]

    @pytest.mark.parametrize(("url", "connected", "expected"), SOURCE_STARTS)
    def test_source_starts_only_when_it_reads_no_default_input(
        self, url: object, connected: bool, expected: bool
    ) -> None:
        source = ModuleNode(id="f", name="fetch", conf=cast("Conf", {"url": url}))
        feeder = ModuleNode(id="s", name="strconcat", conf={"part": "x"})
        edge = StreamEdge(Endpoint("s", "out"), Endpoint("f", "in:_1_URL"))
        nodes, edges = ([source, feeder], (edge,)) if connected else ([source], ())
        outputs = {"default": Endpoint("f", "out")}
        flow = build_workflow(nodes, edges=edges, outputs=outputs)
        plan = ExecutionPlan.from_workflow(flow, dispatcher)

        assert plan.nodes["f"].is_self_starting is expected

    def test_run_never_starts_a_workflow_output_node_unseeded(self) -> None:
        dispatcher = build_dispatcher(
            ModuleDefinition(name="pass", sync_pipe=passthrough_pipe),
            ModuleDefinition(name="src", sync_pipe=tagged_source("b")),
        )
        a, b = ModuleNode(id="a", name="pass"), ModuleNode(id="b", name="src")
        edge = StreamEdge(Endpoint("a", "out"), Endpoint("b", "in:part"))
        outputs = {"default": Endpoint("a", "out"), "other": Endpoint("b", "out")}
        flow = build_workflow([a, b], edges=(edge,), outputs=outputs)
        plan = ExecutionPlan.from_workflow(flow, dispatcher)

        assert not plan.nodes["a"].is_self_starting

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
        plan = build_doubler_plan("double")

        with SyncExecution() as execution:
            assert list(execution.run(plan, seed=make_seed())) == expected

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

    def test_run_starts_a_stored_source_workflow_with_input_schemas(self) -> None:
        schemas = '{"q": {"type": "string", "default": "x"}}'
        raw = f'{{"input_schemas": {schemas}, "nodes": [{{"name": "forever"}}]}}'
        resolved = _build_resolved_workflow(
            "pipe_demo", Workflow.parse(raw), dispatcher
        )
        resolver = WorkflowResolver(module_store=MappingStore({"pipe_demo": resolved}))
        stored = ResolverDispatcher(module_registry, resolver)
        plan = ExecutionPlan.from_workflow(module_workflow("pipe_demo"), stored)

        with SyncExecution() as execution:
            assert next(iter(execution.run(plan))) == {"forever": True}

    @pytest.mark.parametrize(("given", "values", "expected"), INPUT_SOURCES)
    def test_run_uses_the_inputs_its_plan_was_built_from(
        self, given: Context | None, values: dict[str, int] | None, expected: int
    ) -> None:
        plan = _build_default_input_plan(1)
        planned = plan if values is None else plan.with_inputs(values)

        with SyncExecution(given) as execution:
            assert list(execution.run(planned)) == [{"q": expected}]

    def test_run_resolves_each_plan_s_own_input_default(self) -> None:
        """A later run of another plan does not inherit an earlier run's inputs."""
        with SyncExecution() as execution:
            first = list(execution.run(_build_default_input_plan(1)))
            second = list(execution.run(_build_default_input_plan(2)))
            assert (first, second) == ([{"q": 1}], [{"q": 2}])

    def test_a_stored_workflow_ignores_the_outer_context_s_other_inputs(self) -> None:
        conf = {"attrs": {"key": "q", "value": {"input": "q"}}}
        raw = {
            "input_schemas": {"q": {"type": "string", "default": "x"}},
            "nodes": [{"name": "itembuilder", "conf": conf}],
        }
        resolved = _build_resolved_workflow(
            "pipe_demo", Workflow.parse(raw), dispatcher
        )
        resolver = WorkflowResolver(module_store=MappingStore({"pipe_demo": resolved}))
        stored = ResolverDispatcher(module_registry, resolver)
        plan = ExecutionPlan.from_workflow(module_workflow("pipe_demo"), stored)
        context = Context(inputs={"q": "y", "other": 1})

        with SyncExecution(context) as execution:
            assert list(execution.run(plan)) == [{"q": "y"}]

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
        plan = _resource_reader_plan()

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

    def test_run_never_starts_a_non_self_starting_module_unseeded(self) -> None:
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
        raises=AssertionError,
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
        flow = build_workflow(nodes, resources=("primary",))
        plan = ExecutionPlan.from_workflow(flow, dispatcher=dispatcher)
        events: list[str] = []
        context = Context().with_resource("primary", _lifecycle(events), lazy=True)

        with SyncExecution(context) as execution:
            assert list(execution.run(plan, seed=[{"x": 1}])) == [{"x": 1}]

        assert events == []


class TestAsyncPlanRun:
    @async_test
    async def test_arun_maps_a_callable_node_over_a_stream_beside_a_second_one(
        self,
    ) -> None:
        assert await arun_plan(_build_callable_fan_in()) == _FAN_IN_RESULT

    @async_test
    async def test_arun_resolves_each_plan_s_own_input_default(self) -> None:
        """A later run of another plan does not inherit an earlier run's inputs."""
        async with AsyncExecution() as execution:
            first = [
                i async for i in await execution.arun(_build_default_input_plan(1))
            ]
            second = [
                i async for i in await execution.arun(_build_default_input_plan(2))
            ]
            assert (first, second) == ([{"q": 1}], [{"q": 2}])

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

        async def amerge(source, others=None, **_):
            seen["source"] = [row async for row in source]

            for other in others or ():
                async for row in other:
                    yield row

        dispatcher = build_dispatcher(
            ModuleDefinition(name="asrc", async_pipe=atagged_source("a")),
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
        def merge(items, others=None, label=None, **_):
            yield from items

            for other in others or ():
                yield from other

            for row in label or ():
                yield {"labeled": row["t"]}

        dispatcher = build_dispatcher(
            ModuleDefinition(name="asrc", async_pipe=atagged_source("a")),
            ModuleDefinition(name="bsrc", async_pipe=atagged_source("b")),
            ModuleDefinition(name="csrc", async_pipe=atagged_source("c")),
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

    @pytest.mark.parametrize(("make_seed", "expected"), ASYNC_SEEDS)
    @async_test
    async def test_arun_seeds_the_root_from_each_seed_shape(
        self, make_seed, expected
    ) -> None:
        plan = build_doubler_plan("adouble")

        async with AsyncExecution() as execution:
            stream = await execution.arun(plan, seed=make_seed())
            assert [item async for item in stream] == expected

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

    @async_test
    async def test_arun_sync_worker_node_reads_secondary_inputs_lazily(self) -> None:
        @tag_source
        async def bsrc(_items=None, **_):
            yield {"t": "b"}
            raise RuntimeError("secondary later")

        def merge(items, others=None, **_):
            yield from items

            for other in others or ():
                yield from other

        dispatcher = build_dispatcher(
            ModuleDefinition(name="asrc", async_pipe=atagged_source("a")),
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
