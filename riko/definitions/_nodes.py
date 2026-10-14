# vim: sw=4:ts=4:expandtab
"""
The closed node and edge families a ``Workflow`` graph is built from.

Six node families (``ModuleNode``/``ReadNode``/``WriteNode``/``CacheNode``/
``ActionNode``/``SubscribeNode``) share the identity, resource bindings, and label of
``Node``. Two edge families (``StreamEdge``/``PublishEdge``) connect their ports.

Nodes carry declarative intent, never execution state, and no node runs here.
``WriteNode`` and ``ActionNode`` carry a ``backend`` and serialization ``fmt`` rather
than a live resource or write session.

"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from functools import partial
from typing import TYPE_CHECKING, ClassVar

from attrs import define, field

from riko.base.exceptions import InvalidPipelineError
from riko.types._collections import (
    FrozenConf,
    FrozenDict,
    FrozenJSON,
    FrozenParams,
    FrozenPolicy,
    def_from_require,
    def_from_typed_dict,
    freeze_json,
    narrow_def_from_require,
    narrow_from_require,
    normalize_strs,
    optional_mapping_converter,
    require_binding,
    require_str,
    validator_from_require,
)
from riko.types._compiler import Embed
from riko.types._enums import Backends, Formats, resolve_enum
from riko.types._guards import require_mapping
from riko.types._workflow import Edge, NodeId
from riko.types.modules import CallOptions, ConfValues, MaybeFrozenConf

from ._resource_definition import ResourcesLike
from ._write import WriteMode

if TYPE_CHECKING:
    from riko.types._workflow import EdgeFamily, NodeFamily

_NO_OPTIONS = CallOptions()
_FROZEN_PARAMS: FrozenDict[str, FrozenJSON] = FrozenDict()
_FROZEN_POLICY: FrozenDict[str, FrozenJSON] = FrozenDict()
EMPTY_BINDINGS: FrozenDict[str, str] = FrozenDict()
FROZEN_CONF: FrozenConf = FrozenDict()

type ConfInput = MaybeFrozenConf | Mapping[str, ConfValues]

_normalize_backend = partial(resolve_enum, Backends)
_normalize_format = partial(resolve_enum, Formats, strict=False)
_normalize_mode = partial(resolve_enum, WriteMode, default=WriteMode.REPLACE)

optional_str = narrow_def_from_require(require_str)

keys_converter = partial(normalize_strs, what="WriteNode 'keys'")
json_converter = partial(optional_mapping_converter, freeze_json)
binding_converter = narrow_def_from_require(
    require_binding, EMPTY_BINDINGS, "node 'resources'", accepted=ResourcesLike
)
conf_converter = partial(json_converter, ConfInput)
_options_converter = partial(CallOptions.from_raw, what="ModuleNode 'options'")
_module_conf_converter = conf_converter(what="ModuleNode 'conf'")


def _normalize_embed_conf(
    value: Mapping[str, object], what: str | None = None, **_
) -> Mapping[str, object]:
    """Fills an omitted embed ``conf`` with an empty configuration."""
    return value if "conf" in value else {**value, "conf": {}}


def require_embed_fields(value: Embed, what: str = "embed") -> Embed:
    """Validates an Embed's keys."""
    require_str(value["name"], f"{what} 'name'")
    require_mapping(value["conf"], f"{what} 'conf'")
    optional_str(value.get("id"))
    return value


@define(frozen=True, slots=True, kw_only=True)
class Node:
    """The identity, resource bindings, and label every node family carries."""

    family: ClassVar[NodeFamily]
    id: NodeId = field(validator=validator_from_require(require_str))
    name: str = field(converter=narrow_from_require(require_str))
    resources: FrozenDict[str, str] = field(
        default=EMPTY_BINDINGS, converter=binding_converter
    )
    label: str | None = field(default=None, converter=optional_str)

    @property
    def referenced_resources(self) -> set[str]:
        """Collects the Context resource names this node binds."""
        return set(self.resources.values())


