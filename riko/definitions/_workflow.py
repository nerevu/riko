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
from functools import partial
from itertools import chain
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, ClassVar, Generic, TypeGuard, cast

from attrs import define, field
from typing_extensions import TypeVar

from riko.base.exceptions import InvalidPipelineError
from riko.types._collections import (
    FreezeMapping,
    FrozenConf,
    FrozenConfValues,
    FrozenMap,
    FrozenOptions,
    FrozenOptionValues,
    FrozenParams,
    FrozenPolicy,
    JSONSchema,
    deep_freeze_mapping,
    def_from_require,
    freeze_value,
    narrow_def_from_require,
    narrow_from_require,
    require_binding,
    require_str,
    validator_from_require,
)
from riko.types._enums import Backends, Formats, ModuleNameLike
from riko.types._guards import is_listlike, is_mapping, require_mapping
from riko.types._workflow import WORKFLOW_VERSION, Edge, Endpoint, NodeId
from riko.types.modules import (
    AnyModuleConf,
    Conf,
    ConfValues,
    Embed,
    ModuleOptions,
    OptionValues,
)

from ._resources import normalize_resources
from ._targets import normalize_strs, resolve_enum
from ._write import WriteMode

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping

    from riko.types._streams import AsyncItemGenerator, ItemGenerator, Items
    from riko.types._workflow import EdgeFamily, NodeFamily

_FROZEN_OPTIONS: FrozenMap[FrozenOptionValues] = MappingProxyType({})
_FROZEN_PARAMS: FrozenMap[FrozenOptionValues] = MappingProxyType({})
_FROZEN_POLICY: FrozenMap[FrozenOptionValues] = MappingProxyType({})
_FROZEN_CONF: FrozenMap[FrozenConfValues] = MappingProxyType({})
_MODULE_OPTION_KEYS = frozenset(ModuleOptions.__annotations__)
_EMBED_KEYS = frozenset(Embed.__annotations__)
_EMPTY_INPUTS: JSONSchema = MappingProxyType({})
_EMPTY_RESOURCES: FrozenMap[str] = MappingProxyType({})

T = TypeVar("T", default=Any)


def freeze_mapping_value(value: Mapping[str, object]) -> JSONSchema:
    return freeze_value(value)


def freeze_conf(value: Mapping[str, ConfValues]) -> FrozenConf:
    return cast("FrozenConf", freeze_value(value))


def freeze_options(value: Mapping[str, OptionValues]) -> FrozenOptions:
    return cast("FrozenOptions", freeze_value(value))


optional_binding = def_from_require(require_binding)
optional_resources = def_from_require(normalize_resources, default=_EMPTY_RESOURCES)
optional_str = narrow_def_from_require(require_str)
resource_converter = [optional_binding, optional_resources]

_normalize_backend = partial(resolve_enum, Backends)
_normalize_format = partial(resolve_enum, Formats, strict=False)
_normalize_mode = partial(resolve_enum, WriteMode, default=WriteMode.REPLACE)


def _is_items(value: object) -> TypeGuard[Items]:
    """A stream of items on the left of ``|``, never a string, mapping, or pipeline."""
    return is_listlike(value) and not isinstance(value, Pipeline)


def _is_pipe_spec(value: object) -> TypeGuard[tuple[str, AnyModuleConf]]:
    """A ``(name, conf)`` pair on the right of ``|``."""
    return (
        isinstance(value, tuple)
        and len(value) == 2
        and isinstance(value[0], str)
        and is_mapping(value[1])
    )


def mapping_converter[V, FV](
    freezer: Callable[[Mapping[str, V]], FrozenMap[FV]], what: str | None = None
) -> Callable[[FrozenMap[FV] | Mapping[str, V] | object], FrozenMap[FV]]:
    optional_mapping = def_from_require(require_mapping, default={}, what=what)

    def converter(value: object | None) -> FrozenMap[FV]:
        return freezer(cast("Mapping[str, V]", optional_mapping(value)))

    return converter


