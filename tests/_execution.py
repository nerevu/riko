# vim: sw=4:ts=4:expandtab
"""Provides shared workflow, dispatcher, and seed helpers for execution tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

from riko.definitions._nodes import ModuleNode
from riko.definitions._workflow import Workflow
from riko.runtime._module_registry import ModuleRegistry
from riko.runtime._resolver import ResolverDispatcher
from riko.runtime._workflows import workflow_resolver
from riko.types._workflow import Endpoint

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from riko.definitions.modules import ModuleDefinition


def build_dispatcher(*definitions: ModuleDefinition) -> ResolverDispatcher:
    registry = ModuleRegistry()

    for definition in definitions:
        registry.register(definition, replace=True)

    return ResolverDispatcher(registry, workflow_resolver)


def module_workflow(name: str = "m") -> Workflow:
    node = ModuleNode(id="n", name=name)
    outputs = {"default": Endpoint("n", "out")}
    return Workflow(nodes=[node], outputs=outputs, inputs={}, edges=(), resources=())


async def agen_source() -> AsyncGenerator[dict[str, int]]:
    yield {"x": 1}
    yield {"x": 2}


async def awaitable_source() -> list[dict[str, int]]:
    return [{"x": 1}, {"x": 2}]
