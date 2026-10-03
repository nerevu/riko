# vim: sw=4:ts=4:expandtab
"""Tests for canonical workflow indexing and execution preparation."""

from threading import get_ident
from typing import TYPE_CHECKING, cast

import pytest

from riko.bado._backend import fail_after
from riko.bado._util import maybe_deferred
from riko.bado.itertools import as_async
from riko.base.exceptions import InvalidPipelineError, UnsupportedModuleError
from riko.definitions._workflow import (
    CacheNode,
    ModuleNode,
    Pipeline,
    StreamEdge,
    Workflow,
)
from riko.definitions.modules import ModuleDefinition
from riko.execution._adapt import (
    adapt_embed_for_async,
    adapt_embed_for_sync,
    require_async_stream,
    require_stream,
)
from riko.execution._execution import AsyncExecution, SyncExecution
from riko.execution._prepared import ExecMode, PreparedNode
from riko.execution._resources import Resource
from riko.execution.context import Context
from riko.modules._decorators import processor, splitter
from riko.modules.loop import async_pipe as async_loop
from riko.modules.loop import pipe as loop_pipe
from riko.modules.split import async_pipe as async_split
from riko.modules.split import pipe as split_pipe
from riko.runtime._execution_plan import build_execution_plan
from riko.runtime._graph_index import index_workflow
from riko.runtime._module_registry import (
    ModuleRegistry,
    register_module,
    reset_module_registry,
)
from riko.runtime._pipelines import mark_subpipe, pipeline_resolver
from riko.runtime._resolver import ResolverDispatcher
from riko.types._enums import BasicCastType
from riko.types._workflow import Endpoint
from tests import async_test, skipif_issync

if TYPE_CHECKING:
    from riko.types._streams import AsyncItemGenerator, Cascade
    from riko.types._wrappers import AsyncModuleWrapper, SyncModuleWrapper
    from riko.types.modules import ModuleOptions

_sync_pipe = cast("SyncModuleWrapper", lambda source, **_: iter(source or {}))
_async_pipe = cast("AsyncModuleWrapper", lambda source, **_: as_async(source or {}))


def _workflow(nodes, outputs, edges=(), resources=()):
    keyed = {node.id: node for node in nodes}
    return Workflow(
        nodes=keyed, outputs=outputs, inputs={}, edges=edges, resources=resources
    )


def _dispatcher(*definitions):
    registry = ModuleRegistry()

    for definition in definitions:
        registry.register(definition)

    return ResolverDispatcher(registry, pipeline_resolver)


def _module_workflow(name="m"):
    node = ModuleNode(id="n", name=name)
    return _workflow([node], {"default": Endpoint("n", "out")})


def test_index_workflow_orders_and_indexes() -> None:
    a = ModuleNode(id="a", name="m")
    b = ModuleNode(id="b", name="m")
    c = ModuleNode(id="c", name="m")
    edge = StreamEdge(Endpoint("a", "out"), Endpoint("b", "in"))
    outputs = {"default": Endpoint("b", "out"), "extra": Endpoint("c", "out")}
    workflow = _workflow([a, b, c], outputs, edges=(edge,))
    index = index_workflow(workflow)

    assert set(index.order) == {"a", "b", "c"}
    assert index.order.index("a") < index.order.index("b")
    assert set(index.roots) == {"a", "c"}
    assert set(index.leaves) == {"b", "c"}
    assert index.dependencies["b"] == frozenset({"a"})
    assert index.incoming["b"][0].source == "a"
    assert index.outgoing["a"][0].target == "b"
    assert set(index.outputs) == {"default", "extra"}


def test_prepare_selects_native_sync() -> None:
    definition = ModuleDefinition(
        name="m", sync_pipe=_sync_pipe, async_pipe=_async_pipe
    )
    plan = build_execution_plan(_module_workflow(), dispatcher=_dispatcher(definition))
    node = plan.nodes["n"]
    result = node.select(is_async=False)
    assert result.pipe is _sync_pipe
    assert result.mode is ExecMode.NATIVE


def test_prepare_selects_native_async() -> None:
    definition = ModuleDefinition(
        name="m", sync_pipe=_sync_pipe, async_pipe=_async_pipe
    )
    plan = build_execution_plan(_module_workflow(), dispatcher=_dispatcher(definition))
    node = plan.nodes["n"]
    result = node.select(is_async=True)
    assert result.pipe is _async_pipe
    assert result.mode is ExecMode.NATIVE


def test_prepare_adapts_sync_only_under_async() -> None:
    definition = ModuleDefinition(name="m", sync_pipe=_sync_pipe)
    plan = build_execution_plan(_module_workflow(), dispatcher=_dispatcher(definition))
    node = plan.nodes["n"]
    assert node.select(is_async=True).mode is ExecMode.ADAPTER


def test_prepare_adapts_async_only_under_sync() -> None:
    definition = ModuleDefinition(name="m", async_pipe=_async_pipe)
    plan = build_execution_plan(_module_workflow(), dispatcher=_dispatcher(definition))
    node = plan.nodes["n"]
    assert node.select(is_async=False).mode is ExecMode.ADAPTER


def test_prepare_does_not_invoke_the_pipe() -> None:
    calls: list[int] = []

    def pipe(source, **_):
        calls.append(1)
        return source

    sync_pipe = cast("SyncModuleWrapper", pipe)
    definition = ModuleDefinition(name="m", sync_pipe=sync_pipe)
    build_execution_plan(_module_workflow(), dispatcher=_dispatcher(definition))
    assert calls == []


def test_execution_plan_snapshots_resolution() -> None:
    # The plan resolves each node's callable once at build time, so replacing a
    # module afterward does not change what a built plan runs.
    registry = ModuleRegistry()
    registry.register(ModuleDefinition(name="src", sync_pipe=_tagged_source("a")))
    dispatcher = ResolverDispatcher(registry, pipeline_resolver)
    plan = build_execution_plan(_module_workflow("src"), dispatcher=dispatcher)
    registry.register(
        ModuleDefinition(name="src", sync_pipe=_tagged_source("b")), replace=True
    )

    with SyncExecution() as execution:
        assert list(execution.run(plan)) == [{"t": "a"}]