@define(frozen=True, slots=True, kw_only=True)
class ModuleNode(Node):
    """
    A module node: any module, including split/branch/route/union/join/loop.

    Attributes:

        conf: the configuration the node's own module parses.

        options: the call options forwarded to the module callable itself, such as
            ``emit``, ``assign``, ``field``, and ``count``.

        embed: names the module a ``loop`` runs once per item, together with that
            module's own configuration.

    """

    family: ClassVar[NodeFamily] = "module"
    conf: FrozenConf = field(default=FROZEN_CONF, converter=_module_conf_converter)
    options: CallOptions = field(default=_NO_OPTIONS, converter=_options_converter)
    embed: Embed | None = field(
        default=None,
        converter=[
            def_from_require(require_mapping, what="ModuleNode 'embed'"),
            def_from_require(_normalize_embed_conf),
            def_from_typed_dict(Embed, what="ModuleNode 'embed'"),
            freeze_json,
        ],
        validator=validator_from_require(require_embed_fields, optional=True),
    )


@define(frozen=True, slots=True, kw_only=True)
class ReadNode(Node):
    """A node that acquires records from a backend, interpreting them via a format."""

    family: ClassVar[NodeFamily] = "read"
    backend: Backends = field(converter=_normalize_backend)
    fmt: Formats | None = field(default=None, converter=_normalize_format)


@define(frozen=True, slots=True, kw_only=True)
class WriteNode(Node):
    """A node that writes an item stream to a backend destination with a format."""

    family: ClassVar[NodeFamily] = "write"
    backend: Backends = field(converter=_normalize_backend)
    dest: str | None = field(default=None, converter=optional_str)
    fmt: Formats | None = field(default=None, converter=_normalize_format)
    mode: WriteMode = field(default=WriteMode.REPLACE, converter=_normalize_mode)
    keys: tuple[str, ...] = field(default=(), converter=keys_converter)


@define(frozen=True, slots=True, kw_only=True)
class ActionNode(Node):
    """A node that runs a backend command that is not a data write."""

    family: ClassVar[NodeFamily] = "action"
    backend: Backends = field(converter=_normalize_backend)
    params: FrozenParams = field(
        default=_FROZEN_PARAMS, converter=json_converter(what="ActionNode 'params'")
    )


@define(frozen=True, slots=True, kw_only=True)
class CacheNode(Node):
    """A node carrying cache identity and policy, never cache contents."""

    family: ClassVar[NodeFamily] = "cache"
    policy: FrozenPolicy = field(
        default=_FROZEN_POLICY, converter=json_converter(what="CacheNode 'policy'")
    )


@define(frozen=True, slots=True, kw_only=True)
class SubscribeNode(Node):
    """A node owning subscription policy for a published stream."""

    family: ClassVar[NodeFamily] = "subscribe"
    policy: FrozenPolicy = field(
        default=_FROZEN_POLICY, converter=json_converter(what="SubscribeNode 'policy'")
    )


@define(frozen=True, slots=True)
class StreamEdge(Edge):
    """A stream edge delivering items from a source port to a target port."""

    family: ClassVar[EdgeFamily] = "stream"


@define(frozen=True, slots=True)
class PublishEdge(Edge):
    """A publish edge delivering a producer's output stream to a subscribe node."""

    family: ClassVar[EdgeFamily] = "publish"


def get_family_edges(
    edges: Iterable[Edge], family: EdgeFamily = "stream"
) -> list[Edge]:
    """
    Selects the edges of one family, in listing order.

    Args:

        edges: The edges to select from.
        family: The edge family to keep.

    Returns:

        The ``family`` edges among ``edges``.

    Examples:

        >>> from riko import Endpoint
        >>>
        >>> end = Endpoint("a", "out")
        >>> edges = [StreamEdge(end, end), PublishEdge(end, end)]
        >>> [edge.family for edge in get_family_edges(edges, "publish")]
        ['publish']

    """
    return [edge for edge in edges if edge.family == family]


def require_module_node(value: Node, what: str | None = None, **_) -> ModuleNode:
    if not isinstance(value, ModuleNode):
        msg = f"{value.family} node execution is not yet supported"
        raise InvalidPipelineError(msg if what is None else f"{what}: {msg}")

    return value


__all__ = [
    "ActionNode",
    "CacheNode",
    "ModuleNode",
    "Node",
    "PublishEdge",
    "ReadNode",
    "StreamEdge",
    "SubscribeNode",
    "WriteNode",
]
