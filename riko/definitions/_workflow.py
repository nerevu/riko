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

from collections import Counter
from dataclasses import dataclass
from functools import partial
from itertools import chain
from types import MappingProxyType
from typing import TYPE_CHECKING, ClassVar

from attrs import define, field

from riko.base.exceptions import InvalidPipelineError
from riko.types._collections import (
    FreezeMapping,
    JSONSchema,
    deep_freeze_mapping,
    def_from_require,
    freeze_value,
    require_binding,
    require_str,
)
from riko.types._enums import Backends, Formats
from riko.types._guards import require_mapping
from riko.types._workflow import WORKFLOW_VERSION, Edge, Endpoint, NodeId

from ._resources import normalize_resources
from ._targets import normalize_strs, resolve_enum
from ._write import WriteMode

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from riko.types._streams import AsyncItemGenerator, ItemGenerator
    from riko.types._workflow import EdgeFamily, NodeFamily

_EMPTY_CONF: Mapping[str, object] = MappingProxyType({})
_EMPTY_RESOURCES: Mapping[str, str] = MappingProxyType({})


def freeze_mapping_value(value: Mapping[object, object]) -> JSONSchema:
    return freeze_value(value)


_optional_str = def_from_require(require_str)
_optional_binding = def_from_require(require_binding)
_optional_resources = def_from_require(normalize_resources, default=_EMPTY_RESOURCES)
_optional_freeze = def_from_require(freeze_mapping_value, default=_EMPTY_CONF)
_normalize_backend = partial(resolve_enum, Backends)
_normalize_format = partial(resolve_enum, Formats, strict=False)
_normalize_mode = partial(resolve_enum, WriteMode, default=WriteMode.REPLACE)


def conf_field(what: str | None = None) -> Mapping[str, object]:
    converters = [def_from_require(require_mapping, what=what), _optional_freeze]
    return field(default=_EMPTY_CONF, converter=converters)


@define(frozen=True, slots=True, kw_only=True)
class Node:
    """The identity, resource bindings, and label every node family carries."""

    family: ClassVar[NodeFamily]
    id: NodeId
    name: str = field(converter=require_str)
    resources: Mapping[str, str] = field(
        default=_EMPTY_RESOURCES, converter=[_optional_binding, _optional_resources]
    )
    label: str | None = field(default=None, converter=_optional_str)

    @property
    def declared_resources(self) -> set[str]:
        """Collect the resource slots referenced by nodes."""
        return set(self.resources.values())


@define(frozen=True, slots=True, kw_only=True)
class ModuleNode(Node):
    """A registered transform/operator node (split/branch/route/union/join/loop too)."""

    family: ClassVar[NodeFamily] = "module"
    conf: Mapping[str, object] | None = conf_field("ModuleNode 'conf'")


@define(frozen=True, slots=True, kw_only=True)
class ReadNode(Node):
    """A node that acquires records from a backend, interpreting them via a format."""

    family: ClassVar[NodeFamily] = "read"
    backend: Backends = field(converter=_normalize_backend)
    fmt: Formats | None = field(default=None, converter=_normalize_format)


@define(frozen=True, slots=True, kw_only=True)
class WriteNode(Node):
    """A node that writes a record stream to a backend destination with a format."""

    family: ClassVar[NodeFamily] = "write"
    backend: Backends = field(converter=_normalize_backend)
    dest: str | None = field(default=None, converter=_optional_str)
    fmt: Formats | None = field(default=None, converter=_normalize_format)
    mode: WriteMode = field(default=WriteMode.REPLACE, converter=_normalize_mode)
    keys: tuple[str, ...] = field(default=(), converter=normalize_strs)


@define(frozen=True, slots=True, kw_only=True)
class ActionNode(Node):
    """A node that runs a provider command that is not a data write."""

    family: ClassVar[NodeFamily] = "action"
    backend: Backends = field(converter=_normalize_backend)
    params: Mapping[str, object] | None = conf_field("ActionNode 'params'")


@define(frozen=True, slots=True, kw_only=True)
class CacheNode(Node):
    """A node carrying cache identity and policy, never cache contents."""

    family: ClassVar[NodeFamily] = "cache"
    policy: Mapping[str, object] | None = conf_field("CacheNode 'policy'")


@define(frozen=True, slots=True, kw_only=True)
class SubscribeNode(Node):
    """A node owning subscription policy for a published stream."""

    family: ClassVar[NodeFamily] = "subscribe"
    policy: Mapping[str, object] | None = conf_field("SubscribeNode 'policy'")


@define(frozen=True, slots=True)
class StreamEdge(Edge):
    """A stream edge delivering records from a source port to a target port."""

    family: ClassVar[EdgeFamily] = "stream"


@define(frozen=True, slots=True)
class PublishEdge(Edge):
    """A publish edge delivering a producer's output to a subscribe node."""

    family: ClassVar[EdgeFamily] = "publish"


