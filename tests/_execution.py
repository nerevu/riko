# vim: sw=4:ts=4:expandtab
"""Provides shared workflow, dispatcher, and seed helpers for execution tests."""

from __future__ import annotations

from contextlib import contextmanager
from inspect import isasyncgenfunction, iscoroutinefunction
from itertools import pairwise
from typing import TYPE_CHECKING, Self, cast

from riko.definitions._nodes import ModuleNode, StreamEdge
from riko.definitions._settings import DEF_EXECUTION_SETTINGS
from riko.definitions._workflow_definition import Workflow
from riko.definitions._wrapping import stamp_wrapper_meta
from riko.execution._async_execution import AsyncExecution
from riko.execution._prepared import ExecutionPlan
from riko.execution._sync_execution import SyncExecution
from riko.runtime._module_registry import ModuleRegistry, module_registry
from riko.runtime._resolver import ResolverDispatcher, dispatcher
from riko.runtime._workflow_resolver import workflow_resolver
from riko.types._workflow import Endpoint

if TYPE_CHECKING:
    from collections.abc import (
        AsyncGenerator,
        AsyncIterator,
        Awaitable,
        Callable,
        Generator,
        Mapping,
        Sequence,
    )

    from riko.definitions._module_definition import ModuleDefinition
    from riko.definitions._settings import ExecutionSettings
    from riko.types._streams import Item
    from riko.types._wrappers import AsyncModuleWrapper, SyncModuleWrapper


OUTPUT_A = {"default": Endpoint("a", "out")}


@contextmanager
def registered_modules(
    *definitions: ModuleDefinition, replace: bool = False
) -> Generator[ModuleRegistry]:
    """Registers *definitions* in a fresh module registry, reset again on exit."""
    module_registry.reset()

    try:
        for definition in definitions:
            module_registry.register(definition, replace=replace)

        yield module_registry
    finally:
        module_registry.reset()


def tag_source[F: Callable[..., object]](fn: F) -> F:
    """Tags a bare test callable as a source module, so an unseeded run may start it."""
    stamp_wrapper_meta(
        fn,
        name=getattr(fn, "name", getattr(fn, "__name__", "source")),
        module_type=getattr(fn, "type", "processor"),
        subtype="source",
        subtypes={"source"},
        pollable=getattr(fn, "pollable", False),
        loopable=getattr(fn, "loopable", False),
        isasync=getattr(
            fn, "isasync", iscoroutinefunction(fn) or isasyncgenfunction(fn)
        ),
        sequential_inputs=getattr(fn, "sequential_inputs", False),
        prepare=getattr(fn, "prepare", None),
    )
    return fn


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
    outputs: Mapping[str, Endpoint] | None = None,
) -> Workflow:
    if outputs is None:
        outputs = {"default": Endpoint(nodes[-1].id, "out")}

    return Workflow(nodes=nodes, outputs=outputs, edges=edges, resources=resources)


def build_chain(*nodes: ModuleNode) -> Workflow:
    pairs = pairwise(nodes)
    edges = [StreamEdge(Endpoint(a.id, "out"), Endpoint(b.id, "in")) for a, b in pairs]
    return build_workflow(list(nodes), edges=tuple(edges))


def module_workflow(name: str = "m") -> Workflow:
    return build_workflow([ModuleNode(id="n", name=name)])


async def agen_source() -> AsyncGenerator[dict[str, int]]:
    yield {"x": 1}
    yield {"x": 2}


async def awaitable_source() -> list[dict[str, int]]:
    return [{"x": 1}, {"x": 2}]


def _mark(func: Callable[..., object]) -> None:
    setattr(func, "loopable", True)  # noqa: B010
    setattr(func, "type", "processor")  # noqa: B010


def mark_loopable(func: Callable[..., object]) -> SyncModuleWrapper:
    """Mark sync *func* as a loopable processor so a plan may map it per item."""
    _mark(func)
    return cast("SyncModuleWrapper", func)


def mark_async_loopable(
    func: Callable[..., AsyncIterator[object] | Awaitable[object]],
) -> AsyncModuleWrapper:
    """Mark async *func* as a loopable processor so a plan may map it per item."""
    _mark(func)
    return cast("AsyncModuleWrapper", func)


def build_chain_plan(*names: str) -> ExecutionPlan:
    """Build a plan chaining one built-in module node per name."""
    nodes = [ModuleNode(id=f"n{i}", name=name) for i, name in enumerate(names)]
    return ExecutionPlan.from_workflow(build_chain(*nodes), dispatcher)


class RecordingSink:
    """Records every execution event it receives, in order."""

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
    resolved = DEF_EXECUTION_SETTINGS if settings is None else settings
    result: list = []

    with SyncExecution(settings=resolved) as execution:
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
    resolved = DEF_EXECUTION_SETTINGS if settings is None else settings
    result: list = []

    async with AsyncExecution(settings=resolved) as execution:
        stream = await execution.arun(_build_plan(plan, dispatcher), output, seed=seed)
        result = [item async for item in stream]

    return result


passthrough_pipe = cast("SyncModuleWrapper", lambda source, **_: iter(source or {}))


def gen_closing_seed(closed: list[str]) -> Generator[Item]:
    """Yields more items than any read-ahead and records ``"closed"`` on close."""
    try:
        for index in range(1, 51):
            yield {"x": index}
    finally:
        closed.append("closed")


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


def tagged_source(tag):
    """Builds a sync source module that yields one item tagged ``tag``."""

    def src(_items=None, **_):
        yield {"t": tag}

    return cast("SyncModuleWrapper", tag_source(src))
