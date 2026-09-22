# vim: sw=4:ts=4:expandtab
"""
The immutable canonical Workflow v2 model and public ``Pipeline`` definition.

Six closed node families (``ModuleNode``/``ReadNode``/``WriteNode``/``CacheNode``/
``ActionNode``/``SubscribeNode``) and two edge families (``StreamEdge``/``PublishEdge``)
compose a ``WorkflowSpec`` graph, wrapped by the public immutable ``Pipeline``. This is
the structural definition surface only: nodes carry declarative intent, never execution
state, and no node runs here. ``WriteNode`` and ``ActionNode`` carry a ``backend`` and
serialization ``fmt`` rather than a live resource or write session.

Examples:

    Basic usage::

        >>> from riko.definitions._workflow import ModuleNode, Pipeline, WorkflowSpec
        >>> from riko.types._workflow import Endpoint
        >>>
        >>> node = ModuleNode(id="fetch-1", name="fetch")
        >>> spec = WorkflowSpec(
        ...     nodes={node.id: node},
        ...     edges=(),
        ...     outputs={"default": Endpoint(node.id, "out")},
        ...     inputs={},
        ... )
        >>> Pipeline(spec).spec.outputs["default"]
        Endpoint(node='fetch-1', port='out')

"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, ClassVar

from riko.types._workflow import WORKFLOW_VERSION

from ._write import WriteMode

if TYPE_CHECKING:
    from collections.abc import Mapping

    from riko.types._enums import Backends, Formats
    from riko.types._workflow import (
        EdgeFamily,
        Endpoint,
        JSONSchema,
        NodeFamily,
        NodeId,
    )

_EMPTY_CONF: Mapping[str, object] = MappingProxyType({})
_EMPTY_RESOURCES: Mapping[str, str] = MappingProxyType({})


@dataclass(frozen=True, slots=True, kw_only=True)
class _Node:
    """The identity, resource bindings, and label every node family carries."""

    id: NodeId
    name: str
    resources: Mapping[str, str] = _EMPTY_RESOURCES
    label: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ModuleNode(_Node):
    """A registered transform/operator node (split/branch/route/union/join/loop too)."""

    family: ClassVar[NodeFamily] = "module"
    conf: Mapping[str, object] = _EMPTY_CONF


@dataclass(frozen=True, slots=True, kw_only=True)
class ReadNode(_Node):
    """A node that acquires records from a backend, interpreting them via a format."""

    family: ClassVar[NodeFamily] = "read"
    backend: Backends
    fmt: Formats | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class WriteNode(_Node):
    """A node that writes a record stream to a backend with a format, mode, and keys."""

    family: ClassVar[NodeFamily] = "write"
    backend: Backends
    fmt: Formats | None = None
    mode: WriteMode = WriteMode.REPLACE
    keys: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class ActionNode(_Node):
    """A node that runs a provider command that is not a data write."""

    family: ClassVar[NodeFamily] = "action"
    backend: Backends
    params: Mapping[str, object] = _EMPTY_CONF


@dataclass(frozen=True, slots=True, kw_only=True)
class CacheNode(_Node):
    """A node carrying cache identity and policy, never cache contents."""

    family: ClassVar[NodeFamily] = "cache"
    policy: Mapping[str, object] = _EMPTY_CONF


@dataclass(frozen=True, slots=True, kw_only=True)
class SubscribeNode(_Node):
    """A node owning subscription policy for a published stream."""

    family: ClassVar[NodeFamily] = "subscribe"
    policy: Mapping[str, object] = _EMPTY_CONF


@dataclass(frozen=True, slots=True)
class StreamEdge:
    """A stream edge delivering records from a source port to a target port."""

    family: ClassVar[EdgeFamily] = "stream"
    source: Endpoint
    target: Endpoint


@dataclass(frozen=True, slots=True)
class PublishEdge:
    """A publish edge delivering a producer's output to a subscribe node."""

    family: ClassVar[EdgeFamily] = "publish"
    source: Endpoint
    target: Endpoint


type Node = ModuleNode | ReadNode | WriteNode | CacheNode | ActionNode | SubscribeNode
type Edge = StreamEdge | PublishEdge


@dataclass(frozen=True, slots=True)
class WorkflowSpec:
    """
    The strict canonical Workflow v2 graph: nodes, edges, outputs, and inputs.

    Mappings are wrapped read-only on construction so a spec cannot be mutated in
    place. Structural validity (closed schema, resolvable references, port rules) is a
    separate concern layered on this container, not enforced here.

    Attributes:

        nodes: The graph nodes keyed by canonical node id.
        edges: The stream and publish edges, in listing order.
        outputs: The named exposed outputs, each an endpoint reference.
        inputs: The declared inputs, each a JSON Schema.
        resources: The declared resource slot names.
        version: The canonical workflow version.

    """

    nodes: Mapping[NodeId, Node]
    edges: tuple[Edge, ...]
    outputs: Mapping[str, Endpoint]
    inputs: Mapping[str, JSONSchema]
    resources: tuple[str, ...] = ()
    version: str = WORKFLOW_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "nodes", MappingProxyType(dict(self.nodes)))
        object.__setattr__(self, "outputs", MappingProxyType(dict(self.outputs)))
        object.__setattr__(self, "inputs", MappingProxyType(dict(self.inputs)))


@dataclass(frozen=True, slots=True)
class Pipeline[T]:
    """
    A public immutable pipeline definition over a canonical Workflow v2 spec.

    ``Pipeline`` is the stable definition surface; execution lands in a later phase.
    The type parameter records the item type the pipeline's execution will yield.

    Attributes:

        spec: The canonical workflow this pipeline defines.

    """

    spec: WorkflowSpec


__all__ = [
    "ActionNode",
    "CacheNode",
    "ModuleNode",
    "Pipeline",
    "PublishEdge",
    "ReadNode",
    "StreamEdge",
    "SubscribeNode",
    "WorkflowSpec",
    "WriteNode",
]