def conf_converter(
    what: str | None = None,
) -> Callable[[FrozenConf | Conf | Mapping[str, ConfValues] | None], FrozenConf]:
    return mapping_converter(freeze_conf, f"{what} 'conf'" if what else "conf")


def options_converter(
    what: str | None = None,
) -> Callable[
    [FrozenOptions | ModuleOptions | Mapping[str, OptionValues] | None], FrozenOptions
]:
    return mapping_converter(freeze_options, f"{what} 'options'" if what else "options")


def params_converter(
    what: str | None = None,
) -> Callable[[FrozenParams | Mapping[str, OptionValues] | None], FrozenParams]:
    return mapping_converter(freeze_options, f"{what} 'params'" if what else "params")


def policy_converter(
    what: str | None = None,
) -> Callable[[FrozenPolicy | Mapping[str, OptionValues] | None], FrozenPolicy]:
    what = f"{what} 'policy'" if what else "policy"
    return mapping_converter(freeze_options, what)


def require_options(
    value: Mapping[str, object], what: str = "options"
) -> ModuleOptions:
    """Confirms every key of ``value`` names a supported module call option."""
    if unknown := set(value).difference(_MODULE_OPTION_KEYS):
        msg = f"unknown module option(s) in {what}: {sorted(unknown)}"
        raise InvalidPipelineError(msg)

    return cast("ModuleOptions", value)


def normalize_embed(value: Mapping[str, object], what: str = "embed") -> Embed:
    """Confirms an embed names its module and carries only its supported keys."""
    if unknown := set(value).difference(_EMBED_KEYS):
        raise InvalidPipelineError(f"unknown embed key(s) in {what}: {sorted(unknown)}")
    elif "name" not in value:
        raise InvalidPipelineError(f"missing embed key in {what}: 'name'")
    else:
        _conf = value.get("conf", {})
        _id = value.get("id")
        name = require_str(value["name"], f"{what} 'name'")
        conf = cast("Conf", require_mapping(_conf, f"{what} 'conf'"))
        embed = Embed(name=name, conf=conf)

        if (_id := value.get("id")) is not None:
            embed["id"] = require_str(_id, f"{what} 'id'")

    return embed


@define(frozen=True, slots=True, kw_only=True)
class Node:
    """The identity, resource bindings, and label every node family carries."""

    family: ClassVar[NodeFamily]
    id: NodeId
    name: str = field(converter=narrow_from_require(require_str))
    resources: Mapping[str, str] = field(
        default=_EMPTY_RESOURCES, converter=resource_converter
    )
    label: str = field(default=None, converter=optional_str)

    @property
    def declared_resources(self) -> set[str]:
        """Collect the resource slots referenced by nodes."""
        return set(self.resources.values())


@define(frozen=True, slots=True, kw_only=True)
class ModuleNode(Node):
    """
    A registered transform/operator node (split/branch/route/union/join/loop too).

    ``conf`` is the configuration the node's own module parses. ``options`` are the
    call options forwarded to the module callable itself, such as ``emit``,
    ``assign``, ``field``, and ``count``. ``embed`` names the module a ``loop`` runs
    once per item, together with that module's own configuration.

    """

    family: ClassVar[NodeFamily] = "module"
    conf: FrozenConf = field(
        default=_FROZEN_CONF, converter=conf_converter("ModuleNode")
    )
    options: FrozenOptions = field(
        default=_FROZEN_OPTIONS,
        converter=options_converter("ModuleNode"),
        validator=validator_from_require(require_options),
    )
    embed: Embed | None = field(
        default=None,
        converter=[
            def_from_require(require_mapping, what="ModuleNode 'embed'"),
            def_from_require(normalize_embed, what="ModuleNode 'embed'"),
            def_from_require(freeze_mapping_value),
        ],
    )


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
    dest: str | None = field(default=None, converter=optional_str)
    fmt: Formats | None = field(default=None, converter=_normalize_format)
    mode: WriteMode = field(default=WriteMode.REPLACE, converter=_normalize_mode)
    keys: tuple[str, ...] = field(default=(), converter=normalize_strs)


