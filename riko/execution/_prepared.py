# vim: sw=4:ts=4:expandtab
"""
Immutable execution-plan data for a ``Workflow``.

The runtime build boundary resolves a workflow into these nodes; the sync/async
executions then run them without re-inspecting the ``Workflow``, resolver, or
registry. This module carries data only and imports no resolution or graph
machinery.
"""

from __future__ import annotations

from enum import Enum, auto
from typing import TYPE_CHECKING, NamedTuple

from attrs import Factory, define, field

from riko.base.exceptions import UnsupportedModuleError
from riko.definitions._workflow import (
    Node,
    conf_converter,
    options_converter,
    require_module_node,
    resource_converter,
)
from riko.types._collections import (
    FrozenConf,
    FrozenOptions,
    require_str,
    validator_from_require,
)
from riko.types._guards import require_single_output

if TYPE_CHECKING:
    from collections.abc import Mapping

    from riko.types._workflow import NodeFamily, NodeId
    from riko.types._wrappers import (
        AsyncModuleWrapper,
        ModuleWrapper,
        SyncModuleWrapper,
    )
    from riko.types.modules import ModuleType


single_output = validator_from_require(require_single_output, optional=True)


class ExecMode(Enum):
    """How a prepared node's callable runs under the chosen execution mode."""

    NATIVE = auto()
    ADAPTER = auto()


class Selection(NamedTuple):
    """A resolved callable paired with how it runs under an execution mode."""

    pipe: ModuleWrapper
    mode: ExecMode


@define(frozen=True, slots=True)
class PreparedNode:
    """
    One resolved graph node ready to run, with its callables already resolved.

    Attributes:

        node: The ``Workflow`` node this was resolved from.
        id: The canonical node id.
        name: The registered implementation name.
        resources: The node's resource-slot bindings, slot to resource name.
        conf: The node's declarative configuration.
        options: The call options forwarded to the node's module callable.
        sync_pipe: The resolved synchronous callable, or ``None`` if unavailable.
        async_pipe: The resolved asynchronous callable, or ``None`` if unavailable.
        embed: The resolved embed submodule for a loop node, else ``None``.

    Raises:

        InvalidPipelineError: If either resolved callable is a multi-output
            splitter, which no execution can run yet.

    """

    node: Node = field(converter=require_module_node)
    id: NodeId = field(
        default=Factory(lambda self: self.node.id, takes_self=True),
        converter=require_str,
    )
    name: str = field(
        default=Factory(lambda self: self.node.name, takes_self=True),
        converter=require_str,
    )
    resources: Mapping[str, str] = field(
        default=Factory(lambda self: self.node.resources, takes_self=True),
        converter=resource_converter,
    )
    conf: FrozenConf = field(
        default=Factory(lambda self: self.node.conf, takes_self=True),
        converter=conf_converter("PreparedNode"),
    )
    options: FrozenOptions = field(
        default=Factory(lambda self: self.node.options, takes_self=True),
        converter=options_converter("PreparedNode"),
    )
    sync_pipe: SyncModuleWrapper | None = field(default=None, validator=single_output)
    async_pipe: AsyncModuleWrapper | None = field(default=None, validator=single_output)
    embed: PreparedNode | None = field(default=None)

    def select(self, *, is_async: bool) -> Selection:
        """
        Chooses this node's native-or-adapted callable for an execution mode.

        The callable was resolved when the plan was built, so no resolver or
        registry is touched here.

        Args:

            is_async: Whether the node runs under asynchronous execution.

        Returns:

            The resolved pipe and whether it runs natively or adapted.

        Examples:

            >>> from riko.definitions._workflow import ModuleNode
            >>> from riko.runtime._execution_plan import build_execution_plan
            >>> from riko.definitions._workflow import Workflow
            >>> from riko.types._workflow import Endpoint
            >>>
            >>> node = ModuleNode(id="count-1", name="count")
            >>> workflow = Workflow(
            ...     nodes={"count-1": node},
            ...     outputs={"default": Endpoint("count-1", "out")},
            ... )
            >>> plan = build_execution_plan(workflow)
            >>> plan.nodes["count-1"].select(is_async=False).mode.name
            'NATIVE'

        """
        native = self.async_pipe if is_async else self.sync_pipe
        adapted = self.sync_pipe if is_async else self.async_pipe

        if native is None and adapted is not None:
            result = Selection(adapted, ExecMode.ADAPTER)
        elif native is None:
            raise UnsupportedModuleError(f"{self.name!r} has no interfaces")
        else:
            result = Selection(native, ExecMode.NATIVE)

        return result

    @property
    def family(self) -> NodeFamily:
        return self.node.family

    @property
    def embed_or_self_conf(self) -> FrozenConf:
        return self.conf if self.embed is None else self.embed.conf

    @property
    def pipe(self) -> ModuleWrapper | None:
        return self.sync_pipe if self.async_pipe is None else self.async_pipe

    @property
    def module_type(self) -> ModuleType | None:
        """
        Reports the declared module type of this node's resolved implementation.

        Returns:

            The ``processor``/``operator``/``splitter`` type its pipe was decorated
            with, or ``None`` when no resolved pipe carries one.

        """
        return None if self.pipe is None else getattr(self.pipe, "type", None)

    @property
    def loopable(self) -> bool:
        """
        Whether this node's resolved implementation runs one item at a time.

        A loopable node gives the same results whether it is called once with the
        whole stream or once per item, so its items may be spread across workers.
        """
        return self.pipe is not None and getattr(self.pipe, "loopable", False) is True
