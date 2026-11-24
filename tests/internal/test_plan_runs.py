"""Provides internal tests for running an ``ExecutionPlan``."""

from __future__ import annotations

from dataclasses import replace
from functools import partial
from threading import get_ident
from typing import TYPE_CHECKING, Self, cast

import pytest

from riko.bado._backend import async_sleep, lowlevel
from riko.bado.itertools import alist, as_async
from riko.base._config import settings
from riko.base._exceptions import InvalidPipelineError, PipelineError
from riko.definitions._context import Context
from riko.definitions._module_definition import ModuleDefinition
from riko.definitions._nodes import CallableNode, ModuleNode, StreamEdge
from riko.definitions._resource_definition import Resource
from riko.definitions._settings import ExecutionSettings
from riko.definitions._workflow_definition import Workflow
from riko.execution import _async_execution as async_execution_module
from riko.execution import _sync_execution as sync_execution_module
from riko.execution._async_execution import AsyncExecution
from riko.execution._prepared import ExecutionPlan
from riko.execution._sync_execution import SyncExecution
from riko.modules import split as split_module
from riko.modules._decorators import operator, splitter
from riko.modules.split import async_pipe as async_split
from riko.modules.split import pipe as split_pipe
from riko.modules.union import async_pipe as async_union
from riko.modules.union import pipe as union_pipe
from riko.runtime._module_registry import module_registry
from riko.runtime._resolver import ResolverDispatcher, dispatcher
from riko.runtime._workflow_resolver import WorkflowResolver, _build_resolved_workflow
from riko.runtime._workflow_stores import MappingStore
from riko.types._workflow import Endpoint
from riko.types.modules import ItemBuilderConf
from tests import X_ROW, async_test, skipif_sync
from tests._execution import (
    ASRC_NODE,
    BSRC_NODE,
    EMPTY,
    M_ARELAY_DEFINITION,
    M_NODE,
    MERGE_NODE,
    OUTPUTS_AB,
    PASS_DEFINITION,
    PASS_NODE,
    PROBE_NODE,
    PROCESSOR_PROBE,
    Q_CONF,
    Q_NODE,
    SPLIT_NODE,
    SRC_DEFINITION,
    SRC_ECHO_DEFINITION,
    SRC_NODE,
    UNION_NODE,
    AsyncPipeFunc,
    RecordingBranch,
    agen_source,
    arelay_pipe,
    arun_plan,
    awaitable_source,
    build_async_definition,
    build_dispatcher,
    build_doubler_plan,
    build_module_plan,
    build_sync_definition,
    build_workflow,
    double,
    mark_async_loopable,
    mark_loopable,
    module_workflow,
    passthrough_pipe,
    require_prepared_node,
    run_plan,
    tag_source,
    tagged_source,
)
from tests._streams import AsyncPullLog, PullLog

if TYPE_CHECKING:
    from collections.abc import Iterable

    from riko.definitions._workflow_definition import DocumentLike
    from riko.types._streams import AsyncStream, Cascade, Item, Stream
    from riko.types._wrappers import AsyncModuleWrapper
    from riko.types.modules import Conf

_PROBE = build_sync_definition(passthrough_pipe, name="probe")
_DOUBLED = [{"x": 2}, {"x": 4}]
_SOURCE_ROWS = [{"x": index} for index in range(3)]
_PORT_1_EDGE = StreamEdge(Endpoint("a", "out:1"), Endpoint("b", "in"))
_PORT_1_OUTPUT = {"default": Endpoint("a", "out:1")}
_NEEDS_SEED = r"'b'.*requires a seed"
_NO_OUT_1 = r"node 'a' has no output port 'out:1'; it produces \('out',\)"
_NOPE = "no workflow output 'nope'"
_RESERVED = "use a reserved name"
_TERMINAL_PART = {"terminal": "p", "type": "text"}
_SUBKEY_PART = {"subkey": "word", "type": "text"}
_WRAPPED_PART = {"type": "text", "value": "extVal"}
_FAN_IN_RESULT = [{"x": "1"}]
_LONE_STREAM = "splitter node 's' yielded 1 streams but declares 2"
_EXTRA_STREAM = "splitter node 's' yielded more than 2 streams but declares 2"
_UNION = build_sync_definition(union_pipe, name="union")

_MERGE_EDGES = (
    StreamEdge(Endpoint("a", "out"), Endpoint("m", "in")),
    StreamEdge(Endpoint("b", "out"), Endpoint("m", "in:1")),
)

_A_SRC = build_sync_definition(tagged_source("a"), name="a")
_B_SRC = build_sync_definition(tagged_source("b"), name="b")
_SIDE = build_sync_definition(tagged_source("side"), name="side")
_A_NODE = ModuleNode(id="a", name="a")
_B_NODE = ModuleNode(id="b", name="b")
_SIDE_NODE = ModuleNode(id="b", name="side")
_A_PASS_NODE = ModuleNode(id="a", name="pass")

_DUAL_PROBE = ModuleDefinition(
    name="probe", sync_pipe=passthrough_pipe, async_pipe=arelay_pipe
)


@splitter(objectify=False)
def _lone_branch(stream: Stream, _: object, __: object, **___: object) -> Cascade:
    return iter([stream])


_SPLIT_PROBE = build_sync_definition(_lone_branch, name="probe")


@tag_source
@operator()
def _decorated_reader(stream, objconf, tuples, **kwargs):
    yield {"got": kwargs["resources"]["slot"]}


_READER_PROBE = build_sync_definition(_decorated_reader, name="probe")
_NOT_ITERATOR = r"module 'src' returned a list\. A pipe must return an iterator"

