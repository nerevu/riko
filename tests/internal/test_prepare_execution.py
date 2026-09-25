# vim: sw=4:ts=4:expandtab
"""Tests for canonical workflow indexing and execution preparation."""

import pytest

from riko.base.exceptions import InvalidPipelineError, UnsupportedModuleError
from riko.definitions._workflow import (
    CacheNode,
    ModuleNode,
    Pipeline,
    StreamEdge,
    WorkflowSpec,
)
from riko.definitions.modules import ModuleDefinition
from riko.runtime._execution._execution import AsyncExecution, SyncExecution
from riko.runtime._execution._prepared import ExecMode
from riko.runtime._graph_index import index_workflow
from riko.runtime._module_registry import (
    ModuleRegistry,
    register_module,
    reset_module_registry,
)
from riko.runtime._pipelines import pipeline_resolver
from riko.runtime._prepare_execution import prepare_execution
from riko.runtime._resolver import PipeResolver
from riko.runtime._resources import Resource
from riko.runtime.context import Context
from riko.types._workflow import Endpoint
from tests import async_test

_sync_pipe = lambda source, **_: source
_async_pipe = lambda source, **_: source


def _spec(nodes, outputs, edges=(), resources=()):
    keyed = {node.id: node for node in nodes}
    return WorkflowSpec(
        nodes=keyed, outputs=outputs, inputs={}, edges=edges, resources=resources
    )


def _resolver(*definitions):
    registry = ModuleRegistry()

    for definition in definitions:
        registry.register(definition)

    return PipeResolver(registry, pipeline_resolver)


def _module_spec(name="m"):
    node = ModuleNode(id="n", name=name)
    return _spec([node], {"default": Endpoint("n", "out")})


def test_index_workflow_orders_and_indexes() -> None:
    a = ModuleNode(id="a", name="m")
    b = ModuleNode(id="b", name="m")
    c = ModuleNode(id="c", name="m")
    edge = StreamEdge(Endpoint("a", "out"), Endpoint("b", "in"))
    spec = _spec(
        [a, b, c],
        {"default": Endpoint("b", "out"), "extra": Endpoint("c", "out")},
        edges=(edge,),
    )
    index = index_workflow(spec)

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
    plan = prepare_execution(_module_spec(), resolver=_resolver(definition))
    prepared = plan.nodes["n"]

    assert prepared.mode is ExecMode.NATIVE_SYNC
    assert prepared.pipe is _sync_pipe


def test_prepare_selects_native_async() -> None:
    definition = ModuleDefinition(
        name="m", sync_pipe=_sync_pipe, async_pipe=_async_pipe
    )
    plan = prepare_execution(
        _module_spec(), is_async=True, resolver=_resolver(definition)
    )
    prepared = plan.nodes["n"]

    assert prepared.mode is ExecMode.NATIVE_ASYNC
    assert prepared.pipe is _async_pipe


def test_prepare_adapts_sync_only_under_async() -> None:
    definition = ModuleDefinition(name="m", sync_pipe=_sync_pipe)
    plan = prepare_execution(
        _module_spec(), is_async=True, resolver=_resolver(definition)
    )

    assert plan.nodes["n"].mode is ExecMode.SYNC_VIA_WORKER


def test_prepare_adapts_async_only_under_sync() -> None:
    definition = ModuleDefinition(name="m", async_pipe=_async_pipe)
    plan = prepare_execution(_module_spec(), resolver=_resolver(definition))

    assert plan.nodes["n"].mode is ExecMode.ASYNC_VIA_PORTAL


def test_prepare_does_not_invoke_the_pipe() -> None:
    calls: list[int] = []

    def pipe(source, **_):
        calls.append(1)
        return source

    definition = ModuleDefinition(name="m", sync_pipe=pipe)
    prepare_execution(_module_spec(), resolver=_resolver(definition))

    assert calls == []


def test_prepare_carries_conf_index_and_resources() -> None:
    definition = ModuleDefinition(name="m", sync_pipe=_sync_pipe)
    node = ModuleNode(id="n", name="m", conf={"url": "x"}, resources={"db": "db"})
    spec = _spec([node], {"default": Endpoint("n", "out")}, resources=("db",))
    plan = prepare_execution(spec, resolver=_resolver(definition))
    prepared = plan.nodes["n"]

    assert prepared.conf == {"url": "x"}
    assert set(prepared.resources.values()) == {"db"}
    assert plan.index.outputs["default"].node == "n"


