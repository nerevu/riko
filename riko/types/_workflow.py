# vim: sw=4:ts=4:expandtab
"""
Structural contracts for the canonical Workflow v2 graph language.

These are pure, behavior-free contracts shared by the immutable workflow model in
``riko.definitions``: the node/port endpoint reference, the port-grammar parser, the
input reference shape, and the node/edge discriminant vocabularies. The concrete node,
edge, and ``Pipeline`` definitions build on these.

Examples:

    Basic usage::

        >>> from riko.types._workflow import Endpoint, parse_port
        >>>
        >>> Endpoint("normalize-1", "out")
        Endpoint(node='normalize-1', port='out')
        >>> parse_port("out:errors")
        ParsedPort(direction='out', index=None, name='errors')

"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Literal, Required, TypedDict, cast

from attrs import define

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from ._collections import JSONSchema
    from ._enums import BackendLike, FmtLike, StrLike

type NodeId = str
type Port = str
type ResourceName = str

type NodeFamily = Literal["module", "read", "write", "cache", "action", "subscribe"]
type EdgeFamily = Literal["stream", "publish"]
type PortDirection = Literal["in", "out"]

WORKFLOW_VERSION = "2"


class InputRef(TypedDict):
    """A structural reference to a declared workflow input."""

    input: str


class EndpointAuthoring(TypedDict, total=False):
    """Authoring shorthand for an edge or output endpoint; ``node`` is required."""

    node: Required[str]
    port: str


class EdgeAuthoring(TypedDict, total=False):
    """Authoring shorthand for a stream or publish edge between two endpoints."""

    source: Required[EndpointAuthoring]
    target: Required[EndpointAuthoring]
    family: EdgeFamily
    type: EdgeFamily


class NodeAuthoring(TypedDict, total=False):
    """Authoring shorthand for a node of any family, with aliases and optional keys."""

    id: str
    name: Required[str]
    type: NodeFamily
    family: NodeFamily
    label: str
    conf: Mapping[str, object]
    policy: Mapping[str, object]
    params: Mapping[str, object]
    backend: BackendLike
    dest: str
    fmt: FmtLike
    format: FmtLike
    mode: str
    keys: StrLike
    resources: str | Sequence[str] | Mapping[str, str]


class WorkflowAuthoring(TypedDict, total=False):
    """Flexible Workflow v2 authoring envelope normalized into a ``WorkflowSpec``."""

    nodes: Sequence[NodeAuthoring] | Mapping[str, NodeAuthoring]
    outputs: Mapping[str, EndpointAuthoring]
    inputs: JSONSchema
    edges: Sequence[EdgeAuthoring]
    resources: str | Sequence[str]
    version: str


type WorkflowSpecLike = WorkflowAuthoring | Mapping[str, object]


@define(frozen=True, slots=True)
class Endpoint:
    """A reference to one port on one node; edges and outputs point through it."""

    node: NodeId
    port: Port


@define(frozen=True, slots=True)
class Edge:
    """A stream edge delivering records from a source port to a target port."""

    family: ClassVar[EdgeFamily]
    source: Endpoint
    target: Endpoint

    @property
    def port(self) -> tuple[str, str]:
        return self.target.node, self.target.port


@dataclass(frozen=True, slots=True)
class ParsedPort:
    """The parsed structure of a port: direction with an optional position or name."""

    direction: PortDirection
    index: int | None
    name: str | None


def parse_port(port: Port) -> ParsedPort:
    """
    Parses a port string into its direction and optional position or name.

    Args:

        port: A port following the ``in``/``out``, ``in:N``/``out:N``, or
            ``out:<name>`` grammar.

    Returns:

        The parsed direction, positional index, and semantic name.

    Examples:

        >>> parse_port("in")
        ParsedPort(direction='in', index=None, name=None)
        >>> parse_port("out:1")
        ParsedPort(direction='out', index=1, name=None)

    """
    direction, sep, rest = port.partition(":")

    if direction not in {"in", "out"}:
        raise ValueError(f"invalid port direction: {port!r}")

    if not sep:
        index, name = None, None
    elif rest.isdigit():
        index, name = int(rest), None
    elif direction == "out" and rest.isidentifier():
        index, name = None, rest
    else:
        raise ValueError(f"invalid port: {port!r}")

    return ParsedPort(cast("PortDirection", direction), index, name)


__all__ = [
    "WORKFLOW_VERSION",
    "EdgeFamily",
    "Endpoint",
    "InputRef",
    "NodeFamily",
    "NodeId",
    "ParsedPort",
    "Port",
    "PortDirection",
    "ResourceName",
    "parse_port",
]
