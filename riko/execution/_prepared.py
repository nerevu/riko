# vim: sw=4:ts=4:expandtab
"""
Immutable execution-plan data for a ``Workflow``.

The runtime build boundary resolves a workflow into these nodes; the sync/async
executions then run them without re-inspecting the ``Workflow``, resolver, or
registry. This module carries data only and imports no resolution or graph
machinery.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from attrs import define, field

from riko.base.exceptions import UnsupportedModuleError
from riko.definitions._workflow import ModuleNode, conf_converter, require_module_node
from riko.types._collections import FrozenConf, require_str, validator_from_require
from riko.types._guards import require_single_output

if TYPE_CHECKING:
    from collections.abc import Mapping

    from riko.types._collections import FrozenOptions
    from riko.types._workflow import NodeFamily, NodeId
    from riko.types._wrappers import (
        AsyncModuleWrapper,
        ModuleWrapper,
        SyncModuleWrapper,
    )
    from riko.types.modules import ModuleType


single_output = validator_from_require(require_single_output, optional=True)


class Native[P](NamedTuple):
    """A resolved callable that runs natively under the chosen execution mode."""

    pipe: P


class Adapted[P](NamedTuple):
    """A resolved other-mode callable the execution adapts to its own mode."""

    pipe: P


type SyncSelection = Native[SyncModuleWrapper] | Adapted[AsyncModuleWrapper]
type AsyncSelection = Native[AsyncModuleWrapper] | Adapted[SyncModuleWrapper]


@define(frozen=True, slots=True)
class ResolvedModule:
    """
    One registered module implementation, resolved for both execution modes.

    Attributes:

        name: The registered implementation name.
        conf: The configuration the implementation runs with.
        sync_pipe: The resolved synchronous callable, or ``None`` if unavailable.
        async_pipe: The resolved asynchronous callable, or ``None`` if unavailable.

    Raises:

        InvalidPipelineError: If either resolved callable is a multi-output
            splitter, which no execution can run yet.

    Examples:

        >>> from riko.modules.hash import pipe
        >>>
        >>> module = ResolvedModule("hash", {}, sync_pipe=pipe)
        >>> type(module.select_sync()).__name__, type(module.select_async()).__name__
        ('Native', 'Adapted')

    """

    name: str = field(converter=require_str)
    conf: FrozenConf = field(converter=conf_converter("ResolvedModule"))
    sync_pipe: SyncModuleWrapper | None = field(default=None, validator=single_output)
    async_pipe: AsyncModuleWrapper | None = field(default=None, validator=single_output)

    def select_sync(self) -> SyncSelection:
        """
        Chooses the callable a synchronous execution runs, preferring the native one.

        Returns:

            The native synchronous pipe, or the asynchronous pipe to adapt.

        Raises:

            UnsupportedModuleError: If neither callable was resolved.

        """
        if self.sync_pipe is not None:
            result: SyncSelection = Native(self.sync_pipe)
        elif self.async_pipe is not None:
            result = Adapted(self.async_pipe)
        else:
            raise UnsupportedModuleError(f"{self.name!r} has no interfaces")

        return result

    def select_async(self) -> AsyncSelection:
        """
        Chooses the callable an asynchronous execution runs, preferring the native one.

        Returns:

            The native asynchronous pipe, or the synchronous pipe to adapt.

        Raises:

            UnsupportedModuleError: If neither callable was resolved.

        """
        if self.async_pipe is not None:
            result: AsyncSelection = Native(self.async_pipe)
        elif self.sync_pipe is not None:
            result = Adapted(self.sync_pipe)
        else:
            raise UnsupportedModuleError(f"{self.name!r} has no interfaces")

        return result

    @property
    def pipe(self) -> ModuleWrapper | None:
        return self.sync_pipe if self.async_pipe is None else self.async_pipe

    @property
    def module_type(self) -> ModuleType | None:
        """
        Reports the declared module type of the resolved implementation.

        Returns:

            The ``processor``/``operator``/``splitter`` type its pipe was decorated
            with, or ``None`` when no resolved pipe carries one.

        """
        return None if self.pipe is None else getattr(self.pipe, "type", None)

    @property
    def loopable(self) -> bool:
        """
        Whether the implementation runs one item at a time.

        A loopable module gives the same results whether it is called once with
        the whole stream or once per item, so its items may be spread across
        workers.
        """
        return self.pipe is not None and getattr(self.pipe, "loopable", False) is True


@define(frozen=True, slots=True)
class PreparedNode:
    """
    One graph node ready to run: the node, its implementation, and its embed.

    Attributes:

        node: The ``Workflow`` module node this was resolved from.
        module: The node's resolved implementation.
        embed: The resolved module a loop node runs per item, else ``None``.

    Examples:

        >>> from riko.definitions._workflow import ModuleNode, Workflow
        >>> from riko.runtime._execution_plan import build_execution_plan
        >>> from riko.types._workflow import Endpoint
        >>>
        >>> node = ModuleNode(id="count-1", name="count")
        >>> workflow = Workflow(
        ...     nodes={"count-1": node},
        ...     outputs={"default": Endpoint("count-1", "out")},
        ... )
        >>> prepared = build_execution_plan(workflow).nodes["count-1"]
        >>> type(prepared.module.select_sync()).__name__
        'Native'

    """

    node: ModuleNode = field(converter=require_module_node)
    module: ResolvedModule
    embed: ResolvedModule | None = None

    @property
    def id(self) -> NodeId:
        return self.node.id

    @property
    def family(self) -> NodeFamily:
        return self.node.family

    @property
    def resources(self) -> Mapping[str, str]:
        return self.node.resources

    @property
    def options(self) -> FrozenOptions:
        return self.node.options

    @property
    def embed_or_self_conf(self) -> FrozenConf:
        return self.module.conf if self.embed is None else self.embed.conf

    @property
    def loopable(self) -> bool:
        return self.module.loopable


__all__ = [
    "Adapted",
    "AsyncSelection",
    "Native",
    "PreparedNode",
    "ResolvedModule",
    "SyncSelection",
]
