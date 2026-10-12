# vim: sw=4:ts=4:expandtab
"""
Immutable execution-plan data for a ``Workflow``.

The runtime build boundary resolves a workflow into these nodes; the sync/async
executions then run them without re-inspecting the ``Workflow``, dispatcher, or
registry. This module carries data only and imports no resolution or graph
machinery.
"""

from __future__ import annotations

from functools import cached_property
from typing import TYPE_CHECKING

from attrs import Factory, define, field
from typing_extensions import TypeIs

from riko.base._iterutils import map_values
from riko.base.exceptions import InvalidPipelineError, UnsupportedModuleError
from riko.definitions._workflow import (
    FROZEN_CONF,
    ModuleNode,
    Workflow,
    conf_converter,
    require_module_node,
)
from riko.types._collections import (
    FrozenConf,
    FrozenDict,
    instances_freezer,
    mapping_converter,
    narrow_from_require,
    optional_mapping_converter,
    require_instance,
    require_str,
    validator_from_require,
)
from riko.types._wrappers import require_single_output

if TYPE_CHECKING:
    from collections.abc import Mapping

    from riko.types._collections import FrozenOptions
    from riko.types._workflow import GraphIndex, NodeFamily, NodeId
    from riko.types._wrappers import (
        AnyModuleWrapper,
        AsyncModuleWrapper,
        ModuleWrapper,
        SyncModuleWrapper,
    )
    from riko.types.modules import ModuleType

type PreparedNodes = FrozenDict[NodeId, PreparedNode]
type ResolvedModules = FrozenDict[NodeId, ResolvedModule]
type ResolvedModulesInput = Mapping[NodeId, ResolvedModule]

_index = lambda self: self.workflow.index
_is_single = validator_from_require(require_single_output, optional=True)
_rmodule_conf_converter = conf_converter(what="ModuleNode 'conf'")


def _validate_distinct_pipes(
    instance: ResolvedModule, _: object, value: AsyncModuleWrapper | None
) -> None:
    if value is not None and value is instance.sync_pipe:
        msg = f"{instance.name!r} uses one callable for both sync and async"
        raise InvalidPipelineError(msg)


@define(frozen=True, slots=True)
class ResolvedModule:
    """
    One module implementation, resolved for both sync and async.

    Attributes:

        name: The registered implementation name.
        conf: The configuration the implementation runs with.
        sync_pipe: The resolved synchronous callable, or ``None`` if unavailable.
        async_pipe: The resolved asynchronous callable, or ``None`` if unavailable.

    Raises:

        InvalidPipelineError: If either resolved callable is a multi-output
            splitter, which no execution can run yet, or one callable fills
            both slots.

    Examples:

        >>> from riko.modules.hash import pipe
        >>>
        >>> module = ResolvedModule("hash", {}, sync_pipe=pipe)
        >>> module.select_sync() is module.select_async() is pipe
        True
        >>> module.is_async_pipe(module.select_async())
        False

    """

    name: str = field(converter=require_str)
    conf: FrozenConf = field(default=FROZEN_CONF, converter=_rmodule_conf_converter)
    sync_pipe: SyncModuleWrapper | None = field(default=None, validator=_is_single)
    async_pipe: AsyncModuleWrapper | None = field(
        default=None, validator=[_is_single, _validate_distinct_pipes]
    )

    def select_sync(self) -> AnyModuleWrapper:
        """
        Chooses the callable a synchronous execution runs, preferring the native one.

        Returns:

            The synchronous pipe, or else the asynchronous pipe to adapt.

        Raises:

            UnsupportedModuleError: If neither callable was resolved.

        """
        if self.sync_pipe is not None:
            result: AnyModuleWrapper = self.sync_pipe
        elif self.async_pipe is not None:
            result = self.async_pipe
        else:
            raise UnsupportedModuleError(self.name, "it has no interfaces")

        return result

    def select_async(self) -> AnyModuleWrapper:
        """
        Chooses the callable an asynchronous execution runs, preferring the native one.

        Returns:

            The asynchronous pipe, or else the synchronous pipe to adapt.

        Raises:

            UnsupportedModuleError: If neither callable was resolved.

        """
        if self.async_pipe is not None:
            result: AnyModuleWrapper = self.async_pipe
        elif self.sync_pipe is not None:
            result = self.sync_pipe
        else:
            raise UnsupportedModuleError(self.name, "it has no interfaces")

        return result

    def is_async_pipe(self, pipe: ModuleWrapper | None) -> TypeIs[AsyncModuleWrapper]:
        """
        Reports whether ``pipe`` is this module's asynchronous implementation.

        Args:

            pipe: A callable chosen by ``select_sync`` or ``select_async``.

        Returns:

            ``True`` when ``pipe`` fills the asynchronous slot.

        """
        return self.async_pipe is not None and pipe is self.async_pipe

    @property
    def pipe(self) -> AnyModuleWrapper | None:
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