@define(frozen=True, slots=True, kw_only=True)
class ActionNode(Node):
    """A node that runs a provider command that is not a data write."""

    family: ClassVar[NodeFamily] = "action"
    backend: Backends = field(converter=_normalize_backend)
    params: FrozenParams = field(
        default=_FROZEN_PARAMS, converter=params_converter("ActionNode")
    )


@define(frozen=True, slots=True, kw_only=True)
class CacheNode(Node):
    """A node carrying cache identity and policy, never cache contents."""

    family: ClassVar[NodeFamily] = "cache"
    policy: FrozenPolicy = field(
        default=_FROZEN_POLICY, converter=policy_converter("CacheNode")
    )


@define(frozen=True, slots=True, kw_only=True)
class SubscribeNode(Node):
    """A node owning subscription policy for a published stream."""

    family: ClassVar[NodeFamily] = "subscribe"
    policy: FrozenPolicy = field(
        default=_FROZEN_POLICY, converter=policy_converter("SubscribeNode")
    )


@define(frozen=True, slots=True)
class StreamEdge(Edge):
    """A stream edge delivering records from a source port to a target port."""

    family: ClassVar[EdgeFamily] = "stream"


@define(frozen=True, slots=True)
class PublishEdge(Edge):
    """A publish edge delivering a producer's output to a subscribe node."""

    family: ClassVar[EdgeFamily] = "publish"


def require_module_node(value: Node, what: str | None = None) -> ModuleNode:
    if not isinstance(value, ModuleNode):
        what = what or value.family
        raise InvalidPipelineError(f"{what} node execution is not yet supported")

    return value


def require_spec(value: object) -> WorkflowSpec:
    if not isinstance(value, WorkflowSpec):
        msg = "Pipeline() takes a WorkflowSpec or None; use Pipeline.from_module(name) "
        msg += "for a module or Pipeline(source=items) to seed an item stream"
        raise TypeError(msg)

    return value


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
        ...     resources="db",
        ... )
        >>> spec.resources
        ('db',)
        >>> spec.isvalid
        True

    """

    nodes: Mapping[NodeId, Node] = field(converter=FreezeMapping[NodeId, Node]())
    outputs: Mapping[str, Endpoint] = field(converter=FreezeMapping[str, Endpoint]())
    inputs: JSONSchema = field(default=_EMPTY_INPUTS, converter=deep_freeze_mapping)
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


_EMPTY_SPEC = WorkflowSpec(nodes={}, outputs={}, inputs={})


def _mint_node_id(spec: WorkflowSpec, name: str) -> NodeId:
    """Mints a ``<name>-<occurrence>`` node id unused by the spec's existing nodes."""
    count = len([node for node in spec.nodes.values() if node.name == name]) + 1
    candidate = f"{name}-{count}"

    while candidate in spec.nodes:
        count += 1
        candidate = f"{name}-{count}"

    return candidate


def _build_chained_spec(
    name: str,
    spec: WorkflowSpec | None = None,
    *,
    conf: FrozenConf | Conf | None = None,
    options: FrozenOptions | ModuleOptions | None = None,
    embed: Embed | None = None,
) -> WorkflowSpec:
    """Builds a spec that appends a module node and re-points the default output."""
    spec = _EMPTY_SPEC if spec is None else spec
    node_id = _mint_node_id(spec, name)
    node = ModuleNode(id=node_id, name=name, conf=conf, options=options, embed=embed)

    if (tail := spec.outputs.get("default")) is None:
        edges = spec.edges
    else:
        edges = (*spec.edges, StreamEdge(tail, Endpoint(node_id, "in")))

    return WorkflowSpec(
        nodes={**spec.nodes, node_id: node},
        outputs={**spec.outputs, "default": Endpoint(node_id, "out")},
        inputs=spec.inputs,
        edges=edges,
        resources=spec.resources,
        version=spec.version,
    )