_NOT_ASYNC_ITERATOR = (
    r"module 'src' returned a list\. An async_pipe must return an async iterator"
)


@splitter(objectify=False)
def _doubled_branches(stream: Stream, _: object, __: object, **___: object) -> Cascade:
    items = list(stream)
    return iter([iter(items * 2), iter(items * 2)])


_DOUBLED_SPLIT = build_sync_definition(_doubled_branches, name="split")


def _fan_out_workflow(*, split: bool, output: str = "u") -> Workflow:
    """Builds ``a`` feeding ``b`` and ``c`` (through a split node or not) into ``u``."""
    source, port, split_nodes, split_edges = "a", "out", [], []

    if split:
        source, port = "s", "out:1"
        split_nodes = [SPLIT_NODE]
        split_edges = [StreamEdge(Endpoint("a", "out"), Endpoint("s", "in"))]

    nodes = [
        SRC_NODE,
        *split_nodes,
        PROBE_NODE,
        ModuleNode(id="c", name="probe"),
        UNION_NODE,
    ]
    edges = (
        *split_edges,
        StreamEdge(Endpoint(source, "out"), Endpoint("b", "in")),
        StreamEdge(Endpoint(source, port), Endpoint("c", "in")),
        StreamEdge(Endpoint("b", "out"), Endpoint("u", "in")),
        StreamEdge(Endpoint("c", "out"), Endpoint("u", "in:1")),
    )
    endpoint = Endpoint("s", "out:1") if output == "s" else Endpoint(output, "out")
    return build_workflow(nodes, edges=edges, outputs={"default": endpoint})


_SPLIT_FLOW = _fan_out_workflow(split=True)
_SPLIT_BRANCH_FLOW = _fan_out_workflow(split=True, output="s")


def atagged_source(tag: str) -> AsyncModuleWrapper:
    """Builds a source module whose async pipe yields one item tagged ``tag``."""

    @tag_source
    async def src(_items=None, **_):
        yield {"t": tag}

    return cast("AsyncModuleWrapper", src)


_ASRC = build_async_definition(atagged_source("a"), name="asrc")


def _rows_source(rows: Iterable[Item]) -> ModuleDefinition:
    """Defines a source that yields each of ``rows``."""

    @tag_source
    def src(_items=None, **_):
        yield from map(dict, rows)

    return build_sync_definition(src)


def _fan_out_dispatcher(
    rows: Iterable[Item], *, native: bool = False
) -> ResolverDispatcher:
    """Builds the fan-out modules, async-only ``split`` and ``union`` if ``native``."""
    if native:
        split = build_async_definition(async_split, name="split")
        union = build_async_definition(async_union, name="union")
    else:
        split = build_sync_definition(split_pipe, name="split")
        union = _UNION

    return build_dispatcher(_rows_source(rows), _PROBE, split, union)


def _counted_branch_dispatcher(
    count: int, *, native: bool
) -> tuple[ResolverDispatcher, PullLog[Stream] | AsyncPullLog[AsyncStream]]:
    """
    Builds the fan-out modules with a ``split`` that yields ``count`` branches.

    The ``split`` declares two branches and is async-only if ``native``. The returned
    log records each branch pulled from it.
    """
    sync_branches: PullLog[Stream] = PullLog(iter(()) for _ in range(count))
    async_branches: AsyncPullLog[AsyncStream]
    async_branches = AsyncPullLog(as_async(()) for _ in range(count))
    branches: PullLog[Stream] | AsyncPullLog[AsyncStream]

    @splitter(objectify=False)
    def split(_stream: Stream, _: object, __: object, **___: object) -> Cascade:
        return sync_branches

    @splitter(objectify=False)
    async def asplit(_stream, _: object, __: object, **___: object):
        return async_branches

    if native:
        branches = async_branches
        split_def = build_async_definition(asplit, name="split")
    else:
        branches = sync_branches
        split_def = build_sync_definition(split, name="split")

    source = _rows_source(_SOURCE_ROWS)
    return (build_dispatcher(source, _PROBE, split_def, _UNION), branches)


class _AsyncRecordingBranch(RecordingBranch):
    """The async twin of ``RecordingBranch``."""

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> Item:
        try:
            item = self.__next__()
        except StopIteration:
            raise StopAsyncIteration from None

        return item

    async def aclose(self) -> None:
        self.close()


def _recording_split_dispatcher(
    events: list[str], *, native: bool
) -> ResolverDispatcher:
    """
    Builds the fan-out modules with a ``split`` whose branches record reads and closes.

    The ``split`` is async-only if ``native``.
    """

    @splitter(objectify=False)
    def split(stream: Stream, _: object, __: object, **___: object) -> Cascade:
        items = list(stream)
        tags = ("b0", "b1")
        return iter([RecordingBranch(items, events, tag) for tag in tags])

    @splitter(objectify=False)
    async def asplit(stream, _: object, __: object, **___: object):
        items = await alist(stream)
        tags = ("b0", "b1")
        return as_async([_AsyncRecordingBranch(items, events, tag) for tag in tags])

    if native:
        split_def = build_async_definition(asplit, name="split")
    else:
        split_def = build_sync_definition(split, name="split")

    return build_dispatcher(_rows_source(_SOURCE_ROWS), _PROBE, split_def, _UNION)


@tag_source
def _plain_reader(stream, **kwargs):
    yield {"got": kwargs["resources"]["slot"]}


def _named_port_workflow(name: str = "part") -> Workflow:
    edge = StreamEdge(Endpoint("a", "out"), Endpoint("b", f"in:{name}"))
    return build_workflow([SRC_NODE, PROBE_NODE], edges=(edge,))


