# vim: sw=4:ts=4:expandtab
"""Provides shared workflow, dispatcher, and seed helpers for execution tests."""

from __future__ import annotations

from contextlib import contextmanager
from inspect import isasyncgenfunction, iscoroutinefunction
from typing import TYPE_CHECKING, Self, cast

from riko.bado.itertools import as_async
from riko.definitions._module_definition import ModuleDefinition
from riko.definitions._nodes import ModuleNode, StreamEdge
from riko.definitions._settings import DEF_EXECUTION_SETTINGS
from riko.definitions._workflow_definition import Workflow
from riko.definitions._wrapping import stamp_wrapper_meta
from riko.execution._async_execution import AsyncExecution
from riko.execution._prepared import ExecutionPlan, PreparedNode
from riko.execution._sync_execution import SyncExecution
from riko.modules.loop import async_pipe as async_loop
from riko.modules.loop import pipe as loop_pipe
from riko.runtime._module_registry import ModuleRegistry, module_registry
from riko.runtime._resolver import ResolverDispatcher, dispatcher
from riko.runtime._workflow_resolver import workflow_resolver
from riko.types._frozendict import freeze
from riko.types._workflow import Endpoint
from riko.types._wrappers import Func
from tests import X_ROWS

if TYPE_CHECKING:
    from collections.abc import (
        AsyncGenerator,
        AsyncIterator,
        Awaitable,
        Generator,
        Sequence,
    )

    from riko.definitions._settings import ExecutionSettings
    from riko.definitions._workflow_definition import Outputs
    from riko.types._frozendict import FrozenDict
    from riko.types._streams import AsyncItemGenerator, Item
    from riko.types._workflow import NodeId
    from riko.types._wrappers import AsyncModuleWrapper, SyncModuleWrapper
    from riko.types.modules import Conf

type AsyncPipeFunc = Func[AsyncIterator[object] | Awaitable[object]]

EMPTY = Workflow(nodes=[], outputs={})
OUTPUT_A = {"default": Endpoint("a", "out")}
OUTPUTS_AB = freeze({"default": Endpoint("a", "out"), "other": Endpoint("b", "out")})
SRC_NODE = ModuleNode(id="a", name="src")
ASRC_NODE = ModuleNode(id="a", name="asrc")
FETCH_NODE = ModuleNode(id="a", name="fetch")
HASH_NODE = ModuleNode(id="a", name="hash")
M_NODE = ModuleNode(id="b", name="m")
PASS_NODE = ModuleNode(id="b", name="pass")
SORT_NODE = ModuleNode(id="b", name="sort")
PROBE_NODE = ModuleNode(id="b", name="probe")
BSRC_NODE = ModuleNode(id="b", name="bsrc")
SPLIT_NODE = ModuleNode(id="s", name="split")
UNION_NODE = ModuleNode(id="u", name="union")
MERGE_NODE = ModuleNode(id="m", name="merge")
Q_CONF = cast("Conf", freeze({"attrs": {"key": "q", "value": {"input": "q"}}}))
Q_NODE = ModuleNode(id="b", name="itembuilder", conf=Q_CONF)

LOOP_DEFINITION = ModuleDefinition(
    name="loop", sync_pipe=loop_pipe, async_pipe=async_loop
)


def _mark(func: Func[object]) -> None:
    setattr(func, "loopable", True)  # noqa: B010
    setattr(func, "type", "processor")  # noqa: B010


def mark_loopable(func: Func[object]) -> SyncModuleWrapper:
    """Mark sync *func* as a loopable processor so a plan may map it per item."""
    _mark(func)
    return cast("SyncModuleWrapper", func)


def build_sync_definition(func: Func[object], *, name: str = "src") -> ModuleDefinition:
    """Builds the definition of module ``name`` whose sync pipe is ``func``."""
    return ModuleDefinition(name=name, sync_pipe=cast("SyncModuleWrapper", func))


PROCESSOR_PROBE = build_sync_definition(
    mark_loopable(lambda item, **_: iter([item])), name="probe"
)


def tag_source[F: Func[object]](fn: F) -> F:
    """Tags a bare test callable as a source module, so an unseeded run may start it."""
    stamp_wrapper_meta(
        fn,
        name=getattr(fn, "name", getattr(fn, "__name__", "source")),
        module_type=getattr(fn, "type", "processor"),
        subtype="source",
        subtypes={"source"},
        pollable=getattr(fn, "pollable", False),
        loopable=getattr(fn, "loopable", False),
        is_async=getattr(
            fn, "is_async", iscoroutinefunction(fn) or isasyncgenfunction(fn)
        ),
        sequential_inputs=getattr(fn, "sequential_inputs", False),
        prepare=getattr(fn, "prepare", None),
    )
    return fn