def test_prepare_carries_conf_index_and_resources() -> None:
    definition = ModuleDefinition(name="m", sync_pipe=_sync_pipe)
    node = ModuleNode(id="n", name="m", conf={"url": "x"}, resources={"db": "db"})
    workflow = _workflow([node], {"default": Endpoint("n", "out")}, resources=("db",))
    plan = build_execution_plan(workflow, dispatcher=_dispatcher(definition))
    prepared = plan.nodes["n"]

    assert prepared.conf == {"url": "x"}
    assert set(prepared.resources.values()) == {"db"}
    assert plan.index.outputs["default"].node == "n"


def test_prepare_rejects_unsupported_node_family() -> None:
    workflow = _workflow(
        [CacheNode(id="c", name="x")], {"default": Endpoint("c", "out")}
    )

    with pytest.raises(InvalidPipelineError, match="cache"):
        build_execution_plan(workflow, dispatcher=_dispatcher())


def test_prepare_rejects_unresolved_module() -> None:
    workflow = _module_workflow(name="does_not_exist_module")

    with pytest.raises(UnsupportedModuleError):
        build_execution_plan(workflow, dispatcher=_dispatcher())


def test_prepare_validates_before_preparing() -> None:
    workflow = _workflow([ModuleNode(id="n", name="m")], {})

    with pytest.raises(InvalidPipelineError):
        build_execution_plan(workflow, dispatcher=_dispatcher())


def _run(workflow, dispatcher, output="default"):
    plan = build_execution_plan(workflow, dispatcher=dispatcher)

    with SyncExecution() as execution:
        return list(execution.run(plan, output))


def test_run_executes_single_source_node() -> None:
    def src(_items=None, **_):
        yield {"x": 1}
        yield {"x": 2}

    sync_pipe = cast("SyncModuleWrapper", src)
    dispatcher = _dispatcher(ModuleDefinition(name="src", sync_pipe=sync_pipe))
    assert _run(_module_workflow("src"), dispatcher) == [{"x": 1}, {"x": 2}]


def test_run_chains_nodes_through_stream_edge() -> None:
    def src(_items=None, **_):
        yield {"x": 1}
        yield {"x": 2}

    def double(items, **_):
        return ({"x": row["x"] * 2} for row in items)

    dispatcher = _dispatcher(
        ModuleDefinition(name="src", sync_pipe=cast("SyncModuleWrapper", src)),
        ModuleDefinition(name="double", sync_pipe=cast("SyncModuleWrapper", double)),
    )
    a = ModuleNode(id="a", name="src")
    b = ModuleNode(id="b", name="double")
    edge = StreamEdge(Endpoint("a", "out"), Endpoint("b", "in"))
    workflow = _workflow([a, b], {"default": Endpoint("b", "out")}, edges=(edge,))

    assert _run(workflow, dispatcher) == [{"x": 2}, {"x": 4}]


def test_module_node_rejects_an_unknown_option() -> None:
    options = cast("ModuleOptions", {"bogus": 1})

    with pytest.raises(InvalidPipelineError, match="unknown module option"):
        ModuleNode(id="n", name="m", options=options)


def test_run_forwards_node_options_as_call_kwargs() -> None:
    seen: dict[str, object] = {}

    def probe(source, **kwargs):
        seen["emit"] = kwargs.get("emit")
        seen["conf"] = dict(kwargs["conf"])
        return iter(())

    sync_pipe = cast("SyncModuleWrapper", probe)
    dispatcher = _dispatcher(ModuleDefinition(name="probe", sync_pipe=sync_pipe))
    node = ModuleNode(id="n", name="probe", options={"emit": True})
    workflow = _workflow([node], {"default": Endpoint("n", "out")})

    assert _run(workflow, dispatcher) == []
    assert seen["emit"] is True
    assert seen["conf"] == {}


def _tagged_source(tag):
    def src(_items=None, **_):
        yield {"t": tag}

    return cast("SyncModuleWrapper", src)