READERS = [
    pytest.param(_plain_reader, id="plain"),
    pytest.param(_decorated_reader, id="decorated"),
]

# An ordinary module produces only its 'out' port, so an 'out:1' source port or
# selected output is rejected rather than silently aliased to the node's 'out'
# stream. A named input port that shares a name with an argument every module call
# takes, or with a parameter a module's pipe or parser fills by position, is rejected
# rather than overwriting that argument or being overwritten by it.
RUN_REJECTIONS = [
    pytest.param(
        build_workflow([SRC_NODE, PASS_NODE], edges=(_PORT_1_EDGE,)),
        (SRC_DEFINITION, PASS_DEFINITION),
        _NO_OUT_1,
        id="nondefault-source-output-port",
    ),
    pytest.param(
        build_workflow([SRC_NODE], outputs=_PORT_1_OUTPUT),
        (SRC_DEFINITION,),
        _NO_OUT_1,
        id="nondefault-selected-output-port",
    ),
    pytest.param(
        _named_port_workflow(),
        (SRC_DEFINITION, _PROBE),
        _NEEDS_SEED,
        id="transformer-fed-only-through-a-named-port",
    ),
    *(
        pytest.param(
            _named_port_workflow(name), (SRC_DEFINITION, _PROBE), _RESERVED, id=name
        )
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
        (SRC_DEFINITION, PROCESSOR_PROBE),
        _RESERVED,
        id="in:count-processor",
    ),
    pytest.param(
        _named_port_workflow("source"),
        (SRC_DEFINITION, _PROBE),
        _RESERVED,
        id="plain-pipe-first-parameter",
    ),
    pytest.param(
        _named_port_workflow("items"),
        (SRC_DEFINITION, _DUAL_PROBE),
        _RESERVED,
        id="async-pipe-first-parameter",
    ),
    pytest.param(
        _named_port_workflow("stream"),
        (SRC_DEFINITION, _SPLIT_PROBE),
        _RESERVED,
        id="splitter-parser-first-parameter",
    ),
    pytest.param(
        _named_port_workflow("tuples"),
        (SRC_DEFINITION, _READER_PROBE),
        _RESERVED,
        id="operator-parser-positional-parameter",
    ),
]