def tagged_source(tag):
    """Builds a sync source module that yields one item tagged ``tag``."""

    def src(_items=None, **_):
        yield {"t": tag}

    return cast("SyncModuleWrapper", tag_source(src))


SRC_DEFINITION = build_sync_definition(tagged_source("a"))


@contextmanager
def registered_modules(
    *definitions: ModuleDefinition, replace: bool = False
) -> Generator[ModuleRegistry]:
    """Registers *definitions* in an emptied module registry, restored on exit."""
    with module_registry.restoring():
        module_registry.reset()

        try:
            for definition in definitions:
                module_registry.register(definition, replace=replace)

            yield module_registry
        finally:
            # drops any entry-point cache a test filled from patched entry points
            module_registry.reset()


def build_dispatcher(*definitions: ModuleDefinition) -> ResolverDispatcher:
    registry = ModuleRegistry()

    for definition in definitions:
        registry.register(definition, replace=True)

    return ResolverDispatcher(registry, workflow_resolver)


def build_workflow(
    nodes: Sequence[ModuleNode],
    edges: Sequence[StreamEdge] = (),
    resources: Sequence[str] = (),
    *,
    outputs: Outputs | None = None,
) -> Workflow:
    if outputs is None:
        outputs = {"default": Endpoint(nodes[-1].id, "out")}

    return Workflow(nodes=nodes, outputs=outputs, edges=edges, resources=resources)


def module_workflow(name: str = "m") -> Workflow:
    return build_workflow([ModuleNode(id="n", name=name)])


def build_module_plan(resolver: ResolverDispatcher, name: str = "src") -> ExecutionPlan:
    """Builds the plan of a one-node workflow running module ``name``."""
    return ExecutionPlan.from_workflow(module_workflow(name), resolver)


def run_items(
    execution: SyncExecution, plan: ExecutionPlan, *, seed: object = None
) -> Generator[Item]:
    """Runs ``plan`` and returns its open item stream."""
    return cast("Generator[Item]", execution.run(plan, seed=seed))


async def arun_items(
    execution: AsyncExecution, plan: ExecutionPlan, *, seed: object = None
) -> AsyncItemGenerator:
    """Runs ``plan`` asynchronously and returns its open item stream."""
    return cast("AsyncItemGenerator", await execution.arun(plan, seed=seed))


async def agen_source() -> AsyncGenerator[Item]:
    for row in X_ROWS:
        yield dict(row)


async def awaitable_source() -> tuple[FrozenDict[str, int], ...]:
    return X_ROWS


def require_prepared_node(plan: ExecutionPlan, node_id: NodeId) -> PreparedNode:
    """Requires the plan's node ``node_id`` to be a prepared module node."""
    node = plan.nodes[node_id]
    assert isinstance(node, PreparedNode)
    return node


def mark_async_loopable(func: AsyncPipeFunc) -> AsyncModuleWrapper:
    """Mark async *func* as a loopable processor so a plan may map it per item."""
    _mark(func)
    return cast("AsyncModuleWrapper", func)


def _echo(item, **_):
    return iter([item])


def build_echo() -> Func[object]:
    """Builds a fresh, unpicklable copy of ``_echo`` local to its caller."""

    def echo(item, **_):
        return _echo(item)

    return echo


echo_pipe = mark_loopable(_echo)


def build_chain_plan(*names: str) -> ExecutionPlan:
    """Build a plan chaining one built-in module node per name."""
    nodes = [ModuleNode(id=f"n{i}", name=name) for i, name in enumerate(names)]
    return ExecutionPlan.from_workflow(Workflow().with_nodes(*nodes), dispatcher)


def double(source, **_):
    """Doubles each item's ``x``."""
    return ({"x": row["x"] * 2} for row in source)


async def adouble(source, **_):
    """The async twin of ``double``."""
    async for row in source:
        yield {"x": row["x"] * 2}


def build_doubler_plan(name: str) -> ExecutionPlan:
    """Builds a one-node plan whose ``double``/``adouble`` module doubles ``x``."""
    definition = build_sync_definition(double, name="double")
    adefinition = build_async_definition(adouble, name="adouble")
    return build_module_plan(build_dispatcher(definition, adefinition), name)


class RecordingSink:
    """Records every execution event it receives."""

    def __init__(self) -> None:
        self.events: list[object] = []

    def emit(self, event: object) -> None:
        self.events.append(event)


def _build_plan(
    plan: ExecutionPlan | Workflow, resolver: ResolverDispatcher
) -> ExecutionPlan:
    """Builds the plan for a workflow, or passes a plan through."""
    is_plan = isinstance(plan, ExecutionPlan)
    return plan if is_plan else ExecutionPlan.from_workflow(plan, dispatcher=resolver)