optional_spec = narrow_def_from_require(require_spec, default=_EMPTY_SPEC)


@define(frozen=True, slots=True)
class Pipeline(Generic[T]):
    """
    A public immutable pipeline definition over a canonical Workflow v2 spec.

    ``Pipeline`` is the stable definition surface. Iterating it yields its default
    output stream which is generic over T.

    ``Pipeline(spec)`` wraps a built graph. ``Pipeline.from_module(name)`` seeds a
    module by name, ``Pipeline(source=items)`` seeds an item stream, and ``Pipeline()``
    starts an empty template to compose with ``|``.

    Attributes:

        spec: The canonical workflow this pipeline defines.
        source: The seeded input stream, or ``None`` when the graph supplies its own.

    Examples:

        >>> flow = Pipeline.from_module("fetch").pipe("sort", conf={"combine": "a"})
        >>> sorted(flow.spec.nodes)
        ['fetch-1', 'sort-1']
        >>> flow.spec.outputs["default"]
        Endpoint(node='sort-1', port='out')
        >>> Pipeline(source=[{"x": 1}]).source
        [{'x': 1}]

    """

    spec: WorkflowSpec = field(default=_EMPTY_SPEC, converter=optional_spec)
    source: Items | None = field(default=None, repr=False)

    @classmethod
    def from_module(
        cls,
        name: ModuleNameLike,
        *,
        conf: Conf | None = None,
        options: ModuleOptions | None = None,
        embed: Embed | None = None,
    ) -> Pipeline:
        """
        Builds a pipeline seeded with a single named module node.

        Module existence is not checked here, so a typo surfaces as a
        module-resolution failure when the pipeline runs rather than now.

        Args:

            name: The seeding module's name.
            conf: The module's configuration, if any.
            options: The call options forwarded to the module, if any.
            embed: The module a loop runs per item, with its configuration, if any.

        Returns:

            A new pipeline whose sole node is the named module.

        Examples:

            >>> flow = Pipeline.from_module("fetch").pipe("sort", conf={"combine": "a"})
            >>> sorted(flow.spec.nodes)
            ['fetch-1', 'sort-1']
            >>> flow.spec.outputs["default"]
            Endpoint(node='sort-1', port='out')

        """
        spec = _build_chained_spec(str(name), conf=conf, options=options, embed=embed)
        return cls(spec)

    def _derive(self, spec: WorkflowSpec, source: Items | None) -> Pipeline:
        """Builds a sibling pipeline over a derived spec."""
        return type(self)(spec, source)

    def pipe(
        self,
        name: ModuleNameLike,
        *,
        conf: FrozenConf | Conf | None = None,
        options: FrozenOptions | ModuleOptions | None = None,
        embed: Embed | None = None,
    ) -> Pipeline:
        """
        Chains the next module by name by re-pointing the default output to it.

        Module existence is not checked here, so a typo surfaces as a
        module-resolution failure when the pipeline runs rather than now.

        Args:

            name: The module to append.
            conf: The module's configuration, if any.
            options: The call options forwarded to the module, if any.
            embed: The module a loop runs per item, with its configuration, if any.

        Returns:

            A new pipeline whose default output is the appended module.

        Examples:

            >>> flow = Pipeline.from_module("fetch").pipe("sort", conf={"combine": "a"})
            >>> sorted(flow.spec.nodes)
            ['fetch-1', 'sort-1']
            >>> flow.spec.outputs["default"]
            Endpoint(node='sort-1', port='out')
            >>> delimiter = {"type": "text", "value": " "}
            >>> embed = {"name": "tokenizer", "conf": {"delimiter": delimiter}}
            >>> flow = Pipeline.from_module("itembuilder")
            >>> flow = flow.loop(embed=embed, options={"emit": True})
            >>> flow.spec.nodes["loop-1"].embed["name"]
            'tokenizer'
            >>> dict(flow.spec.nodes["loop-1"].options)
            {'emit': True}

        """
        args = str(name), self.spec
        spec = _build_chained_spec(*args, conf=conf, options=options, embed=embed)
        return self._derive(spec, self.source)

    def __getattr__(self, name: str) -> Callable[..., Pipeline]:
        """
        Chains any module by attribute, so ``.sort()`` appends the sort module.

        Every unknown non-underscore attribute is treated as a module name, so a
        typo surfaces as a module-resolution failure rather than ``AttributeError``.
        Mapping names are excluded to keep a pipeline from looking dict-like to
        duck-typed callers.
        """
        if name.startswith("_") or name in {"keys", "values", "items", "get"}:
            raise AttributeError(name)

        return partial(self.pipe, name)

    def __or__(self, other: object) -> Pipeline:
        """
        Chains a module name, config pair, or single-module template using ``|``.

        Args:

            other: A module name, a ``(name, conf)`` pair, or a one-module pipeline.

        Returns:

            A new pipeline with the module appended.

        Examples:

            >>> flow = Pipeline.from_module("fetch") | "sort"
            >>> sorted(flow.spec.nodes)
            ['fetch-1', 'sort-1']
            >>> flow = Pipeline.from_module("fetch") | ("sort", {"combine": "a"})
            >>> dict(flow.spec.nodes["sort-1"].conf)
            {'combine': 'a'}

        """
        if isinstance(other, str):
            chained = self.pipe(other)
        elif _is_pipe_spec(other):
            name, conf = other
            chained = self.pipe(name, conf=conf)
        elif isinstance(other, Pipeline):
            chained = self._or_template(other)
        else:
            chained = NotImplemented

        return chained

    def _or_template(self, other: Pipeline) -> Pipeline:
        """Chains a single-module, source-less pipeline used as a reusable template."""
        nodes = other.spec.nodes.values()
        node = next(iter(nodes)) if len(nodes) == 1 else None

        if other.source is None and isinstance(node, ModuleNode):
            chained = self.pipe(
                node.name, conf=node.conf, options=node.options, embed=node.embed
            )
        else:
            msg = "pipeline template must define exactly one module"
            raise InvalidPipelineError(msg)

        return chained

    def __ror__(self, other: object) -> Pipeline:
        """
        Seeds an item stream on the left of ``|``.

        Args:

            other: The item stream to bind as this pipeline's source.

        Returns:

            A new pipeline bound to the seeded source.

        Examples:

            >>> items = [{"x": 1}, {"x": 2}]
            >>> flow = items | Pipeline.from_module("sort")
            >>> flow.source is items
            True

        """
        if self.source is None and _is_items(other):
            primed = self._derive(self.spec, other)
        else:
            primed = NotImplemented

        return primed

    def __iter__(self) -> ItemGenerator:
        """
        Synchronously runs the pipeline.

        Each iteration creates a fresh one-shot execution that owns the run's
        resources for the lifetime of the returned iterator.

        Yields:

            The items produced at the pipeline's default output.

        """
        from riko.execution._execution import SyncExecution  # noqa: PLC0415
        from riko.runtime._execution_plan import build_execution_plan  # noqa: PLC0415

        plan = build_execution_plan(self.spec)

        with SyncExecution() as execution:
            yield from execution.run(plan, source=self.source)

    def __aiter__(self) -> AsyncItemGenerator:
        """
        Asynchronously runs the pipeline.

        Each iteration creates a fresh one-shot execution that owns the run's
        resources for the lifetime of the returned async iterator.

        Yields:

            The items produced at the pipeline's default output.

        """
        from riko.execution._execution import AsyncExecution  # noqa: PLC0415
        from riko.runtime._execution_plan import build_execution_plan  # noqa: PLC0415

        async def _run() -> AsyncItemGenerator:
            plan = build_execution_plan(self.spec)

            async with AsyncExecution() as execution:
                stream = await execution.run(plan, source=self.source)

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