UNKNOWN_OUTPUTS = [
    pytest.param(EMPTY, (), "extra", [{"x": 1}], "'extra'", id="empty-plan"),
    pytest.param(
        module_workflow("src"), (SRC_ECHO_DEFINITION,), "nope", None, _NOPE, id="absent"
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
    pytest.param(agen_source, _DOUBLED, id="async-stream", marks=skipif_sync),
    pytest.param(awaitable_source, _DOUBLED, id="awaitable", marks=skipif_sync),
    pytest.param(_awaitable_none, [], id="awaitable-none", marks=skipif_sync),
    pytest.param(_DualSeed, [{"x": 2}], id="dual-iterable"),
]
ASYNC_SEEDS = [
    pytest.param(lambda: {"x": 5}, [{"x": 10}], id="one-item"),
    pytest.param(_awaitable_none, [], id="awaitable-none"),
    pytest.param(_DualSeed, [{"x": 200}], id="dual-iterable"),
]


def _resource_reader_plan(reader=_decorated_reader):
    dispatcher = build_dispatcher(build_sync_definition(reader, name="reader"))
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


INPUT_SOURCES = [
    pytest.param(None, None, 1, id="schema-default"),
    pytest.param(Context(inputs={"q": 2}), None, 2, id="context"),
    pytest.param(None, {"q": 5}, 5, id="planned"),
    pytest.param(Context(inputs={"q": 2}), {"q": 5}, 5, id="planned-over-context"),
]
SPLITTERS = [
    pytest.param(False, id="sync-split"),
    pytest.param(True, id="async-split", marks=skipif_sync),
]
# The streams a splitter declaring two yields, the error, and the streams it pulls.
STREAM_COUNTS = [
    pytest.param(1, _LONE_STREAM, 1, id="fewer"),
    pytest.param(3, _EXTRA_STREAM, 3, id="more"),
    pytest.param(10, _EXTRA_STREAM, 3, id="pull-count"),
]


async def _alist_item(item=None, **_):
    return [item]


# A pipe that returns a list instead of an iterator, over its whole input or per item.
LIST_RETURNS = [
    pytest.param(tag_source(lambda _=None, **__: [{"x": 1}]), id="whole-stream"),
    pytest.param(
        tag_source(mark_loopable(lambda _=None, **__: [{"x": 1}])), id="per-item"
    ),
]
ASYNC_LIST_RETURNS = [
    pytest.param(tag_source(lambda _=None, **__: [{"x": 1}]), id="whole-stream"),
    pytest.param(tag_source(mark_async_loopable(_alist_item)), id="per-item"),
]
ASYNC_FAN_OUTS = [
    pytest.param(False, False, id="one-port"),
    pytest.param(True, False, id="sync-split"),
    pytest.param(True, True, id="async-split"),
]


def _build_default_input_plan(default: int) -> ExecutionPlan:
    """Builds a plan whose one node emits the ``q`` input, defaulted to ``default``."""
    schemas = {"q": {"type": "integer", "default": default}}
    flow = Workflow(input_schemas=schemas).with_nodes(Q_NODE)
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


def _build_stored_plan(raw: DocumentLike) -> ExecutionPlan:
    """Builds a plan whose one node runs the stored workflow ``raw`` parses to."""
    module = _build_resolved_workflow("pipe_demo", Workflow.parse(raw), dispatcher)
    resolver = WorkflowResolver(module_store=MappingStore({"pipe_demo": module}))
    stored = ResolverDispatcher(module_registry, resolver)
    return build_module_plan(stored, "pipe_demo")


async def _acollect(stream, seen):
    async for item in stream:
        seen.append(item)


def _ident_source(pulled: set[int]) -> ModuleDefinition:
    """Defines a three-item sync source that records each thread it yields on."""

    @tag_source
    def src(_items=None, **_):
        for x in range(3):
            pulled.add(get_ident())
            yield {"x": x}

    return build_sync_definition(src)


def _relay_reader(
    pulled: set[int], relayed: set[int]
) -> tuple[Workflow, ResolverDispatcher]:
    """Plans a sync source read by an async-only relay that records its threads."""

    async def relay(source, **_):
        async for item in as_async(source):
            relayed.add(get_ident())
            yield item

    dispatcher = build_dispatcher(
        _ident_source(pulled), build_async_definition(relay, name="m")
    )
    flow = Workflow().with_nodes(SRC_NODE, M_NODE)
    return flow, dispatcher


def _split_reader(
    output: str, pulled: set[int], relayed: set[int]
) -> tuple[Workflow, ResolverDispatcher]:
    """Plans a sync source split by an async-only splitter that records its threads."""

    @splitter(objectify=False)
    async def asplit(stream, _: object, __: object, **___: object):
        items = []

        async for item in as_async(stream):
            relayed.add(get_ident())
            items.append(item)

        return as_async([as_async(items), as_async(items)])

    split = build_async_definition(asplit, name="split")
    dispatcher = build_dispatcher(_ident_source(pulled), _PROBE, split, _UNION)
    return _fan_out_workflow(split=True, output=output), dispatcher


ASYNC_ONLY_READERS = [
    pytest.param(_relay_reader, [0, 1, 2], id="relay"),
    pytest.param(partial(_split_reader, "u"), [0, 0, 1, 1, 2, 2], id="split-to-union"),
    pytest.param(partial(_split_reader, "c"), [0, 1, 2], id="split-to-reader"),
]


class _LoopBoundHandle:
    """An async iterable that opens its iterator only on a running event loop."""

    def __aiter__(self) -> AsyncStream:
        lowlevel.current_token()
        return agen_source()


class TestPlanRun:
    def test_run_maps_a_callable_node_over_a_stream_beside_a_second_one(self) -> None:
        flow = _build_callable_fan_in()
        plan = ExecutionPlan.from_workflow(flow, dispatcher)
        assert not require_prepared_node(plan, "c").is_mappable
        assert run_plan(flow) == _FAN_IN_RESULT

    def test_run_executes_single_source_node(self) -> None:
        @tag_source
        def src(_items=None, **_):
            yield {"x": 1}
            yield {"x": 2}

        dispatcher = build_dispatcher(build_sync_definition(src))
        assert run_plan(module_workflow("src"), dispatcher=dispatcher) == [
            {"x": 1},
            {"x": 2},
        ]

    def test_run_chains_nodes_through_stream_edge(self) -> None:
        @tag_source
        def src(_items=None, **_):
            yield {"x": 1}
            yield {"x": 2}

        dispatcher = build_dispatcher(
            build_sync_definition(src), build_sync_definition(double, name="double")
        )
        flow = Workflow().with_nodes(SRC_NODE, ModuleNode(id="b", name="double"))

        assert run_plan(flow, dispatcher=dispatcher) == _DOUBLED

    def test_run_forwards_node_options_as_call_kwargs(self) -> None:
        seen: dict[str, object] = {}

        @tag_source
        def probe(source, **kwargs):
            seen["emit"] = kwargs.get("emit")
            seen["conf"] = dict(kwargs["conf"])
            return iter(())

        dispatcher = build_dispatcher(build_sync_definition(probe, name="probe"))
        node = ModuleNode(id="n", name="probe", options={"emit": True})
        flow = build_workflow([node])

        assert run_plan(flow, dispatcher=dispatcher) == []
        assert seen["emit"] is True
        assert seen["conf"] == {}

    @pytest.mark.parametrize("port", ["side", "options", "wrapper"])
    def test_run_wires_a_named_input_port_as_a_kwarg(self, port) -> None:
        def joiner(items, **kwargs):
            yield from items
            yield from kwargs.get(port) or ()

        dispatcher = build_dispatcher(
            _A_SRC, _SIDE, build_sync_definition(joiner, name="joiner")
        )
        j = ModuleNode(id="j", name="joiner")
        edges = (
            StreamEdge(Endpoint("a", "out"), Endpoint("j", "in")),
            StreamEdge(Endpoint("b", "out"), Endpoint("j", f"in:{port}")),
        )
        flow = build_workflow([_A_NODE, _SIDE_NODE, j], edges=edges)

        assert run_plan(flow, dispatcher=dispatcher) == [{"t": "a"}, {"t": "side"}]

    def test_run_leaves_the_default_input_empty_with_only_indexed_ports_wired(
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
            SRC_DEFINITION, build_sync_definition(merge, name="merge")
        )
        edge = StreamEdge(Endpoint("a", "out"), Endpoint("m", "in:1"))
        flow = build_workflow([SRC_NODE, MERGE_NODE], edges=(edge,))

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
            SRC_DEFINITION, build_sync_definition(probe, name="probe")
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
            build_sync_definition(src), build_sync_definition(probe, name="probe")
        )
        plan = ExecutionPlan.from_workflow(_named_port_workflow(), dispatcher)

        assert plan.require_seed_target("default") == "b"

        with SyncExecution() as execution:
            assert list(execution.run(plan, seed=X_ROW)) == []

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

    def test_run_never_starts_a_workflow_output_node_unseeded(self) -> None:
        dispatcher = build_dispatcher(PASS_DEFINITION, _B_SRC)
        edge = StreamEdge(Endpoint("a", "out"), Endpoint("b", "in:part"))
        flow = build_workflow(
            [_A_PASS_NODE, _B_NODE], edges=(edge,), outputs=OUTPUTS_AB
        )
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
            _A_SRC,
            _B_SRC,
            build_sync_definition(tagged_source("c"), name="c"),
            ModuleDefinition(
                name="union", sync_pipe=union_pipe, async_pipe=async_union
            ),
        )
        c = ModuleNode(id="c", name="c")
        edges = (
            StreamEdge(Endpoint("a", "out"), Endpoint("u", "in")),
            StreamEdge(Endpoint("c", "out"), Endpoint("u", "in:3")),
            StreamEdge(Endpoint("b", "out"), Endpoint("u", "in:1")),
        )
        flow = build_workflow([_A_NODE, _B_NODE, c, UNION_NODE], edges=edges)

        assert run_plan(flow, dispatcher=dispatcher) == [
            {"t": "a"},
            {"t": "b"},
            {"t": "c"},
        ]

    @pytest.mark.parametrize("split", [False, True], ids=["one-port", "split"])
    def test_run_fans_out_every_item_to_each_consumer(self, split: bool) -> None:
        source = PullLog(_SOURCE_ROWS)
        flow = _fan_out_workflow(split=split)
        dispatcher = _fan_out_dispatcher(source)

        assert run_plan(flow, dispatcher=dispatcher) == _SOURCE_ROWS * 2
        assert source.pulled == tuple(_SOURCE_ROWS)

    @pytest.mark.parametrize(("count", "match", "pulled"), STREAM_COUNTS)
    @pytest.mark.parametrize("native", SPLITTERS)
    def test_run_rejects_a_splitter_yielding_other_than_its_declared_branches(
        self, native: bool, count: int, match: str, pulled: int
    ) -> None:
        dispatcher, branches = _counted_branch_dispatcher(count, native=native)

        with pytest.raises(InvalidPipelineError, match=match):
            run_plan(_SPLIT_FLOW, dispatcher=dispatcher)

        assert len(branches.pulled) == pulled

    @pytest.mark.parametrize("native", SPLITTERS)
    def test_run_reads_one_split_branch_without_buffering_its_sibling(
        self, native: bool, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Its unread sibling would queue every item and overrun a one-item buffer.
        capped = replace(settings, branch_buffer=1)
        monkeypatch.setattr(split_module, "settings", capped)
        source = PullLog(_SOURCE_ROWS)
        dispatcher = _fan_out_dispatcher(source, native=native)
        plan = ExecutionPlan.from_workflow(_SPLIT_BRANCH_FLOW, dispatcher)

        with SyncExecution() as execution:
            stream = execution.run(plan)
            assert next(stream) == {"x": 0}
            assert source.pulled == tuple(_SOURCE_ROWS[:1])
            assert list(stream) == [{"x": 1}, {"x": 2}]

    @pytest.mark.parametrize("native", SPLITTERS)
    def test_run_closes_each_split_branch_once_its_reader_finishes(
        self, native: bool
    ) -> None:
        events: list[str] = []
        dispatcher = _recording_split_dispatcher(events, native=native)
        run_plan(_SPLIT_FLOW, dispatcher=dispatcher)

        assert events == ["b0-start", "b0-close", "b1-start", "b1-close"]

    @skipif_sync
    def test_build_envelope_stream_closes_an_abandoned_async_split_on_exit(
        self,
    ) -> None:
        events: list[str] = []
        dispatcher = _recording_split_dispatcher(events, native=True)
        plan = ExecutionPlan.from_workflow(_SPLIT_FLOW, dispatcher)

        with SyncExecution() as execution:
            next(execution.build_envelope_stream(plan))

        # Closing the output closes the branch it reads first, the unread one after.
        assert events == ["b0-start", "b0-close", "b1-close"]

    @skipif_sync
    def test_run_passes_an_async_only_stream_to_an_adjacent_async_only_node(
        self, monkeypatch
    ) -> None:
        to_async = SyncExecution._to_async
        bridged: list[object] = []

        def counting(self, run, stream):
            bridged.append(stream)
            return to_async(self, run, stream)

        monkeypatch.setattr(SyncExecution, "_to_async", counting)

        @tag_source
        async def asrc(_items=None, **_):
            for x in range(3):
                yield {"x": x}

        dispatcher = build_dispatcher(
            build_async_definition(asrc, name="asrc"), M_ARELAY_DEFINITION
        )
        flow = Workflow().with_nodes(ASRC_NODE, M_NODE)
        plan = ExecutionPlan.from_workflow(flow, dispatcher)

        with SyncExecution() as execution:
            assert list(execution.run(plan)) == [{"x": x} for x in range(3)]

        assert len(bridged) == 1

    @skipif_sync
    @pytest.mark.parametrize(("build", "expected"), ASYNC_ONLY_READERS)
    def test_run_pulls_an_async_only_nodes_sync_input_off_the_event_loop(
        self, build, expected
    ) -> None:
        pulled: set[int] = set()
        relayed: set[int] = set()
        flow, dispatcher = build(pulled, relayed)
        result = run_plan(flow, dispatcher=dispatcher)

        assert sorted(item["x"] for item in result) == expected
        assert pulled
        assert relayed
        assert not pulled & relayed

    def test_run_drops_split_branch_values_past_the_last_input_item(self) -> None:
        dispatcher = build_dispatcher(
            _rows_source(_SOURCE_ROWS), _PROBE, _DOUBLED_SPLIT, _UNION
        )

        assert run_plan(_SPLIT_BRANCH_FLOW, dispatcher=dispatcher) == _SOURCE_ROWS

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
            build_sync_definition(a_src, name="a_src"),
            build_sync_definition(b_src, name="b_src"),
        )
        a = ModuleNode(id="a", name="a_src")
        b = ModuleNode(id="b", name="b_src")

        assert run_plan(
            build_workflow([a, b], outputs=OUTPUTS_AB), dispatcher=dispatcher
        ) == [{"x": 1}]
        assert ran == ["a"]

    @skipif_sync
    def test_run_drives_async_only_module_via_portal(self) -> None:
        @tag_source
        async def src(_items=None, **_):
            yield {"x": 1}
            yield {"x": 2}

        dispatcher = build_dispatcher(build_async_definition(src))
        assert run_plan(module_workflow("src"), dispatcher=dispatcher) == [
            {"x": 1},
            {"x": 2},
        ]

    @skipif_sync
    def test_run_opens_an_async_only_stream_on_the_portal(self) -> None:
        @tag_source
        def src(_items=None, **_):
            lowlevel.current_token()
            return agen_source()

        dispatcher = build_dispatcher(build_async_definition(src))
        plan = build_module_plan(dispatcher)

        with SyncExecution() as execution:
            assert list(execution.run(plan)) == [{"x": 1}, {"x": 2}]

    @skipif_sync
    def test_run_opens_an_async_only_item_result_on_the_portal(self) -> None:
        def item(_item, **_) -> AsyncStream:
            lowlevel.current_token()
            return agen_source()

        pipe = mark_async_loopable(cast("AsyncPipeFunc", item))
        dispatcher = build_dispatcher(build_async_definition(pipe, name="m"))
        plan = build_module_plan(dispatcher, "m")

        with SyncExecution() as execution:
            assert list(execution.run(plan, seed={"x": 0})) == [{"x": 1}, {"x": 2}]

    @skipif_sync
    def test_run_opens_an_async_seed_on_the_portal(self) -> None:
        plan = build_doubler_plan("double")

        with SyncExecution() as execution:
            stream = execution.run(plan, seed=_LoopBoundHandle())
            assert list(stream) == [{"x": 2}, {"x": 4}]

    @skipif_sync
    def test_run_reads_a_slow_async_only_source_past_the_shutdown_timeout(self) -> None:
        @tag_source
        async def src(_items=None, **_):
            await async_sleep(0.2)
            yield {"x": 1}

        dispatcher = build_dispatcher(build_async_definition(src))
        settings = ExecutionSettings(shutdown_timeout=0.05)
        flow = module_workflow("src")

        assert run_plan(flow, dispatcher=dispatcher, settings=settings) == [{"x": 1}]

    @skipif_sync
    def test_run_chains_async_only_node_after_sync_node(self) -> None:
        @tag_source
        def src(_items=None, **_):
            yield {"x": 1}

        async def atag(items, **_):
            async for row in as_async(items):
                yield {**row, "seen": True}

        dispatcher = build_dispatcher(
            build_sync_definition(src), build_async_definition(atag, name="atag")
        )
        flow = Workflow().with_nodes(SRC_NODE, ModuleNode(id="b", name="atag"))

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

        dispatcher = build_dispatcher(build_sync_definition(probe, name="probe"))
        plan = build_module_plan(dispatcher, "probe")

        with SyncExecution() as execution:
            assert list(execution.run(plan)) == []

        assert seen == [{"forever": True}]

    def test_run_seeds_a_positional_fan_in_rather_than_its_sources(self) -> None:
        dispatcher = build_dispatcher(_A_SRC, _B_SRC, _UNION)
        edges = (
            StreamEdge(Endpoint("a", "out"), Endpoint("u", "in:1")),
            StreamEdge(Endpoint("b", "out"), Endpoint("u", "in:2")),
        )
        flow = build_workflow([_A_NODE, _B_NODE, UNION_NODE], edges=edges)
        plan = ExecutionPlan.from_workflow(flow, dispatcher=dispatcher)
        expected = [{"x": 1}, {"t": "a"}, {"t": "b"}]

        with SyncExecution() as execution:
            assert list(execution.run(plan, seed=X_ROW)) == expected

    def test_run_starts_a_stored_source_workflow_with_input_schemas(self) -> None:
        schemas = '{"q": {"type": "string", "default": "x"}}'
        raw = f'{{"input_schemas": {schemas}, "nodes": [{{"name": "forever"}}]}}'
        plan = _build_stored_plan(raw)

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
        raw = {
            "input_schemas": {"q": {"type": "string", "default": "x"}},
            "nodes": [{"name": "itembuilder", "conf": Q_CONF}],
        }
        plan = _build_stored_plan(raw)
        context = Context(inputs={"q": "y", "other": 1})

        with SyncExecution(context) as execution:
            assert list(execution.run(plan)) == [{"q": "y"}]

    @pytest.mark.parametrize("pipe", LIST_RETURNS)
    def test_run_rejects_a_pipe_that_returns_a_list(self, pipe) -> None:
        resolver = build_dispatcher(build_sync_definition(pipe))
        plan = build_module_plan(resolver)

        with (
            SyncExecution() as execution,
            pytest.raises(TypeError, match=_NOT_ITERATOR),
        ):
            list(execution.run(plan))

    def test_run_fails_when_an_eager_splitter_overruns_the_branch_buffer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The splitter drains its input first, so its envelope branch lags every item.
        capped = replace(settings, branch_buffer=1)
        monkeypatch.setattr(sync_execution_module, "settings", capped)
        dispatcher = build_dispatcher(
            _rows_source(_SOURCE_ROWS), _PROBE, _DOUBLED_SPLIT, _UNION
        )

        with pytest.raises(PipelineError, match=r"1 items.*RIKO_BRANCH_BUFFER"):
            run_plan(_SPLIT_BRANCH_FLOW, dispatcher=dispatcher)

    @pytest.mark.parametrize("native", SPLITTERS)
    def test_run_fails_a_split_branch_lagging_past_the_branch_buffer(
        self, native: bool, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        capped = replace(settings, branch_buffer=1)
        monkeypatch.setattr(sync_execution_module, "settings", capped)
        events: list[str] = []
        dispatcher = _recording_split_dispatcher(events, native=native)

        with pytest.raises(PipelineError, match="fell more than 1 items behind"):
            run_plan(_SPLIT_FLOW, dispatcher=dispatcher)

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
            PASS_DEFINITION, build_sync_definition(passthrough_pipe, name="merge")
        )
        flow = build_workflow([_A_PASS_NODE, PASS_NODE, MERGE_NODE], edges=_MERGE_EDGES)
        plan = ExecutionPlan.from_workflow(flow, dispatcher=dispatcher)

        with (
            SyncExecution() as execution,
            pytest.raises(InvalidPipelineError, match="exactly one open input"),
        ):
            execution.run(plan, seed=X_ROW)

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
        dispatcher = build_dispatcher(PASS_DEFINITION)
        nodes = [ModuleNode(id="n", name="pass", resources={"slot": "primary"})]
        flow = build_workflow(nodes, resources=("primary",))
        plan = ExecutionPlan.from_workflow(flow, dispatcher=dispatcher)
        events: list[str] = []
        context = Context().with_resource("primary", _lifecycle(events), lazy=True)

        with SyncExecution(context) as execution:
            assert list(execution.run(plan, seed=X_ROW)) == [{"x": 1}]

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

        dispatcher = build_dispatcher(build_async_definition(src))
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
            build_async_definition(src),
            build_sync_definition(double, name="double"),
            build_async_definition(atag, name="atag"),
        )
        b = ModuleNode(id="b", name="double")
        flow = Workflow().with_nodes(SRC_NODE, b, ModuleNode(id="c", name="atag"))

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

        dispatcher = build_dispatcher(build_async_definition(aprobe, name="aprobe"))
        node = ModuleNode(id="n", name="aprobe", options={"emit": True})
        flow = build_workflow([node])

        assert await arun_plan(flow, dispatcher=dispatcher) == []
        assert seen["emit"] is True
        assert seen["conf"] == {}

    @async_test
    async def test_arun_leaves_the_default_input_empty_with_only_indexed_ports_wired(
        self,
    ) -> None:
        seen: dict[str, object] = {}

        async def amerge(source, others=None, **_):
            seen["source"] = [row async for row in source]

            for other in others or ():
                async for row in other:
                    yield row

        dispatcher = build_dispatcher(
            _ASRC, build_async_definition(amerge, name="amerge")
        )
        m = ModuleNode(id="m", name="amerge")
        edge = StreamEdge(Endpoint("a", "out"), Endpoint("m", "in:1"))
        flow = build_workflow([ASRC_NODE, m], edges=(edge,))

        assert await arun_plan(flow, dispatcher=dispatcher) == [{"t": "a"}]
        assert seen["source"] == []

    @async_test
    async def test_arun_passes_a_sync_only_stream_to_an_adjacent_sync_only_node(
        self,
    ) -> None:
        pulled: list[int] = []
        relayed: list[int] = []

        @tag_source
        def src(_items=None, **_):
            for x in range(3):
                pulled.append(get_ident())
                yield {"x": x}

        def relay(source, **_):
            for item in source:
                relayed.append(get_ident())
                yield item

        dispatcher = build_dispatcher(
            build_sync_definition(src), build_sync_definition(relay, name="m")
        )
        flow = Workflow().with_nodes(SRC_NODE, M_NODE)

        assert await arun_plan(flow, dispatcher=dispatcher) == [
            {"x": x} for x in range(3)
        ]
        assert pulled == relayed

    @pytest.mark.parametrize(("split", "native"), ASYNC_FAN_OUTS)
    @async_test
    async def test_arun_fans_out_every_item_to_each_consumer(
        self, split: bool, native: bool
    ) -> None:
        source = PullLog(_SOURCE_ROWS)
        flow = _fan_out_workflow(split=split)
        dispatcher = _fan_out_dispatcher(source, native=native)

        assert await arun_plan(flow, dispatcher=dispatcher) == _SOURCE_ROWS * 2
        assert source.pulled == tuple(_SOURCE_ROWS)

    @async_test
    async def test_arun_feeds_a_sync_only_splitter_named_input_values(self) -> None:
        seen: list[object] = []

        @splitter(objectify=False)
        def split(stream: Stream, _: object, __: object, side=None, **___: object):
            seen.extend(side or ())
            items = list(stream)
            return iter([iter(items), iter(items)])

        dispatcher = build_dispatcher(
            _A_SRC, _SIDE, build_sync_definition(split, name="split")
        )
        nodes = [_A_NODE, _SIDE_NODE, SPLIT_NODE]
        edges = (
            StreamEdge(Endpoint("a", "out"), Endpoint("s", "in")),
            StreamEdge(Endpoint("b", "out"), Endpoint("s", "in:side")),
        )
        outputs = {"default": Endpoint("s", "out")}
        flow = build_workflow(nodes, edges=edges, outputs=outputs)

        assert await arun_plan(flow, dispatcher=dispatcher) == [{"t": "a"}]
        assert seen == [{"t": "side"}]

    @pytest.mark.parametrize(("count", "match", "pulled"), STREAM_COUNTS)
    @pytest.mark.parametrize("native", SPLITTERS)
    @async_test
    async def test_arun_rejects_a_splitter_yielding_other_than_its_declared_branches(
        self, native: bool, count: int, match: str, pulled: int
    ) -> None:
        dispatcher, branches = _counted_branch_dispatcher(count, native=native)

        with pytest.raises(InvalidPipelineError, match=match):
            await arun_plan(_SPLIT_FLOW, dispatcher=dispatcher)

        assert len(branches.pulled) == pulled

    @pytest.mark.parametrize("native", SPLITTERS)
    @async_test
    async def test_arun_reads_one_split_branch_without_buffering_its_sibling(
        self, native: bool, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Its unread sibling would queue every item and overrun a one-item buffer.
        monkeypatch.setattr(
            split_module, "settings", replace(settings, branch_buffer=1)
        )
        source = PullLog(_SOURCE_ROWS)
        dispatcher = _fan_out_dispatcher(source, native=native)
        plan = ExecutionPlan.from_workflow(_SPLIT_BRANCH_FLOW, dispatcher)

        async with AsyncExecution() as execution:
            stream = await execution.arun(plan)
            assert await anext(stream) == {"x": 0}
            assert source.pulled == tuple(_SOURCE_ROWS[:1])
            assert [item async for item in stream] == [{"x": 1}, {"x": 2}]

    @pytest.mark.parametrize("native", SPLITTERS)
    @async_test
    async def test_arun_closes_each_split_branch_once_its_reader_finishes(
        self, native: bool
    ) -> None:
        events: list[str] = []
        dispatcher = _recording_split_dispatcher(events, native=native)
        await arun_plan(_SPLIT_FLOW, dispatcher=dispatcher)

        assert events == ["b0-start", "b0-close", "b1-start", "b1-close"]

    @async_test
    async def test_arun_drops_split_branch_values_past_the_last_input_item(
        self,
    ) -> None:
        dispatcher = build_dispatcher(
            _rows_source(_SOURCE_ROWS), _PROBE, _DOUBLED_SPLIT, _UNION
        )
        flow = _SPLIT_BRANCH_FLOW

        assert await arun_plan(flow, dispatcher=dispatcher) == _SOURCE_ROWS

    @async_test
    async def test_arun_sync_worker_node_adapts_secondary_inputs(self) -> None:
        def merge(items, others=None, label=None, **_):
            yield from items

            for other in others or ():
                yield from other

            for row in label or ():
                yield {"labeled": row["t"]}

        dispatcher = build_dispatcher(
            _ASRC,
            build_async_definition(atagged_source("b"), name="bsrc"),
            build_async_definition(atagged_source("c"), name="csrc"),
            build_sync_definition(merge, name="merge"),
        )
        c = ModuleNode(id="c", name="csrc")
        edges = (
            *_MERGE_EDGES,
            StreamEdge(Endpoint("c", "out"), Endpoint("m", "in:label")),
        )
        flow = build_workflow([ASRC_NODE, BSRC_NODE, c, MERGE_NODE], edges=edges)

        assert await arun_plan(flow, dispatcher=dispatcher) == [
            {"t": "a"},
            {"t": "b"},
            {"labeled": "c"},
        ]

    @async_test
    async def test_arun_module_reads_execution_resources(self) -> None:
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

        dispatcher = build_dispatcher(build_async_definition(aprobe, name="aprobe"))
        plan = build_module_plan(dispatcher, "aprobe")

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

        dispatcher = build_dispatcher(build_sync_definition(src))
        plan = build_module_plan(dispatcher)
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
            _ASRC,
            build_async_definition(bsrc, name="bsrc"),
            build_sync_definition(merge, name="merge"),
        )
        flow = build_workflow([ASRC_NODE, BSRC_NODE, MERGE_NODE], edges=_MERGE_EDGES)
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

        dispatcher = build_dispatcher(build_sync_definition(src))
        loop_thread = get_ident()

        assert await arun_plan(module_workflow("src"), dispatcher=dispatcher) == [
            {"x": 1}
        ]
        assert threads
        assert loop_thread not in threads

    @pytest.mark.parametrize("pipe", ASYNC_LIST_RETURNS)
    @async_test
    async def test_arun_rejects_a_pipe_that_returns_a_list(self, pipe) -> None:
        resolver = build_dispatcher(build_async_definition(pipe))
        plan = build_module_plan(resolver)

        async with AsyncExecution() as execution:
            with pytest.raises(TypeError, match=_NOT_ASYNC_ITERATOR):
                await alist(await execution.arun(plan))

    @async_test
    async def test_arun_fails_when_an_eager_splitter_overruns_the_branch_buffer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The splitter drains its input first, so its envelope branch lags every item.
        capped = replace(settings, branch_buffer=1)
        monkeypatch.setattr(async_execution_module, "config", capped)
        dispatcher = build_dispatcher(
            _rows_source(_SOURCE_ROWS), _PROBE, _DOUBLED_SPLIT, _UNION
        )

        with pytest.raises(PipelineError, match=r"1 items.*RIKO_BRANCH_BUFFER"):
            await arun_plan(_SPLIT_BRANCH_FLOW, dispatcher=dispatcher)

    @pytest.mark.parametrize("native", SPLITTERS)
    @async_test
    async def test_arun_fails_a_split_branch_lagging_past_the_branch_buffer(
        self, native: bool, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        capped = replace(settings, branch_buffer=1)
        monkeypatch.setattr(async_execution_module, "config", capped)
        events: list[str] = []
        dispatcher = _recording_split_dispatcher(events, native=native)

        with pytest.raises(PipelineError, match="fell more than 1 items behind"):
            await arun_plan(_SPLIT_FLOW, dispatcher=dispatcher)