def run_plan(
    plan: ExecutionPlan | Workflow,
    *,
    dispatcher: ResolverDispatcher = dispatcher,
    settings: ExecutionSettings | None = None,
    seed: object = None,
    output: str = "default",
) -> list:
    """Runs a plan, or plans and runs a workflow, to a list synchronously."""
    _settings = DEF_EXECUTION_SETTINGS if settings is None else settings
    result: list = []

    with SyncExecution(settings=_settings) as execution:
        stream = execution.run(_build_plan(plan, dispatcher), output, seed=seed)
        result = list(stream)

    return result


async def arun_plan(
    plan: ExecutionPlan | Workflow,
    *,
    dispatcher: ResolverDispatcher = dispatcher,
    settings: ExecutionSettings | None = None,
    seed: object = None,
    output: str = "default",
) -> list:
    """Runs a plan, or plans and runs a workflow, to a list asynchronously."""
    _settings = DEF_EXECUTION_SETTINGS if settings is None else settings
    result: list = []

    async with AsyncExecution(settings=_settings) as execution:
        stream = await execution.arun(_build_plan(plan, dispatcher), output, seed=seed)
        result = [item async for item in stream]

    return result


passthrough_pipe = cast("SyncModuleWrapper", lambda source, **_: iter(source or {}))


def build_pipe_wrapper(**attrs: object) -> SyncModuleWrapper:
    """Builds a pass-through sync pipe that carries ``attrs`` as wrapper attributes."""
    wrapper = cast("SyncModuleWrapper", lambda source, **_: source)

    for key, value in attrs.items():
        setattr(wrapper, key, value)

    return wrapper


def gen_closing_seed(closed: list[str]) -> Generator[Item]:
    """Yields more items than any read-ahead and records ``"closed"`` on close."""
    try:
        for index in range(1, 51):
            yield {"x": index}
    finally:
        closed.append("closed")


async def agen_closing_seed(closed: list[str]) -> AsyncGenerator[Item]:
    """Yields more items than any read-ahead and records ``"closed"`` on close."""
    try:
        for index in range(1, 51):
            yield {"x": index}
    finally:
        closed.append("closed")


def _relay(items, **_):
    """Re-yields each item with a ``for`` loop, which never closes ``items``."""
    for item in items:  # noqa: UP028
        yield item


relay_pipe = cast("SyncModuleWrapper", _relay)


async def _arelay(items, **_):
    """Re-yields each item of a sync or async stream with an ``async for`` loop."""
    async for item in as_async(items):
        yield item


arelay_pipe = cast("AsyncModuleWrapper", _arelay)


class RecordingBranch:
    """A split branch that records when it is first read and each time it closes."""

    def __init__(self, items: list[Item], events: list[str], tag: str) -> None:
        self.items, self.events, self.tag = iter(items), events, tag
        self.started = False

    def __iter__(self) -> Self:
        return self

    def __next__(self) -> Item:
        if not self.started:
            self.started = True
            self.events.append(f"{self.tag}-start")

        return next(self.items)

    def close(self) -> None:
        self.events.append(f"{self.tag}-close")


class ClosingAsyncIterator:
    """A two-item async iterator with ``aclose`` that is not an async generator."""

    def __init__(self, closed: list[str]) -> None:
        self.closed, self.index = closed, 0

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> Item:
        if self.index == 2:
            raise StopAsyncIteration

        self.index += 1
        return {"x": self.index}

    async def aclose(self) -> None:
        self.closed.append("closed")


class AsyncCloseAsyncIterator:
    """A two-item async iterator whose only close is an ``async def close``."""

    def __init__(self, closed: list[str]) -> None:
        self.closed, self.index = closed, 0

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> Item:
        if self.index == 2:
            raise StopAsyncIteration

        self.index += 1
        return {"x": self.index}

    async def close(self) -> None:
        self.closed.append("closed")


def build_async_definition(
    func: Func[object], *, name: str = "src"
) -> ModuleDefinition:
    """Builds the definition of module ``name`` whose async pipe is ``func``."""
    return ModuleDefinition(name=name, async_pipe=cast("AsyncModuleWrapper", func))


SRC_ECHO_DEFINITION = build_sync_definition(passthrough_pipe)
PASS_DEFINITION = build_sync_definition(passthrough_pipe, name="pass")
RELAY_DEFINITION = build_sync_definition(relay_pipe, name="relay")
M_ARELAY_DEFINITION = build_async_definition(arelay_pipe, name="m")
ECHO_DEFINITION = build_sync_definition(echo_pipe, name="echo")
