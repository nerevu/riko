# vim: sw=4:ts=4:expandtab
"""Provides shared workflow, dispatcher, and seed helpers for execution tests."""

from __future__ import annotations

from itertools import pairwise
from typing import TYPE_CHECKING

from riko.definitions._nodes import ModuleNode, StreamEdge
from riko.definitions._workflow_definition import Workflow
from riko.runtime._module_registry import ModuleRegistry
from riko.runtime._resolver import ResolverDispatcher
from riko.runtime._workflow_resolver import workflow_resolver
from riko.types._workflow import Endpoint

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Mapping, Sequence

    from riko.definitions._module_definition import ModuleDefinition


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
