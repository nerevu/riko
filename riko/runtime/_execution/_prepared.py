# vim: sw=4:ts=4:expandtab
"""
Immutable execution-plan data for a canonical workflow.

Preparation resolves a workflow into this plan; the sync/async executions then run
it without re-inspecting the definition, resolver, or registry. This module carries
data only and imports no resolution or graph machinery.
"""

from __future__ import annotations

from enum import Enum, auto
from types import MappingProxyType
from typing import TYPE_CHECKING

from attrs import define

if TYPE_CHECKING:
    from collections.abc import Mapping

    from riko.types._compiler import GraphIndex
    from riko.types._workflow import NodeFamily, NodeId
    from riko.types._wrappers import PipeCallable

_EMPTY_OPTIONS: Mapping[str, object] = MappingProxyType({})


class ExecMode(Enum):
    """How a prepared node's callable runs under the chosen execution mode."""

    NATIVE_SYNC = auto()
    NATIVE_ASYNC = auto()
    SYNC_VIA_WORKER = auto()
    ASYNC_VIA_PORTAL = auto()


@define(frozen=True, slots=True)
class PreparedNode:
    """
    One resolved graph node ready to run, with its adaptation decided.

    Attributes:

        id: The canonical node id.
        name: The registered implementation name.
        family: The node's canonical family.
        pipe: The resolved callable selected for the execution mode.
        mode: How that callable runs (native or adapted).
        conf: The node's declarative configuration.
        resources: The node's resource-slot bindings, slot to resource name.
        embed: The resolved embed submodule for a loop node, else ``None``.
        options: The loop call-site options (``emit``/``count``/``assign``/
            ``field``) forwarded to the operator wrapper, else empty.

    """

    id: NodeId
    name: str
    family: NodeFamily
    pipe: PipeCallable
    mode: ExecMode
    conf: Mapping[str, object] | None
    resources: Mapping[str, str]
    embed: PreparedNode | None = None
    options: Mapping[str, object] = _EMPTY_OPTIONS


@define(frozen=True, slots=True)
class ExecutionPlan:
    """
    A prepared workflow: its graph index, resolved nodes, and per-output subgraphs.

    Attributes:

        index: The structural graph index shared with the compiler.
        nodes: The prepared nodes, keyed by canonical node id.
        required: For each named output, the node ids its subgraph must run.

    """

    index: GraphIndex
    nodes: Mapping[NodeId, PreparedNode]
    required: Mapping[str, frozenset[NodeId]]