_is_module = validator_from_require(require_instance, ResolvedModule)
_is_optional_module = validator_from_require(
    require_instance, ResolvedModule, optional=True
)


@define(frozen=True, slots=True)
class PreparedNode:
    """
    One graph node ready to run: the node, its implementation, and its embed.

    Attributes:

        node: The ``Workflow`` module node this was resolved from.
        module: The node's resolved implementation.
        embed: The resolved module a loop node runs per item, else ``None``.

    Examples:

        >>> from riko.ext import ModuleNode
        >>> from riko.modules.hash import pipe
        >>>
        >>> node = ModuleNode(id="hash-1", name="hash", resources="db")
        >>> prepared = PreparedNode(node, ResolvedModule("hash", sync_pipe=pipe))
        >>> prepared.id
        'hash-1'
        >>> dict(prepared.resources)
        {'db': 'db'}

    """

    node: ModuleNode = field(converter=require_module_node)
    module: ResolvedModule = field(validator=_is_module)
    embed: ResolvedModule | None = field(default=None, validator=_is_optional_module)

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


_rmodule_freezer = instances_freezer(ResolvedModule, "ExecutionPlan module")
_modules_converter = mapping_converter(
    _rmodule_freezer, ResolvedModulesInput, what="ExecutionPlan 'modules'"
)
_embeds_converter = optional_mapping_converter(
    _rmodule_freezer, ResolvedModulesInput, what="ExecutionPlan 'embeds'"
)
_require_workflow = narrow_from_require(
    require_instance, Workflow, what="ExecutionPlan 'workflow'"
)


@define(frozen=True, slots=True)
class ExecutionPlan:
    """
    Pairs a ``Workflow`` with the implementations resolved to run it.

    The plan holds only what its workflow cannot supply: each node's resolved module
    and each loop node's resolved embed. An empty workflow (no nodes, edges, or
    outputs) is the identity plan. Running it streams the seed unchanged.

    Attributes:

        workflow: The graph the plan resolves.
        modules: The resolved implementation of each node, keyed by node id.
        embeds: The resolved module each loop node runs per item, keyed by node id.
        nodes: Each workflow node paired with its resolved module and embed.
        index: The workflow's graph index, including each workflow output's subgraph.

    Raises:

        InvalidPipelineError: If ``workflow`` is not a ``Workflow``, a node is not a
            module node, ``modules`` does not resolve exactly the workflow's nodes, or
            ``embeds`` does not resolve exactly its loop embeds.

    Examples:

        >>> from riko import Endpoint, Workflow
        >>> from riko.ext import ModuleNode
        >>> from riko.modules.hash import pipe
        >>>
        >>> workflow = Workflow(
        ...     nodes=[ModuleNode(id="a", name="hash")],
        ...     outputs={"default": Endpoint("a", "out")},
        ... )
        >>> modules = {"a": ResolvedModule("hash", sync_pipe=pipe)}
        >>> plan = ExecutionPlan(workflow=workflow, modules=modules)
        >>> plan.nodes["a"].node
        ModuleNode(id='a', name='hash', resources=FrozenDict({})...)
        >>> plan.index.order
        ('a',)

    """

    workflow: Workflow = field(converter=_require_workflow)
    modules: ResolvedModules = field(converter=_modules_converter)
    embeds: ResolvedModules = field(default=None, converter=_embeds_converter)
    index: GraphIndex = field(init=False, default=Factory(_index, takes_self=True))

    def __attrs_post_init__(self) -> None:
        self.validate()

    @cached_property
    def nodes(self) -> PreparedNodes:
        """Each workflow node paired with its resolved module and embed."""
        embeds = self.embeds
        modules = self.modules
        pairs = self.workflow.nodes.items()
        prepared = {k: PreparedNode(n, modules[k], embeds.get(k)) for k, n in pairs}
        return FrozenDict.from_frozen(prepared)

    def validate(self) -> None:
        """
        Validates that the plan resolves exactly the workflow's nodes and embeds.

        Raises:

            InvalidPipelineError: If a workflow node is not a module node, ``modules``
                does not resolve the workflow's nodes, or ``embeds`` does not resolve
                its loop embeds.

        """
        nodes = map_values(require_module_node, self.workflow.nodes)
        embedded = {key for key, node in nodes.items() if node.embed is not None}

        if unresolved := sorted(set(nodes).symmetric_difference(self.modules)):
            msg = f"modules must match the workflow's nodes: {unresolved}"
            raise InvalidPipelineError(msg)
        elif mismatched := sorted(embedded.symmetric_difference(self.embeds)):
            msg = f"embeds must match the workflow's loop embeds: {mismatched}"
            raise InvalidPipelineError(msg)


__all__ = [
    "ExecutionPlan",
    "PreparedNode",
    "PreparedNodes",
    "ResolvedModule",
    "ResolvedModules",
]