@define(frozen=True, slots=True)
class WorkflowSpec:
    """
    The strict canonical Workflow v2 graph: nodes, edges, outputs, and inputs.

    Construction canonicalizes field-local representation details such as immutable
    mappings and resource-name shorthand. Does not perform authoring-shape normalization
    or closed-schema rejection. Cross-field graph validity is checked explicitly by
    ``validate()``.

    Attributes:

        nodes: The graph nodes keyed by canonical node id.
        edges: The stream and publish edges, in listing order.
        outputs: The named exposed outputs, each an endpoint reference.
        inputs: The declared inputs, each a JSON Schema.
        resources: The declared resource slot names.
        version: The canonical workflow version.

    Examples:

        >>> node = ModuleNode(id="fetch-1", name="fetch")
        >>> spec = WorkflowSpec(
        ...     nodes={node.id: node},
        ...     outputs={"default": Endpoint(node.id, "out")},
        ...     inputs={},
        ...     resources="db",
        ... )
        >>> spec.resources
        ('db',)
        >>> spec.isvalid
        True

    """

    nodes: Mapping[NodeId, Node] = field(converter=FreezeMapping[NodeId, Node]())
    outputs: Mapping[str, Endpoint] = field(converter=FreezeMapping[str, Endpoint]())
    inputs: JSONSchema = field(converter=deep_freeze_mapping)
    edges: tuple[Edge, ...] = field(factory=tuple, converter=tuple)
    resources: tuple[str, ...] = field(factory=tuple, converter=normalize_strs)
    version: str = WORKFLOW_VERSION

    def ports(self, family: EdgeFamily = "stream") -> Counter[tuple[str, str]]:
        return Counter(edge.port for edge in self.edges if edge.family == family)

    def _gen_edge_target_mismatches(self) -> Iterator[str]:
        """Detects a publish/subscribe mismatch between an edge and its target node."""
        for edge in self.edges:
            node = self.nodes.get(edge.target.node)

            if (edge.family == "publish") != isinstance(node, SubscribeNode):
                yield edge.target.node

    @property
    def endpoints(self) -> list[Endpoint]:
        """Collect every endpoint referenced by an edge or named output."""
        ends = chain.from_iterable((edge.source, edge.target) for edge in self.edges)
        return list(chain(ends, self.outputs.values()))

    @property
    def declared_resources(self) -> set[str]:
        """Collect the resource slots referenced by nodes."""
        nodes = self.nodes.values()
        return set(chain.from_iterable(node.declared_resources for node in nodes))

    def validate(self) -> None:
        """Validate workflow graph structure and references."""
        endpoints = {endpoint.node for endpoint in self.endpoints}

        if self.version != WORKFLOW_VERSION:
            msg = f"unsupported workflow version: {self.version!r}"
            raise InvalidPipelineError(msg)
        elif not self.nodes:
            raise InvalidPipelineError("workflow has no nodes")
        elif mismatched := [key for key, node in self.nodes.items() if key != node.id]:
            raise InvalidPipelineError(f"node id does not match its key: {mismatched}")
        elif missing := endpoints.difference(self.nodes):
            msg = f"references to missing node(s): {sorted(missing)}"
            raise InvalidPipelineError(msg)
        elif crowded := [port for port, count in self.ports().items() if count > 1]:
            msg = f"multiple stream edges into port(s): {sorted(crowded)}"
            raise InvalidPipelineError(msg)
        elif mismatches := sorted(self._gen_edge_target_mismatches()):
            msg = f"edge family disagrees with target node: {mismatches}"
            raise InvalidPipelineError(msg)
        elif undeclared := sorted(self.declared_resources.difference(self.resources)):
            msg = f"unresolved resource reference(s): {undeclared}"
            raise InvalidPipelineError(msg)
        elif not self.outputs:
            raise InvalidPipelineError("workflow exposes no output; declare 'outputs'")

    @property
    def isvalid(self) -> bool:
        """Confirms whether the workflow validates."""
        try:
            self.validate()
        except InvalidPipelineError:
            result = False
        else:
            result = True

        return result


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

    def __iter__(self) -> ItemGenerator:
        """
        Runs the pipeline synchronously, yielding its default output stream.

        Each iteration creates a fresh one-shot execution that owns the run's
        resources for the lifetime of the returned iterator.

        Yields:

            The items produced at the pipeline's default output.

        """
        from riko.runtime._execution._execution import SyncExecution  # noqa: PLC0415
        from riko.runtime._prepare_execution import prepare_execution  # noqa: PLC0415

        plan = prepare_execution(self.spec)

        with SyncExecution() as execution:
            yield from execution.run(plan)

    def __aiter__(self) -> AsyncItemGenerator:
        """
        Runs the pipeline asynchronously, yielding its default output stream.

        Each iteration creates a fresh one-shot execution that owns the run's
        resources for the lifetime of the returned async iterator.

        Yields:

            The items produced at the pipeline's default output.

        """
        from riko.runtime._execution._execution import AsyncExecution  # noqa: PLC0415
        from riko.runtime._prepare_execution import prepare_execution  # noqa: PLC0415

        async def _run() -> AsyncItemGenerator:
            plan = prepare_execution(self.spec, is_async=True)

            async with AsyncExecution() as execution:
                stream = await execution.run(plan)

                async for item in stream:
                    yield item

        return _run()


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
