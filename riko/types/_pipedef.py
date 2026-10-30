"""
Pipe definition and bare-bones DAG typing contracts.

A pipe definition (``PipeDef``) is the older ``src``/``tgt``-wired module listing; a
``PipeDag`` is the bare-bones DAG mapping. Both expand into a ``Workflow``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Literal, NewType, NotRequired, Required, TypedDict

from typing_extensions import TypeIs

from riko.base._config import PIPE_ID_PREFIXES

if TYPE_CHECKING:
    from ._module_ids import ModuleId
    from ._options import RawCallOptions
    from .modules import AnyModuleRawConf, Conf

type PipeDefLike = PipeDef | Mapping[str, object]

PipeId = NewType("PipeId", str)
CountValues = Literal["first", "all"]


def is_pipe_id(value: object) -> TypeIs[PipeId]:
    """
    Reports whether ``value`` is a stored workflow's ``pipe_<id>`` name.

    ``pipe:<id>`` is accepted too, since lookups read it as ``pipe_<id>``.

    Examples:

        >>> is_pipe_id("pipe_demo"), is_pipe_id("pipe:demo"), is_pipe_id("fetch")
        (True, True, False)

    """
    return isinstance(value, str) and value.startswith(PIPE_ID_PREFIXES)


class Embed(TypedDict):
    """
    A loop's embedded module: the module name run once per parent item.

    ``conf`` is the configuration that module parses.

    """

    id: NotRequired[str]
    conf: Conf
    name: str


class EmbedRef(TypedDict):
    type: ModuleId | PipeId | Literal["output"]
    id: str


class PipeModule(EmbedRef, total=False):
    conf: Required[AnyModuleRawConf]
    emit: bool
    assign: str
    field: str
    count: CountValues
    embed: EmbedRef


class EmbedKwargs(TypedDict, total=False):
    """Kwargs a loop passes to its embed per parent — not a full module descriptor."""

    conf: Conf
    field: str
    emit: bool


class WireEndpoint(TypedDict):
    id: str
    moduleid: str


class Wire(TypedDict):
    id: str
    src: WireEndpoint
    tgt: WireEndpoint


class PipeDef(TypedDict):
    """
    A pipe definition: the older ``src``/``tgt``-wired module listing.

    ``migrate_v1_to_v2`` converts one into a ``Workflow``.
    """

    modules: list[PipeModule]
    wires: list[Wire]
    layout: NotRequired[Sequence[Mapping[str, object]]]
    terminaldata: NotRequired[Sequence[Mapping[str, object]]]


class DagModule(TypedDict, total=False):
    name: ModuleId | PipeId
    type: ModuleId | PipeId
    id: str
    conf: Conf
    options: RawCallOptions
    label: str
    embed: Embed
    resources: str | Sequence[str] | Mapping[str, str]


class PipeDag(TypedDict):
    """
    A bare-bones DAG mapping that ``Workflow.parse`` expands into a ``Workflow``.

    ``wires`` is optional (omit for a linear chain in module listing order) and holds
    ``(source_id, target_id)`` entries, optionally followed by the port the wire enters.
    This makes a fan-in operator such as ``union``/``join`` expressible as
    ``("b", "union-1", "in:1")``.

    A module ``id`` is also optional and defaults to ``sw-{n}`` (1-based listing order).
    This is practical for the concise wireless form. Supply ids when ``wires`` reference
    them. The expansion adds no ``PipeDef``-style ``output`` node: the workflow's
    default output is its single leaf.
    """

    modules: list[DagModule]
    wires: NotRequired[Sequence[Sequence[str]]]


__all__ = [
    "DagModule",
    "PipeDag",
    "PipeDef",
    "PipeDefLike",
    "PipeModule",
    "Wire",
    "is_pipe_id",
]