def test_run_wires_others_ordered_by_port_index() -> None:
    def merge(items, others=None, **_):
        yield from items

        for other in others or ():
            yield from other

    dispatcher = _dispatcher(
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
    workflow = _workflow([a, b, c, m], {"default": Endpoint("m", "out")}, edges=edges)

    assert _run(workflow, dispatcher) == [{"t": "a"}, {"t": "b"}, {"t": "c"}]


def test_run_wires_named_input_port_as_kwarg() -> None:
    def joiner(items, side=None, **_):
        yield from items
        yield from side or ()

    dispatcher = _dispatcher(
        ModuleDefinition(name="a", sync_pipe=_tagged_source("a")),
        ModuleDefinition(name="side", sync_pipe=_tagged_source("side")),
        ModuleDefinition(name="joiner", sync_pipe=cast("SyncModuleWrapper", joiner)),
    )
    a = ModuleNode(id="a", name="a")
    s = ModuleNode(id="s", name="side")
    j = ModuleNode(id="j", name="joiner")
    edges = (
        StreamEdge(Endpoint("a", "out"), Endpoint("j", "in")),
        StreamEdge(Endpoint("s", "out"), Endpoint("j", "in:side")),
    )
    workflow = _workflow([a, s, j], {"default": Endpoint("j", "out")}, edges=edges)

    assert _run(workflow, dispatcher) == [{"t": "a"}, {"t": "side"}]


def test_run_leaves_the_default_input_empty_when_only_indexed_ports_are_wired() -> None:
    # An operator whose default input is unconnected but whose secondary inputs are
    # wired must not receive the seed item as data.
    seen: dict[str, object] = {}

    def merge(source, others=None, **_):
        seen["source"] = list(source)

        for other in others or ():
            yield from other

    dispatcher = _dispatcher(
        ModuleDefinition(name="src", sync_pipe=_tagged_source("a")),
        ModuleDefinition(name="merge", sync_pipe=cast("SyncModuleWrapper", merge)),
    )
    a = ModuleNode(id="a", name="src")
    m = ModuleNode(id="m", name="merge")
    edge = StreamEdge(Endpoint("a", "out"), Endpoint("m", "in:1"))
    workflow = _workflow([a, m], {"default": Endpoint("m", "out")}, edges=(edge,))

    assert _run(workflow, dispatcher) == [{"t": "a"}]
    assert seen["source"] == []


def test_run_still_seeds_a_node_wired_only_through_a_named_value_port() -> None:
    seen: dict[str, object] = {}

    def probe(source, count=None, **_):
        seen["source"] = list(source)
        seen["count"] = list(count or ())
        return iter(())

    dispatcher = _dispatcher(
        ModuleDefinition(name="src", sync_pipe=_tagged_source("a")),
        ModuleDefinition(name="probe", sync_pipe=cast("SyncModuleWrapper", probe)),
    )
    a = ModuleNode(id="a", name="src")
    b = ModuleNode(id="b", name="probe")
    edge = StreamEdge(Endpoint("a", "out"), Endpoint("b", "in:count"))
    workflow = _workflow([a, b], {"default": Endpoint("b", "out")}, edges=(edge,))

    assert _run(workflow, dispatcher) == []
    assert seen["source"] == [{"forever": True}]
    assert seen["count"] == [{"t": "a"}]


def test_run_rejects_nondefault_source_output_port() -> None:
    # Execution fails closed on non-default output ports: only the bare 'out' port
    # is executable. A distinct 'out:1' source port is rejected rather than
    # silently aliased to the node's 'out' stream. This guard is removed once
    # port-keyed fan-out/split delivery becomes executable.
    sync_pipe = cast("SyncModuleWrapper", lambda items, **_: iter(list(items)))
    dispatcher = _dispatcher(
        ModuleDefinition(name="src", sync_pipe=_tagged_source("a")),
        ModuleDefinition(name="sink", sync_pipe=sync_pipe),
    )
    a = ModuleNode(id="a", name="src")
    b = ModuleNode(id="b", name="sink")
    edge = StreamEdge(Endpoint("a", "out:1"), Endpoint("b", "in"))
    workflow = _workflow([a, b], {"default": Endpoint("b", "out")}, edges=(edge,))

    with pytest.raises(InvalidPipelineError, match="non-default output port"):
        _run(workflow, dispatcher)


def test_run_rejects_nondefault_selected_output_port() -> None:
    # The fail-closed guard also covers a selected workflow output whose port is
    # not the default 'out'. This is removed once positional/named output ports
    # become addressable.
    dispatcher = _dispatcher(
        ModuleDefinition(name="src", sync_pipe=_tagged_source("a"))
    )
    node = ModuleNode(id="n", name="src")
    workflow = _workflow([node], {"default": Endpoint("n", "out:1")})

    with pytest.raises(InvalidPipelineError, match="non-default output port"):
        _run(workflow, dispatcher)


def test_build_plan_rejects_fan_out_from_one_source_port() -> None:
    # Two stream edges leaving the same source port would hand both consumers
    # one shared one-shot iterator, so whichever drained first would steal the
    # other's items. The plan refuses the shape before any node runs. This
    # guard is removed once port-keyed fan-out delivery becomes executable.
    dispatcher = _dispatcher(
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
    workflow = _workflow([a, b, c], {"default": Endpoint("b", "out")}, edges=edges)

    with pytest.raises(InvalidPipelineError, match=r"fan-out.*\('a', 'out'\)"):
        build_execution_plan(workflow, dispatcher=dispatcher)


@pytest.mark.parametrize(
    "ports",
    [
        pytest.param(("in", "in:2"), id="gap-after-default"),
        pytest.param(("in:1", "in:3"), id="gap-between-positions"),
        pytest.param(("in:0",), id="zero-index"),
    ],
)
def test_build_plan_rejects_sparse_positional_inputs(ports) -> None:
    # Positional inputs reach a node as one contiguous list, so a gap or a zero
    # index would silently renumber the operands. The plan refuses the shape
    # until module port contracts say what each position means.
    dispatcher = _dispatcher(
        ModuleDefinition(name="src", sync_pipe=_tagged_source("a")),
        ModuleDefinition(name="merge", sync_pipe=_sync_pipe),
    )
    sources = [ModuleNode(id=f"s{n}", name="src") for n in range(len(ports))]
    m = ModuleNode(id="m", name="merge")
    edges = tuple(
        StreamEdge(Endpoint(source.id, "out"), Endpoint("m", port))
        for source, port in zip(sources, ports, strict=True)
    )
    workflow = _workflow([*sources, m], {"default": Endpoint("m", "out")}, edges=edges)

    with pytest.raises(InvalidPipelineError, match="without gaps"):
        build_execution_plan(workflow, dispatcher=dispatcher)


def test_build_plan_rejects_splitter_node_before_any_node_runs() -> None:
    # A multi-output (splitter) node is refused when the plan is built, so its
    # upstream is never consumed first. This is removed once port-keyed
    # fan-out/split delivery becomes executable.
    consumed: list[int] = []

    def src(_items=None, **_):
        consumed.append(1)
        yield {"t": "a"}

    dispatcher = _dispatcher(
        ModuleDefinition(name="src", sync_pipe=cast("SyncModuleWrapper", src)),
        ModuleDefinition(name="split", sync_pipe=split_pipe, async_pipe=async_split),
    )
    a = ModuleNode(id="a", name="src")
    s = ModuleNode(id="s", name="split")
    edge = StreamEdge(Endpoint("a", "out"), Endpoint("s", "in"))
    workflow = _workflow([a, s], {"default": Endpoint("s", "out")}, edges=(edge,))

    with pytest.raises(InvalidPipelineError, match="splitter"):
        build_execution_plan(workflow, dispatcher=dispatcher)

    assert consumed == []


def test_build_plan_rejects_splitter_by_declared_type_not_output_shape() -> None:
    # The refusal keys on the module type the pipe was decorated with, not on the
    # shape of what it yields, so a splitter whose branches are lists rather than
    # iterators is refused too instead of delivering whole lists as items.
    @splitter(objectify=False)
    def listy(stream, _objconf, _tuples, **_):
        items = list(stream)
        return cast("Cascade", iter([list(items), list(items)]))

    dispatcher = _dispatcher(ModuleDefinition(name="listy", sync_pipe=listy))

    with pytest.raises(InvalidPipelineError, match="splitter"):
        build_execution_plan(_module_workflow("listy"), dispatcher=dispatcher)


def test_prepared_node_refuses_a_splitter_pipe_on_construction() -> None:
    # The invariant lives on the node itself, so every construction path (plan
    # build, embeds, direct construction) is covered, not only the plan builder.
    node = ModuleNode(id="s", name="split")

    with pytest.raises(InvalidPipelineError, match=r"'sync_pipe'.*splitter"):
        PreparedNode(node, sync_pipe=split_pipe)

    with pytest.raises(InvalidPipelineError, match=r"'async_pipe'.*splitter"):
        PreparedNode(node, async_pipe=async_split)


def test_require_stream_refuses_a_splitter_pipe_without_consuming() -> None:
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


def test_run_injects_bound_resource() -> None:
    sentinel = object()

    def reader(items, **kw):
        yield {"got": kw["resources"]["slot"]}

    sync_pipe = cast("SyncModuleWrapper", reader)
    dispatcher = _dispatcher(ModuleDefinition(name="reader", sync_pipe=sync_pipe))
    node = ModuleNode(id="n", name="reader", resources={"slot": "primary"})
    workflow = _workflow(
        [node], {"default": Endpoint("n", "out")}, resources=("primary",)
    )
    plan = build_execution_plan(workflow, dispatcher=dispatcher)
    context = Context().with_resource("primary", Resource.from_external(sentinel))

    with SyncExecution(context) as execution:
        assert list(execution.run(plan)) == [{"got": sentinel}]


def test_run_resource_lifecycle_owned_by_execution() -> None:
    events: list[str] = []

    def db():
        events.append("open")

        try:
            yield "conn"
        finally:
            events.append("close")

    def reader(items, **kw):
        yield {"db": kw["resources"]["slot"]}

    sync_pipe = cast("SyncModuleWrapper", reader)
    dispatcher = _dispatcher(ModuleDefinition(name="reader", sync_pipe=sync_pipe))
    node = ModuleNode(id="n", name="reader", resources={"slot": "primary"})
    workflow = _workflow(
        [node], {"default": Endpoint("n", "out")}, resources=("primary",)
    )
    plan = build_execution_plan(workflow, dispatcher=dispatcher)
    context = Context().with_resource("primary", db)

    with SyncExecution(context) as execution:
        assert list(execution.run(plan)) == [{"db": "conn"}]
        assert events == ["open"]

    assert events == ["open", "close"]


def test_run_rejects_unprovided_resource() -> None:
    def reader(items, **_):
        yield {}

    sync_pipe = cast("SyncModuleWrapper", reader)
    dispatcher = _dispatcher(ModuleDefinition(name="reader", sync_pipe=sync_pipe))
    node = ModuleNode(id="n", name="reader", resources={"slot": "primary"})
    workflow = _workflow(
        [node], {"default": Endpoint("n", "out")}, resources=("primary",)
    )
    plan = build_execution_plan(workflow, dispatcher=dispatcher)

    with (
        SyncExecution() as execution,
        pytest.raises(InvalidPipelineError, match="not provided"),
    ):
        list(execution.run(plan))


def test_run_executes_only_selected_output_subgraph() -> None:
    ran: list[str] = []

    def a_src(_items=None, **_):
        ran.append("a")
        yield {"x": 1}

    def b_src(_items=None, **_):
        ran.append("b")
        yield {"y": 1}

    dispatcher = _dispatcher(
        ModuleDefinition(name="a_src", sync_pipe=cast("SyncModuleWrapper", a_src)),
        ModuleDefinition(name="b_src", sync_pipe=cast("SyncModuleWrapper", b_src)),
    )
    a = ModuleNode(id="a", name="a_src")
    b = ModuleNode(id="b", name="b_src")
    outputs = {"default": Endpoint("a", "out"), "other": Endpoint("b", "out")}

    assert _run(_workflow([a, b], outputs), dispatcher) == [{"x": 1}]
    assert ran == ["a"]


def test_run_rejects_missing_output() -> None:
    dispatcher = _dispatcher(ModuleDefinition(name="src", sync_pipe=_sync_pipe))
    plan = build_execution_plan(_module_workflow("src"), dispatcher=dispatcher)

    with (
        SyncExecution() as execution,
        pytest.raises(InvalidPipelineError, match="output"),
    ):
        execution.run(plan, "nope")


@skipif_issync
def test_run_drives_async_only_module_via_portal() -> None:
    async def src(_items=None, **_):
        yield {"x": 1}
        yield {"x": 2}

    async_pipe = cast("AsyncModuleWrapper", src)
    dispatcher = _dispatcher(ModuleDefinition(name="src", async_pipe=async_pipe))
    assert _run(_module_workflow("src"), dispatcher) == [{"x": 1}, {"x": 2}]


@skipif_issync
def test_run_chains_async_only_node_after_sync_node() -> None:
    def src(_items=None, **_):
        yield {"x": 1}

    async def atag(items, **_):
        for row in items:
            yield {**row, "seen": True}

    dispatcher = _dispatcher(
        ModuleDefinition(name="src", sync_pipe=cast("SyncModuleWrapper", src)),
        ModuleDefinition(name="atag", async_pipe=cast("AsyncModuleWrapper", atag)),
    )
    a = ModuleNode(id="a", name="src")
    b = ModuleNode(id="b", name="atag")
    edge = StreamEdge(Endpoint("a", "out"), Endpoint("b", "in"))
    workflow = _workflow([a, b], {"default": Endpoint("b", "out")}, edges=(edge,))

    assert _run(workflow, dispatcher) == [{"x": 1, "seen": True}]


def test_run_seeds_root_with_supplied_source() -> None:
    def double(source, **_):
        return ({"x": row["x"] * 2} for row in source)

    sync_pipe = cast("SyncModuleWrapper", double)
    dispatcher = _dispatcher(ModuleDefinition(name="double", sync_pipe=sync_pipe))
    plan = build_execution_plan(_module_workflow("double"), dispatcher=dispatcher)

    with SyncExecution() as execution:
        stream = execution.run(plan, source=[{"x": 1}, {"x": 2}])
        assert list(stream) == [{"x": 2}, {"x": 4}]


def test_run_without_seed_keeps_forever_source() -> None:
    seen: list[object] = []

    def probe(source, **_):
        seen.extend(source)
        return iter(())

    sync_pipe = cast("SyncModuleWrapper", probe)
    dispatcher = _dispatcher(ModuleDefinition(name="probe", sync_pipe=sync_pipe))
    plan = build_execution_plan(_module_workflow("probe"), dispatcher=dispatcher)

    with SyncExecution() as execution:
        assert list(execution.run(plan)) == []

    assert seen == [{"forever": True}]


def test_run_rejects_seed_with_multiple_open_inputs() -> None:
    dispatcher = _dispatcher(
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
    workflow = _workflow([a, b, m], {"default": Endpoint("m", "out")}, edges=edges)
    plan = build_execution_plan(workflow, dispatcher=dispatcher)

    with (
        SyncExecution() as execution,
        pytest.raises(InvalidPipelineError, match="exactly one open input"),
    ):
        execution.run(plan, source=[{"x": 1}])


@async_test
async def test_arun_seeds_root_with_supplied_source() -> None:
    async def adouble(source, **_):
        async for row in source:
            yield {"x": row["x"] * 2}

    async_pipe = cast("AsyncModuleWrapper", adouble)
    dispatcher = _dispatcher(ModuleDefinition(name="adouble", async_pipe=async_pipe))
    plan = build_execution_plan(_module_workflow("adouble"), dispatcher=dispatcher)

    async with AsyncExecution() as execution:
        stream = await execution.run(plan, source=[{"x": 1}, {"x": 2}])
        assert [item async for item in stream] == [{"x": 2}, {"x": 4}]


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
    return _dispatcher(definition, adefinition)


async def _agen_source():
    yield {"x": 1}
    yield {"x": 2}


async def _awaitable_source():
    return [{"x": 1}, {"x": 2}]


def test_run_seeds_one_item_as_a_single_item_stream() -> None:
    plan = build_execution_plan(_module_workflow("double"), _doubler_dispatcher())

    with SyncExecution() as execution:
        assert list(execution.run(plan, source={"x": 5})) == [{"x": 10}]


@skipif_issync
def test_run_seeds_an_async_stream_through_the_portal() -> None:
    plan = build_execution_plan(_module_workflow("double"), _doubler_dispatcher())

    with SyncExecution() as execution:
        stream = execution.run(plan, source=_agen_source())
        assert list(stream) == [{"x": 2}, {"x": 4}]


@skipif_issync
def test_run_awaits_an_awaitable_seed_once() -> None:
    plan = build_execution_plan(_module_workflow("double"), _doubler_dispatcher())

    with SyncExecution() as execution:
        stream = execution.run(plan, source=_awaitable_source())
        assert list(stream) == [{"x": 2}, {"x": 4}]


@async_test
async def test_arun_seeds_one_item_as_a_single_item_stream() -> None:
    plan = build_execution_plan(_module_workflow("adouble"), _doubler_dispatcher())

    async with AsyncExecution() as execution:
        stream = await execution.run(plan, source={"x": 5})
        assert [item async for item in stream] == [{"x": 10}]


@async_test
async def test_arun_seeds_an_async_stream_without_wrapping_it() -> None:
    # An async stream seed is the stream itself, never one item holding the
    # stream object.
    plan = build_execution_plan(_module_workflow("adouble"), _doubler_dispatcher())

    async with AsyncExecution() as execution:
        stream = await execution.run(plan, source=_agen_source())
        assert [item async for item in stream] == [{"x": 2}, {"x": 4}]


@async_test
async def test_arun_awaits_an_awaitable_seed_once() -> None:
    plan = build_execution_plan(_module_workflow("adouble"), _doubler_dispatcher())

    async with AsyncExecution() as execution:
        stream = await execution.run(plan, source=_awaitable_source())
        assert [item async for item in stream] == [{"x": 2}, {"x": 4}]


@async_test
async def test_arun_without_seed_keeps_forever_source() -> None:
    seen: list[object] = []

    async def aprobe(source, **_):
        seen.extend([row async for row in source])

        for item in ():
            yield item

    async_pipe = cast("AsyncModuleWrapper", aprobe)
    dispatcher = _dispatcher(ModuleDefinition(name="aprobe", async_pipe=async_pipe))
    plan = build_execution_plan(_module_workflow("aprobe"), dispatcher=dispatcher)

    async with AsyncExecution() as execution:
        stream = await execution.run(plan)
        assert [item async for item in stream] == []

    assert seen == [{"forever": True}]


def _prepare_loop(embed_conf=None):
    loop = ModuleNode(
        id="loop",
        name="fakeloop",
        embed={"name": "up", "conf": embed_conf or {}},
        options={"emit": True, "count": "first"},
    )
    return _workflow([loop], {"default": Endpoint("loop", "out")})


def test_prepare_resolves_nested_embed() -> None:
    up = cast("SyncModuleWrapper", lambda item, **_: item)
    dispatcher = _dispatcher(
        ModuleDefinition(name="fakeloop", sync_pipe=_sync_pipe),
        ModuleDefinition(name="up", sync_pipe=up),
    )
    plan = build_execution_plan(_prepare_loop({"case": "upper"}), dispatcher=dispatcher)
    node = plan.nodes["loop"]

    assert node.embed is not None
    assert node.embed.name == "up"
    assert node.embed.select(is_async=False).pipe is up
    assert node.embed.conf == {"case": "upper"}
    assert dict(node.options) == {"emit": True, "count": "first"}
    assert dict(node.embed.options) == {}


def test_prepare_adapts_async_only_embed_under_sync() -> None:
    dispatcher = _dispatcher(
        ModuleDefinition(name="fakeloop", sync_pipe=_sync_pipe),
        ModuleDefinition(name="up", async_pipe=_async_pipe),
    )
    plan = build_execution_plan(_prepare_loop(), dispatcher=dispatcher)
    embed = plan.nodes["loop"].embed
    assert embed is not None
    assert embed.select(is_async=False).mode is ExecMode.ADAPTER


def test_prepare_adapts_sync_only_embed_under_async() -> None:
    dispatcher = _dispatcher(
        ModuleDefinition(name="fakeloop", async_pipe=_async_pipe),
        ModuleDefinition(name="up", sync_pipe=_sync_pipe),
    )
    plan = build_execution_plan(_prepare_loop(), dispatcher=dispatcher)
    embed = plan.nodes["loop"].embed

    assert embed is not None
    assert embed.select(is_async=True).mode is ExecMode.ADAPTER


@skipif_issync
def test_run_adapts_async_only_embed_under_sync() -> None:
    async def up(item, **_):
        yield {"up": item["t"].upper()}

    def fakeloop(items, embed=_sync_pipe, **_):
        for row in items:
            yield from embed(row)

    dispatcher = _dispatcher(
        ModuleDefinition(name="src", sync_pipe=_tagged_source("x")),
        ModuleDefinition(
            name="fakeloop", sync_pipe=cast("SyncModuleWrapper", fakeloop)
        ),
        ModuleDefinition(name="up", async_pipe=cast("AsyncModuleWrapper", up)),
    )
    src = ModuleNode(id="s", name="src")
    loop = ModuleNode(
        id="loop",
        name="fakeloop",
        embed={"name": "up", "conf": {}},
        options={"emit": True, "count": "first"},
    )
    edge = StreamEdge(Endpoint("s", "out"), Endpoint("loop", "in"))
    workflow = _workflow(
        [src, loop], {"default": Endpoint("loop", "out")}, edges=(edge,)
    )

    assert _run(workflow, dispatcher) == [{"up": "X"}]


def test_run_forwards_embed_and_options_to_loop() -> None:
    seen: dict[str, object] = {}

    def up(item, **_):
        yield {"up": item["t"].upper()}

    def fakeloop(items, embed=_sync_pipe, **kwargs):
        seen["embed"] = embed
        seen["options"] = {k: kwargs[k] for k in ("emit", "count") if k in kwargs}

        for row in items:
            yield from embed(row)

    sync_pipe = cast("SyncModuleWrapper", fakeloop)
    dispatcher = _dispatcher(
        ModuleDefinition(name="src", sync_pipe=_tagged_source("x")),
        ModuleDefinition(name="fakeloop", sync_pipe=sync_pipe),
        ModuleDefinition(name="up", sync_pipe=cast("SyncModuleWrapper", up)),
    )
    src = ModuleNode(id="s", name="src")
    loop = ModuleNode(
        id="loop",
        name="fakeloop",
        embed={"name": "up", "conf": {}},
        options={"emit": True, "count": "first"},
    )
    edge = StreamEdge(Endpoint("s", "out"), Endpoint("loop", "in"))
    workflow = _workflow(
        [src, loop], {"default": Endpoint("loop", "out")}, edges=(edge,)
    )

    assert _run(workflow, dispatcher) == [{"up": "X"}]
    assert seen["embed"] is up
    assert seen["options"] == {"emit": True, "count": "first"}


def _loop(loop_name="fakeloop", embed_name="up"):
    src = ModuleNode(id="s", name="src")
    loop = ModuleNode(
        id="loop",
        name=loop_name,
        embed={"name": embed_name, "conf": {}},
        options={"emit": True, "count": "first"},
    )
    edge = StreamEdge(Endpoint("s", "out"), Endpoint("loop", "in"))
    return _workflow([src, loop], {"default": Endpoint("loop", "out")}, edges=(edge,))


def _build_async_embed():
    """Decorate a fresh async processor parser so it carries real pipe metadata."""

    async def shout(item, extraction, objconf, **kwargs):
        return {"up": str(item["t"]).upper()}

    return cast(
        "AsyncModuleWrapper", processor(isasync=True, ptype=BasicCastType.NONE)(shout)
    )


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


@skipif_issync
def test_run_loops_async_only_embed_through_the_real_loop() -> None:
    embed = _build_async_embed()
    dispatcher = _dispatcher(
        ModuleDefinition(name="src", sync_pipe=_tagged_source("x")),
        ModuleDefinition(name="loop", sync_pipe=loop_pipe, async_pipe=async_loop),
        ModuleDefinition(name=embed.name, async_pipe=embed),
    )
    workflow = _loop(loop_name="loop", embed_name=embed.name)

    assert _run(workflow, dispatcher) == [{"up": "X"}]


def test_adapt_embed_for_sync_copies_metadata() -> None:
    stub = _EmbedStub()
    adapted = adapt_embed_for_sync(cast("AsyncModuleWrapper", stub), _unused_drain)

    assert adapted.name == "up"
    assert adapted.type == "processor"
    assert adapted.subtype == "transformer"
    assert adapted.subtypes == frozenset({"transformer"})
    assert adapted.pollable is False
    assert adapted.loopable is True
    assert adapted.isasync is False
    assert not hasattr(adapted, "__wrapped__")


def test_adapt_embed_for_async_copies_metadata() -> None:
    stub = _EmbedStub()
    stub.isasync = False
    adapted = adapt_embed_for_async(cast("SyncModuleWrapper", stub), _unused_worker)

    assert adapted.name == "up"
    assert adapted.type == "processor"
    assert adapted.subtype == "transformer"
    assert adapted.subtypes == frozenset({"transformer"})
    assert adapted.pollable is False
    assert adapted.loopable is True
    assert adapted.isasync is True
    assert not hasattr(adapted, "__wrapped__")


def test_pipeline_iter_runs_end_to_end() -> None:
    def src(_items=None, **_):
        yield {"x": 1}

    reset_module_registry()
    sync_pipe = cast("SyncModuleWrapper", src)
    register_module(ModuleDefinition(name="itersrc", sync_pipe=sync_pipe))

    try:
        assert list(Pipeline(_module_workflow("itersrc"))) == [{"x": 1}]
    finally:
        reset_module_registry()


def test_pipeline_source_seed_runs_end_to_end() -> None:
    def double(source, **_):
        return ({"x": item["x"] * 2} for item in source)

    reset_module_registry()
    sync_pipe = cast("SyncModuleWrapper", double)
    register_module(ModuleDefinition(name="doubler", sync_pipe=sync_pipe))

    try:
        expected = [{"x": 2}, {"x": 4}]
        assert list([{"x": 1}, {"x": 2}] | Pipeline.from_module("doubler")) == expected
        assert list(Pipeline(source=[{"x": 10}]).pipe("doubler")) == [{"x": 20}]
    finally:
        reset_module_registry()


@async_test
async def test_pipeline_async_source_seed_runs_end_to_end() -> None:
    async def adouble(source, **_):
        async for item in source:
            yield {"x": item["x"] * 2}

    reset_module_registry()
    async_pipe = cast("AsyncModuleWrapper", adouble)
    register_module(ModuleDefinition(name="adoubler", async_pipe=async_pipe))

    try:
        streamed = _agen_source() | Pipeline.from_module("adoubler")
        assert [item async for item in streamed] == [{"x": 2}, {"x": 4}]
        awaited = _awaitable_source() | Pipeline.from_module("adoubler")
        assert [item async for item in awaited] == [{"x": 2}, {"x": 4}]
    finally:
        reset_module_registry()


def test_pipeline_iter_closes_upstream_on_early_break() -> None:
    closed: list[bool] = []

    def src(_items=None, **_):
        try:
            yield {"x": 1}
            yield {"x": 2}
        finally:
            closed.append(True)

    reset_module_registry()
    sync_pipe = cast("SyncModuleWrapper", src)
    register_module(ModuleDefinition(name="itersrc2", sync_pipe=sync_pipe))

    try:
        iterator = iter(Pipeline(_module_workflow("itersrc2")))
        assert next(iterator) == {"x": 1}
        iterator.close()
        assert closed == [True]
    finally:
        reset_module_registry()


async def _acollect(stream, seen):
    async for item in stream:
        seen.append(item)


async def _arun(workflow, dispatcher, output="default"):
    plan = build_execution_plan(workflow, dispatcher=dispatcher)

    async with AsyncExecution() as execution:
        stream = await execution.run(plan, output)
        return [item async for item in stream]


@async_test
async def test_arun_executes_native_async_source() -> None:
    async def src(_items=None, **_):
        yield {"x": 1}
        yield {"x": 2}

    async_pipe = cast("AsyncModuleWrapper", src)
    dispatcher = _dispatcher(ModuleDefinition(name="src", async_pipe=async_pipe))
    assert await _arun(_module_workflow("src"), dispatcher) == [{"x": 1}, {"x": 2}]


@async_test
async def test_arun_runs_sync_only_node_via_worker() -> None:
    def src(_items=None, **_):
        yield {"x": 1}
        yield {"x": 2}

    sync_pipe = cast("SyncModuleWrapper", src)
    dispatcher = _dispatcher(ModuleDefinition(name="src", sync_pipe=sync_pipe))
    assert await _arun(_module_workflow("src"), dispatcher) == [{"x": 1}, {"x": 2}]


@async_test
async def test_arun_chains_async_and_sync_worker_nodes() -> None:
    async def src(_items=None, **_):
        yield {"n": 1}

    def double(items, **_):
        return ({"n": row["n"] * 2} for row in items)

    async def atag(items, **_):
        async for row in items:
            yield {**row, "seen": True}

    dispatcher = _dispatcher(
        ModuleDefinition(name="src", async_pipe=cast("AsyncModuleWrapper", src)),
        ModuleDefinition(name="double", sync_pipe=cast("SyncModuleWrapper", double)),
        ModuleDefinition(name="atag", async_pipe=cast("AsyncModuleWrapper", atag)),
    )
    a = ModuleNode(id="a", name="src")
    b = ModuleNode(id="b", name="double")
    c = ModuleNode(id="c", name="atag")
    edges = (
        StreamEdge(Endpoint("a", "out"), Endpoint("b", "in")),
        StreamEdge(Endpoint("b", "out"), Endpoint("c", "in")),
    )
    workflow = _workflow([a, b, c], {"default": Endpoint("c", "out")}, edges=edges)

    assert await _arun(workflow, dispatcher) == [{"n": 2, "seen": True}]


@async_test
async def test_arun_forwards_node_options_as_call_kwargs() -> None:
    seen: dict[str, object] = {}

    async def aprobe(source, **kwargs):
        seen["emit"] = kwargs.get("emit")
        seen["conf"] = dict(kwargs["conf"])

        for item in ():
            yield item

    async_pipe = cast("AsyncModuleWrapper", aprobe)
    dispatcher = _dispatcher(ModuleDefinition(name="aprobe", async_pipe=async_pipe))
    node = ModuleNode(id="n", name="aprobe", options={"emit": True})
    workflow = _workflow([node], {"default": Endpoint("n", "out")})

    assert await _arun(workflow, dispatcher) == []
    assert seen["emit"] is True
    assert seen["conf"] == {}


@async_test
async def test_arun_leaves_the_default_input_empty_for_indexed_ports() -> None:
    seen: dict[str, object] = {}

    async def asrc(_items=None, **_):
        yield {"t": "a"}

    async def amerge(source, others=None, **_):
        seen["source"] = [row async for row in source]

        for other in others or ():
            async for row in other:
                yield row

    dispatcher = _dispatcher(
        ModuleDefinition(name="asrc", async_pipe=cast("AsyncModuleWrapper", asrc)),
        ModuleDefinition(name="amerge", async_pipe=cast("AsyncModuleWrapper", amerge)),
    )
    a = ModuleNode(id="a", name="asrc")
    m = ModuleNode(id="m", name="amerge")
    edge = StreamEdge(Endpoint("a", "out"), Endpoint("m", "in:1"))
    workflow = _workflow([a, m], {"default": Endpoint("m", "out")}, edges=(edge,))

    assert await _arun(workflow, dispatcher) == [{"t": "a"}]
    assert seen["source"] == []


@async_test
async def test_arun_sync_worker_node_adapts_secondary_inputs() -> None:
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

    dispatcher = _dispatcher(
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
    workflow = _workflow([a, b, c, m], {"default": Endpoint("m", "out")}, edges=edges)

    assert await _arun(workflow, dispatcher) == [
        {"t": "a"},
        {"t": "b"},
        {"labeled": "c"},
    ]


@async_test
async def test_arun_sync_only_source_streams_lazily() -> None:
    def src(_items=None, **_):
        yield {"x": 1}
        raise RuntimeError("later")

    sync_pipe = cast("SyncModuleWrapper", src)
    dispatcher = _dispatcher(ModuleDefinition(name="src", sync_pipe=sync_pipe))
    plan = build_execution_plan(_module_workflow("src"), dispatcher=dispatcher)
    first = None

    async with AsyncExecution() as execution:
        stream = await execution.run(plan)
        first = await anext(aiter(stream))

    assert first == {"x": 1}


@async_test
async def test_arun_sync_only_source_raises_after_yielding_earlier_items() -> None:
    def src(_items=None, **_):
        yield {"x": 1}
        yield {"x": 2}
        raise RuntimeError("later")

    sync_pipe = cast("SyncModuleWrapper", src)
    dispatcher = _dispatcher(ModuleDefinition(name="src", sync_pipe=sync_pipe))
    plan = build_execution_plan(_module_workflow("src"), dispatcher=dispatcher)
    seen = []

    async with AsyncExecution() as execution:
        stream = await execution.run(plan)

        with pytest.raises(RuntimeError, match="later"):
            await _acollect(stream, seen)

    assert seen == [{"x": 1}, {"x": 2}]


@async_test
async def test_arun_sync_only_source_closes_on_early_exit() -> None:
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
    dispatcher = _dispatcher(ModuleDefinition(name="src", sync_pipe=sync_pipe))
    plan = build_execution_plan(_module_workflow("src"), dispatcher=dispatcher)
    seen = []

    with fail_after(5):
        async with AsyncExecution() as execution:
            stream = cast("AsyncItemGenerator", await execution.run(plan))

            async for item in stream:
                seen.append(item)

                if len(seen) == 3:
                    break

            await stream.aclose()

    assert seen == [{"x": 0}, {"x": 1}, {"x": 2}]
    assert closed == [True]


@async_test
async def test_arun_unconsumed_sync_only_source_does_not_block_exit() -> None:
    def src(_items=None, **_):
        index = 0

        while True:
            yield {"x": index}
            index += 1

    sync_pipe = cast("SyncModuleWrapper", src)
    dispatcher = _dispatcher(ModuleDefinition(name="src", sync_pipe=sync_pipe))
    plan = build_execution_plan(_module_workflow("src"), dispatcher=dispatcher)

    with fail_after(5):
        async with AsyncExecution() as execution:
            stream = await execution.run(plan)
            assert stream is not None


@async_test
async def test_arun_sync_worker_node_reads_secondary_inputs_lazily() -> None:
    async def asrc(_items=None, **_):
        yield {"t": "a"}

    async def bsrc(_items=None, **_):
        yield {"t": "b"}
        raise RuntimeError("secondary later")

    def merge(items, others=None, **_):
        yield from items

        for other in others or ():
            yield from other

    dispatcher = _dispatcher(
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
    workflow = _workflow([a, b, m], {"default": Endpoint("m", "out")}, edges=edges)
    plan = build_execution_plan(workflow, dispatcher=dispatcher)
    seen = []

    async with AsyncExecution() as execution:
        stream = await execution.run(plan)

        with pytest.raises(RuntimeError, match="secondary later"):
            await _acollect(stream, seen)

    assert seen == [{"t": "a"}, {"t": "b"}]


@async_test
async def test_arun_sync_worker_node_runs_off_the_event_loop() -> None:
    threads = []

    def src(_items=None, **_):
        threads.append(get_ident())
        yield {"x": 1}
        threads.append(get_ident())

    sync_pipe = cast("SyncModuleWrapper", src)
    dispatcher = _dispatcher(ModuleDefinition(name="src", sync_pipe=sync_pipe))
    loop_thread = get_ident()

    assert await _arun(_module_workflow("src"), dispatcher) == [{"x": 1}]
    assert threads
    assert loop_thread not in threads


@async_test
async def test_pipeline_aiter_runs_end_to_end() -> None:
    async def src(_items=None, **_):
        yield {"x": 1}

    reset_module_registry()
    async_pipe = cast("AsyncModuleWrapper", src)
    register_module(ModuleDefinition(name="aitersrc", async_pipe=async_pipe))

    try:
        assert [x async for x in Pipeline(_module_workflow("aitersrc"))] == [{"x": 1}]
    finally:
        reset_module_registry()


@async_test
async def test_pipeline_source_seed_aruns_end_to_end() -> None:
    async def double(source, **_):
        async for item in source:
            yield {"x": item["x"] * 2}

    reset_module_registry()
    async_pipe = cast("AsyncModuleWrapper", double)
    register_module(ModuleDefinition(name="adoubler", async_pipe=async_pipe))

    try:
        flow = [{"x": 1}, {"x": 2}] | Pipeline.from_module("adoubler")
        assert [x async for x in flow] == [{"x": 2}, {"x": 4}]
    finally:
        reset_module_registry()


@async_test
async def test_arun_runs_sync_only_embed_off_the_event_loop() -> None:
    threads: list[int] = []

    def up(item, **_):
        threads.append(get_ident())
        yield {"up": item["t"].upper()}

    async def fakeloop(items, embed=_sync_pipe, **_):
        async for row in as_async(items):
            for value in await maybe_deferred(embed, row):
                yield value

    dispatcher = _dispatcher(
        ModuleDefinition(name="src", sync_pipe=_tagged_source("x")),
        ModuleDefinition(
            name="fakeloop", async_pipe=cast("AsyncModuleWrapper", fakeloop)
        ),
        ModuleDefinition(name="up", sync_pipe=cast("SyncModuleWrapper", up)),
    )
    plan = build_execution_plan(_loop(), dispatcher=dispatcher)
    embed = plan.nodes["loop"].embed
    loop_thread = get_ident()

    assert embed is not None
    assert embed.select(is_async=True).mode is ExecMode.ADAPTER

    async with AsyncExecution() as execution:
        stream = await execution.run(plan)
        assert [item async for item in stream] == [{"up": "X"}]

    assert threads
    assert loop_thread not in threads


@async_test
async def test_arun_adapts_async_only_embed_for_a_sync_loop_on_a_worker() -> None:
    async def up(item, **_):
        yield {"up": item["t"].upper()}

    def fakeloop(items, embed=_sync_pipe, **_):
        for row in items:
            yield from embed(row)

    dispatcher = _dispatcher(
        ModuleDefinition(name="src", sync_pipe=_tagged_source("x")),
        ModuleDefinition(
            name="fakeloop", sync_pipe=cast("SyncModuleWrapper", fakeloop)
        ),
        ModuleDefinition(name="up", async_pipe=cast("AsyncModuleWrapper", up)),
    )

    assert await _arun(_loop(), dispatcher) == [{"up": "X"}]


def _titled_source(_items=None, **_):
    yield {"title": "a"}
    yield {"title": "b"}


def _real_loop_spec(embed_name="child"):
    return _loop(loop_name="loop", embed_name=embed_name)


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

    return mark_subpipe(_sub)


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

    return cast("AsyncModuleWrapper", mark_subpipe(_sub))


@skipif_issync
def test_run_count_first_stays_lazy_for_an_async_only_embed() -> None:
    produced: list[int] = []
    closed: list[str] = []
    dispatcher = _dispatcher(
        ModuleDefinition(
            name="src", sync_pipe=cast("SyncModuleWrapper", _titled_source)
        ),
        ModuleDefinition(name="loop", sync_pipe=loop_pipe, async_pipe=async_loop),
        ModuleDefinition(name="child", async_pipe=_async_child(produced, closed)),
    )

    assert _run(_real_loop_spec(), dispatcher) == [{"content": "a0"}, {"content": "b0"}]
    assert produced == [0, 0]
    assert closed == ["a", "b"]


@pytest.mark.xfail(
    strict=True,
    reason="owned by the pending lazy cross-mode embed work: a sync-only embed under "
    "an async loop is collected to a list on the worker before the loop takes "
    "its first result, so count='first' cannot stop the child early",
)
@async_test
async def test_arun_count_first_stays_lazy_for_a_sync_only_embed() -> None:
    produced: list[int] = []
    closed: list[str] = []
    dispatcher = _dispatcher(
        ModuleDefinition(
            name="src", sync_pipe=cast("SyncModuleWrapper", _titled_source)
        ),
        ModuleDefinition(name="loop", sync_pipe=loop_pipe, async_pipe=async_loop),
        ModuleDefinition(name="child", sync_pipe=_sync_child(produced, closed)),
    )

    assert await _arun(_real_loop_spec(), dispatcher) == [
        {"content": "a0"},
        {"content": "b0"},
    ]
    assert produced == [0, 0]
    assert closed == ["a", "b"]