def test_prepare_rejects_unsupported_node_family() -> None:
    spec = _spec([CacheNode(id="c", name="x")], {"default": Endpoint("c", "out")})

    with pytest.raises(InvalidPipelineError, match="cache"):
        prepare_execution(spec, resolver=_resolver())


def test_prepare_rejects_unresolved_module() -> None:
    spec = _module_spec(name="does_not_exist_module")

    with pytest.raises(UnsupportedModuleError):
        prepare_execution(spec, resolver=_resolver())


def test_prepare_validates_before_preparing() -> None:
    spec = _spec([ModuleNode(id="n", name="m")], {})

    with pytest.raises(InvalidPipelineError):
        prepare_execution(spec, resolver=_resolver())


def _run(spec, resolver, output="default"):
    plan = prepare_execution(spec, resolver=resolver)

    with SyncExecution() as execution:
        return list(execution.run(plan, output))


def test_run_executes_single_source_node() -> None:
    def src(_items=None, **_):
        yield {"x": 1}
        yield {"x": 2}

    resolver = _resolver(ModuleDefinition(name="src", sync_pipe=src))

    assert _run(_module_spec("src"), resolver) == [{"x": 1}, {"x": 2}]


def test_run_chains_nodes_through_stream_edge() -> None:
    def src(_items=None, **_):
        yield {"x": 1}
        yield {"x": 2}

    def double(items, **_):
        return ({"x": row["x"] * 2} for row in items)

    resolver = _resolver(
        ModuleDefinition(name="src", sync_pipe=src),
        ModuleDefinition(name="double", sync_pipe=double),
    )
    a = ModuleNode(id="a", name="src")
    b = ModuleNode(id="b", name="double")
    edge = StreamEdge(Endpoint("a", "out"), Endpoint("b", "in"))
    spec = _spec([a, b], {"default": Endpoint("b", "out")}, edges=(edge,))

    assert _run(spec, resolver) == [{"x": 2}, {"x": 4}]


def _tagged_source(tag):
    def src(_items=None, **_):
        yield {"t": tag}

    return src


