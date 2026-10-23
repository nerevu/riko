# vim: sw=4:ts=4:expandtab
"""
The closed node and edge families a ``Workflow`` graph is built from.

Seven node families (``ModuleNode``/``CallableNode``/``ReadNode``/``WriteNode``/
``CacheNode``/``ActionNode``/``SubscribeNode``) share the identity, resource bindings,
and label of ``Node``. Two edge families (``StreamEdge``/``PublishEdge``) connect their
ports.

Nodes carry declarative intent, never execution state, and no node runs here.
``WriteNode`` and ``ActionNode`` carry a ``backend`` and serialization ``fmt`` rather
than a live resource or write session.

"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from functools import partial
from itertools import filterfalse
from keyword import iskeyword
from typing import TYPE_CHECKING, Any, ClassVar, Self

from attrs import define, field
from attrs.validators import is_callable

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
    normalize_strs,
    optional_mapping_converter,
    require_binding,
    require_nonblank_str,
    require_str,
    validator_from_require,
)
from riko.types._enums import Backends, Formats, IdentityMode, resolve_enum
from riko.types._guards import require_mapping
from riko.types._pipedef import Embed
from riko.types._scalars import is_non_null_hashable
from riko.types._sentinels import MISSING, MissingType
from riko.types._workflow import Edge, NodeId
from riko.types.modules import CallOptions, ConfValues, MaybeFrozenConf

from ._resource_definition import ResourcesLike
from ._write import WriteMode

if TYPE_CHECKING:
    from riko.types._scalars import NonNullHashable
    from riko.types._workflow import EdgeFamily, NodeFamily

    from ._write import PreparedWrite

_FROZEN_PARAMS: FrozenDict[str, FrozenJSON] = FrozenDict()
_FROZEN_POLICY: FrozenDict[str, FrozenJSON] = FrozenDict()
NO_OPTIONS = CallOptions()
EMPTY_BINDINGS: FrozenDict[str, str] = FrozenDict()
FROZEN_CONF: FrozenConf = FrozenDict()

type ConfInput = MaybeFrozenConf | Mapping[str, ConfValues]
type CallableVersion = NonNullHashable | MissingType
type FrozenKwargs = FrozenDict[str, FrozenJSON]

_normalize_backend = partial(resolve_enum, Backends)
_normalize_format = partial(resolve_enum, Formats, strict=False)
_normalize_mode = partial(resolve_enum, WriteMode, default=WriteMode.REPLACE)
_normalize_identity = partial(
    resolve_enum, IdentityMode, what="CallableNode 'identity'", strict=False
)

optional_str = narrow_def_from_require(require_str)

keys_converter = partial(normalize_strs, what="WriteNode 'keys'")
json_converter = partial(optional_mapping_converter, freeze_json)
binding_converter = narrow_def_from_require(
    require_binding, EMPTY_BINDINGS, "node 'resources'", accepted=ResourcesLike
)
conf_converter = partial(json_converter, ConfInput)
_options_converter = partial(CallOptions.from_raw, what="ModuleNode 'options'")
_module_conf_converter = conf_converter(what="ModuleNode 'conf'")
_is_alias = lambda name: name.isidentifier() and not iskeyword(name)
_kw_converter = json_converter(what="CallableNode 'kwargs'")


def _normalize_embed_conf(
    value: Mapping[str, object], what: str | None = None, **_
) -> Mapping[str, object]:
    """Fills an omitted embed ``conf`` with an empty configuration."""
    return value if "conf" in value else {**value, "conf": {}}


def _require_version(value: object, what: str | None = "value", **_) -> CallableVersion:
    """Requires a declared callable version: ``MISSING`` or a ``NonNullHashable``."""
    if value is None:
        raise TypeError(f"{what} must not be None")
    elif not (isinstance(value, MissingType) or is_non_null_hashable(value)):
        msg = f"{what} must be a hashable scalar or a tuple of them, not "
        raise TypeError(msg + type(value).__name__)

    return value


_is_version = validator_from_require(_require_version)


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
    id: NodeId = field(validator=validator_from_require(require_nonblank_str))
    name: str = field(validator=validator_from_require(require_nonblank_str))
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
    options: CallOptions = field(default=NO_OPTIONS, converter=_options_converter)
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
class CallableNode[T](Node):
    """
    A callable node: applies a Python callable to each item it receives.

    The callable is called once per item with that item, then the keyword arguments,
    then each bound resource as a keyword named after its alias. It is compared by
    identity, and has no ``WorkflowDocument`` representation.

    Attributes:

        fn: The callable to apply to each item.

        version: ``fn``'s durable behavior identity (``MISSING`` if not declared).
        identity: How each result's identity relates to its input item, if declared.
        kwargs: The JSON-native keywords passed to ``fn`` with each item.

    Raises:

        InvalidPipelineError: If a resource alias is not a Python identifier, a keyword
            argument shares a name with a resource alias, ``kwargs`` is not JSON-native,
            or ``identity`` is not an ``IdentityMode``.

        TypeError: If ``fn`` is not callable or ``version`` is ``None`` or unhashable.

    Examples:

        >>> from riko.ext import CallableNode
        >>>
        >>> node = CallableNode(id="len-1", name="len", fn=len, resources="db")
        >>> node.family, dict(node.resources)
        ('callable', {'db': 'db'})
        >>> CallableNode(id="a", name="a", fn=len, resources="db", kwargs={"db": 1})
        Traceback (most recent call last):
            ...
        riko.base.exceptions.InvalidPipelineError: ...share names with resource...

    """

    family: ClassVar[NodeFamily] = "callable"
    fn: Callable[..., T] = field(eq=id, validator=is_callable())
    version: CallableVersion = field(default=MISSING, validator=_is_version)
    identity: IdentityMode | None = field(default=None, converter=_normalize_identity)
    kwargs: FrozenKwargs = field(default=_FROZEN_PARAMS, converter=_kw_converter)

    def __attrs_post_init__(self) -> None:
        if invalid := sorted(filterfalse(_is_alias, self.resources)):
            msg = f"CallableNode resource aliases must be Python identifiers: {invalid}"
            raise InvalidPipelineError(msg)
        elif shared := sorted(set(self.resources).intersection(self.kwargs)):
            msg = "CallableNode keyword arguments share names with resource aliases: "
            msg += f"{shared}"
            raise InvalidPipelineError(msg)


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

    @classmethod
    def from_prepared(cls, prepared: PreparedWrite, *, id: NodeId) -> Self:
        """
        Builds a write node that records a validated write's destination and intent.

        A target without a ``dest`` leaves the node's ``dest`` unset.

        Args:

            prepared: The validated write to record.

        Kwargs:

            id: The node's id.

        Returns:

            A ``write`` node with ``prepared``'s backend, destination, format, mode, and
            keys.

        Examples:

            >>> from riko.definitions._targets import build_write
            >>>
            >>> prepared = build_write("out.jsonl", "append")
            >>> node = WriteNode.from_prepared(prepared, id="write-1")
            >>> node.dest, node.fmt, node.mode
            ('out.jsonl', <Formats.JSONL: 'jsonl'>, <WriteMode.APPEND: 'append'>)
            >>> rebuilt = build_write(node.dest, node.mode, fmt=node.fmt)
            >>> rebuilt.operation == prepared.operation
            True

        """
        location: object = getattr(prepared.target, "dest", None)

        return cls(
            id=id,
            name="write",
            backend=prepared.target.backend,
            dest=None if location is None else str(location),
            fmt=prepared.fmt,
            mode=prepared.operation.mode,
            keys=prepared.operation.keys,
        )


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


type RunnableNode = ModuleNode | CallableNode[Any]


def require_runnable_node(value: Node, what: str | None = None, **_) -> RunnableNode:
    if not isinstance(value, (ModuleNode, CallableNode)):
        msg = f"{value.family} node execution is not yet supported"
        raise InvalidPipelineError(msg if what is None else f"{what}: {msg}")

    return value


__all__ = [
    "ActionNode",
    "CacheNode",
    "CallableNode",
    "ModuleNode",
    "Node",
    "PublishEdge",
    "ReadNode",
    "StreamEdge",
    "SubscribeNode",
    "WriteNode",
]