def test_run_wires_others_ordered_by_port_index() -> None:
    def merge(items, others=None, **_):
        yield from items

        for other in others or ():
            yield from other

    resolver = _resolver(
        ModuleDefinition(name="a", sync_pipe=_tagged_source("a")),
        ModuleDefinition(name="b", sync_pipe=_tagged_source("b")),
        ModuleDefinition(name="c", sync_pipe=_tagged_source("c")),
        ModuleDefinition(name="merge", sync_pipe=merge),
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
    spec = _spec([a, b, c, m], {"default": Endpoint("m", "out")}, edges=edges)

    assert _run(spec, resolver) == [{"t": "a"}, {"t": "b"}, {"t": "c"}]


def test_run_wires_named_input_port_as_kwarg() -> None:
    def joiner(items, side=None, **_):
        yield from items
        yield from side or ()

    resolver = _resolver(
        ModuleDefinition(name="a", sync_pipe=_tagged_source("a")),
        ModuleDefinition(name="side", sync_pipe=_tagged_source("side")),
        ModuleDefinition(name="joiner", sync_pipe=joiner),
    )
    a = ModuleNode(id="a", name="a")
    s = ModuleNode(id="s", name="side")
    j = ModuleNode(id="j", name="joiner")
    edges = (
        StreamEdge(Endpoint("a", "out"), Endpoint("j", "in")),
        StreamEdge(Endpoint("s", "out"), Endpoint("j", "in:side")),
    )
    spec = _spec([a, s, j], {"default": Endpoint("j", "out")}, edges=edges)

    assert _run(spec, resolver) == [{"t": "a"}, {"t": "side"}]


def test_run_injects_bound_resource() -> None:
    sentinel = object()

    def reader(items, **kw):
        yield {"got": kw["resources"]["slot"]}

    resolver = _resolver(ModuleDefinition(name="reader", sync_pipe=reader))
    node = ModuleNode(id="n", name="reader", resources={"slot": "primary"})
    spec = _spec([node], {"default": Endpoint("n", "out")}, resources=("primary",))
    plan = prepare_execution(spec, resolver=resolver)
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

    resolver = _resolver(ModuleDefinition(name="reader", sync_pipe=reader))
    node = ModuleNode(id="n", name="reader", resources={"slot": "primary"})
    spec = _spec([node], {"default": Endpoint("n", "out")}, resources=("primary",))
    plan = prepare_execution(spec, resolver=resolver)
    context = Context().with_resource("primary", db)

    with SyncExecution(context) as execution:
        assert list(execution.run(plan)) == [{"db": "conn"}]
        assert events == ["open"]

    assert events == ["open", "close"]


def test_run_rejects_unprovided_resource() -> None:
    def reader(items, **_):
        yield {}

    resolver = _resolver(ModuleDefinition(name="reader", sync_pipe=reader))
    node = ModuleNode(id="n", name="reader", resources={"slot": "primary"})
    spec = _spec([node], {"default": Endpoint("n", "out")}, resources=("primary",))
    plan = prepare_execution(spec, resolver=resolver)

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

    resolver = _resolver(
        ModuleDefinition(name="a_src", sync_pipe=a_src),
        ModuleDefinition(name="b_src", sync_pipe=b_src),
    )
    a = ModuleNode(id="a", name="a_src")
    b = ModuleNode(id="b", name="b_src")
    outputs = {"default": Endpoint("a", "out"), "other": Endpoint("b", "out")}

    assert _run(_spec([a, b], outputs), resolver) == [{"x": 1}]
    assert ran == ["a"]


def test_run_rejects_missing_output() -> None:
    resolver = _resolver(ModuleDefinition(name="src", sync_pipe=_sync_pipe))
    plan = prepare_execution(_module_spec("src"), resolver=resolver)

    with (
        SyncExecution() as execution,
        pytest.raises(InvalidPipelineError, match="output"),
    ):
        execution.run(plan, "nope")


def test_run_drives_async_only_module_via_portal() -> None:
    async def asrc(_items=None, **_):
        yield {"x": 1}
        yield {"x": 2}

    resolver = _resolver(ModuleDefinition(name="asrc", async_pipe=asrc))

    assert _run(_module_spec("asrc"), resolver) == [{"x": 1}, {"x": 2}]


def test_run_chains_async_only_node_after_sync_node() -> None:
    def src(_items=None, **_):
        yield {"x": 1}

    async def atag(items, **_):
        for row in items:
            yield {**row, "seen": True}

    resolver = _resolver(
        ModuleDefinition(name="src", sync_pipe=src),
        ModuleDefinition(name="atag", async_pipe=atag),
    )
    a = ModuleNode(id="a", name="src")
    b = ModuleNode(id="b", name="atag")
    edge = StreamEdge(Endpoint("a", "out"), Endpoint("b", "in"))
    spec = _spec([a, b], {"default": Endpoint("b", "out")}, edges=(edge,))

    assert _run(spec, resolver) == [{"x": 1, "seen": True}]


def _prepare_loop(embed_conf=None):
    loop = ModuleNode(
        id="loop",
        name="fakeloop",
        conf={
            "embed": {"name": "up", "conf": embed_conf or {}},
            "emit": True,
            "count": "first",
        },
    )
    return _spec([loop], {"default": Endpoint("loop", "out")})


def test_prepare_resolves_nested_embed() -> None:
    up = lambda item, **_: item
    resolver = _resolver(
        ModuleDefinition(name="fakeloop", sync_pipe=_sync_pipe),
        ModuleDefinition(name="up", sync_pipe=up),
    )
    plan = prepare_execution(_prepare_loop({"case": "upper"}), resolver=resolver)
    node = plan.nodes["loop"]

    assert node.embed is not None
    assert node.embed.name == "up"
    assert node.embed.pipe is up
    assert node.conf == {"case": "upper"}
    assert dict(node.options) == {"emit": True, "count": "first"}


def test_prepare_rejects_async_only_embed_under_sync() -> None:
    resolver = _resolver(
        ModuleDefinition(name="fakeloop", sync_pipe=_sync_pipe),
        ModuleDefinition(name="up", async_pipe=_async_pipe),
    )

    with pytest.raises(UnsupportedModuleError, match="pipe"):
        prepare_execution(_prepare_loop(), resolver=resolver)


def test_run_forwards_embed_and_options_to_loop() -> None:
    seen: dict[str, object] = {}

    def up(item, **_):
        yield {"up": item["t"].upper()}

    def fakeloop(items, embed=_sync_pipe, **kwargs):
        seen["embed"] = embed
        seen["options"] = {k: kwargs[k] for k in ("emit", "count") if k in kwargs}

        for row in items:
            yield from embed(row)

    resolver = _resolver(
        ModuleDefinition(name="src", sync_pipe=_tagged_source("x")),
        ModuleDefinition(name="fakeloop", sync_pipe=fakeloop),
        ModuleDefinition(name="up", sync_pipe=up),
    )
    src = ModuleNode(id="s", name="src")
    loop = ModuleNode(
        id="loop",
        name="fakeloop",
        conf={"embed": {"name": "up"}, "emit": True, "count": "first"},
    )
    edge = StreamEdge(Endpoint("s", "out"), Endpoint("loop", "in"))
    spec = _spec([src, loop], {"default": Endpoint("loop", "out")}, edges=(edge,))

    assert _run(spec, resolver) == [{"up": "X"}]
    assert seen["embed"] is up
    assert seen["options"] == {"emit": True, "count": "first"}


def test_pipeline_iter_runs_end_to_end() -> None:
    def src(_items=None, **_):
        yield {"x": 1}

    reset_module_registry()
    register_module(ModuleDefinition(name="itersrc", sync_pipe=src))

    try:
        assert list(Pipeline(_module_spec("itersrc"))) == [{"x": 1}]
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
    register_module(ModuleDefinition(name="itersrc2", sync_pipe=src))

    try:
        iterator = iter(Pipeline(_module_spec("itersrc2")))
        assert next(iterator) == {"x": 1}
        iterator.close()
        assert closed == [True]
    finally:
        reset_module_registry()


async def _arun(spec, resolver, output="default"):
    plan = prepare_execution(spec, is_async=True, resolver=resolver)

    async with AsyncExecution() as execution:
        stream = await execution.run(plan, output)
        return [item async for item in stream]


@async_test
async def test_arun_executes_native_async_source() -> None:
    async def asrc(_items=None, **_):
        yield {"x": 1}
        yield {"x": 2}

    resolver = _resolver(ModuleDefinition(name="asrc", async_pipe=asrc))

    assert await _arun(_module_spec("asrc"), resolver) == [{"x": 1}, {"x": 2}]


@async_test
async def test_arun_runs_sync_only_node_via_worker() -> None:
    def src(_items=None, **_):
        yield {"x": 1}
        yield {"x": 2}

    resolver = _resolver(ModuleDefinition(name="src", sync_pipe=src))

    assert await _arun(_module_spec("src"), resolver) == [{"x": 1}, {"x": 2}]


@async_test
async def test_arun_chains_async_and_sync_worker_nodes() -> None:
    async def asrc(_items=None, **_):
        yield {"n": 1}

    def double(items, **_):
        return ({"n": row["n"] * 2} for row in items)

    async def atag(items, **_):
        async for row in items:
            yield {**row, "seen": True}

    resolver = _resolver(
        ModuleDefinition(name="asrc", async_pipe=asrc),
        ModuleDefinition(name="double", sync_pipe=double),
        ModuleDefinition(name="atag", async_pipe=atag),
    )
    a = ModuleNode(id="a", name="asrc")
    b = ModuleNode(id="b", name="double")
    c = ModuleNode(id="c", name="atag")
    edges = (
        StreamEdge(Endpoint("a", "out"), Endpoint("b", "in")),
        StreamEdge(Endpoint("b", "out"), Endpoint("c", "in")),
    )
    spec = _spec([a, b, c], {"default": Endpoint("c", "out")}, edges=edges)

    assert await _arun(spec, resolver) == [{"n": 2, "seen": True}]


@async_test
async def test_pipeline_aiter_runs_end_to_end() -> None:
    async def asrc(_items=None, **_):
        yield {"x": 1}

    reset_module_registry()
    register_module(ModuleDefinition(name="aitersrc", async_pipe=asrc))

    try:
        assert [x async for x in Pipeline(_module_spec("aitersrc"))] == [{"x": 1}]
    finally:
        reset_module_registry()
