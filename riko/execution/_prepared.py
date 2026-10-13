# vim: sw=4:ts=4:expandtab
"""
Builds a ``Workflow``'s immutable execution plan via ``ExecutionPlan.from_workflow``.

The plan carries each node's pipe, found by name (a module such as ``fetch``, or a
stored workflow's ``pipe_<id>``). Building it runs no node and acquires no resources,
and the sync/async executions run it without re-inspecting the ``Workflow``,
dispatcher, or registry.
"""

from __future__ import annotations

from functools import cached_property, partial
from typing import TYPE_CHECKING, Self

from attrs import define, field
from typing_extensions import TypeIs

from riko.base.exceptions import InvalidPipelineError, UnsupportedModuleError
from riko.definitions._nodes import (
    FROZEN_CONF,
    ModuleNode,
    conf_converter,
    require_module_node,
)
from riko.definitions._workflow import Workflow
from riko.types._collections import (
    FrozenConf,
    FrozenDict,
    instances_freezer,
    mapping_converter,
    narrow_from_require,
    optional_mapping_converter,
    require_from_typed_dict,
    require_instance,
    require_str,
    validator_from_require,
)
from riko.types._workflow import parse_port
from riko.types._wrappers import build_call, require_single_output
from riko.types.modules import CallOptions

if TYPE_CHECKING:
    from collections.abc import Mapping

    from riko.definitions._nodes import ConfInput
    from riko.types._collections import FrozenOptions
    from riko.types._workflow import GraphEdge, GraphIndex, NodeId
    from riko.types._wrappers import (
        AnyModuleWrapper,
        AsyncModuleWrapper,
        Dispatcher,
        ModuleWrapper,
        PreparedCall,
        SyncModuleWrapper,
        Terminals,
    )
    from riko.types.modules import ModuleType

type PreparedNodes = FrozenDict[NodeId, PreparedNode]
type ResolvedModules = FrozenDict[NodeId, ResolvedModule]
type ResolvedModulesInput = Mapping[NodeId, ResolvedModule]

_require_call_options = require_from_typed_dict(CallOptions, "ModuleNode 'options'")
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

    @classmethod
    def from_dispatcher(
        cls, dispatcher: Dispatcher, name: str, conf: ConfInput = FROZEN_CONF
    ) -> Self:
        """
        Resolves the module named ``name`` through ``dispatcher`` for sync and async.

        Args:

            dispatcher: Finds the pipe by name, whether a module such as ``fetch`` or
                a stored workflow's ``pipe_<id>``.

            name: The module name to look up.

            conf: The configuration the resolved module runs with.

        Returns:

            The resolved module, with whichever of its sync and async callables the
            dispatcher provides.

        Raises:

            UnsupportedModuleError: If no module has the name.

            UnsupportedWorkflowError: If no stored workflow has the ``pipe_<id>`` name.

        Examples:

            >>> from riko.runtime._resolver import dispatcher
            >>>
            >>> module = ResolvedModule.from_dispatcher(dispatcher, "hash")
            >>> module.name, module.sync_pipe is not None
            ('hash', True)

        """
        dispatcher.validate(name)
        resolve = partial(dispatcher.resolve, name)
        return cls(name, conf, sync_pipe=resolve(), async_pipe=resolve(is_async=True))

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
        incoming: The stream edges that target the node.
        terminals: The names of the extra inputs delivered with each item: a named
            input stream under its port name, positional streams as ``others``, bound
            resources as ``resources``, and a loop's embed as ``embed``, in that order.

    Examples:

        >>> from riko.ext import ModuleNode
        >>> from riko.modules.strconcat import pipe
        >>> from riko.types._workflow import GraphEdge
        >>>
        >>> node = ModuleNode(id="n", name="strconcat", resources="db")
        >>> named = GraphEdge("a", "n", "out", "in:part")
        >>> positional = GraphEdge("b", "n", "out", "in:1")
        >>> module = ResolvedModule("strconcat", sync_pipe=pipe)
        >>> prepared = PreparedNode(node, module, incoming=(named, positional))
        >>> prepared.node.id
        'n'
        >>> dict(prepared.resources)
        {'db': 'db'}
        >>> prepared.terminals
        ('part', 'others', 'resources')

    """

    node: ModuleNode = field(converter=require_module_node)
    module: ResolvedModule = field(validator=_is_module)
    embed: ResolvedModule | None = field(default=None, validator=_is_optional_module)
    incoming: tuple[GraphEdge, ...] = field(default=(), converter=tuple)

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

    @cached_property
    def terminals(self) -> Terminals:
        """The names of the extra inputs delivered with each item, in call order."""
        node = self.node
        ports = [parse_port(edge.target_port) for edge in self.incoming]
        named = [port.name for port in ports if port.name is not None]
        has_others = any(port.is_positional for port in ports)
        others = ["others"] if has_others else []
        resources = ["resources"] if node.resources else []
        embed = [] if node.embed is None else ["embed"]
        return (*named, *others, *resources, *embed)

    def _build_call(self, pipe: ModuleWrapper | None) -> PreparedCall | None:
        if pipe is None:
            call = None
        else:
            conf, options = self.embed_or_self_conf, _require_call_options(self.options)
            call = build_call(pipe, *self.terminals, conf=conf, **options)

        return call

    @cached_property
    def sync_call(self) -> PreparedCall | None:
        """The synchronous pipe's call, prepared once, or ``None`` without one."""
        return self._build_call(self.module.sync_pipe)

    @cached_property
    def async_call(self) -> PreparedCall | None:
        """The asynchronous pipe's call, prepared once, or ``None`` without one."""
        return self._build_call(self.module.async_pipe)

    def select_call(self, pipe: ModuleWrapper) -> PreparedCall:
        """
        Chooses the prepared call matching ``pipe``, the sync or async one selected.

        Args:

            pipe: The pipe ``select_sync`` or ``select_async`` chose.

        Returns:

            The asynchronous pipe's call when ``pipe`` is it, else the synchronous one.

        Raises:

            UnsupportedModuleError: If the module has no pipe matching ``pipe``.

        """
        is_async = self.module.is_async_pipe(pipe)

        if (call := self.async_call if is_async else self.sync_call) is None:
            raise UnsupportedModuleError(self.module.name, "it has no such interface")

        return call


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
    and each loop node's resolved embed. ``from_workflow`` resolves both through a
    dispatcher. An empty workflow (no nodes, edges, or outputs) is the identity plan.
    Running it streams the seed unchanged.

    Attributes:

        workflow: The graph the plan resolves.
        modules: The resolved implementation of each node, keyed by node id.
        embeds: The resolved module each loop node runs per item, keyed by node id.
        index: The workflow's graph index, including each workflow output's subgraph.
        nodes: Each workflow node paired with its resolved module and embed.

    Raises:

        InvalidPipelineError: If ``workflow`` is not a ``Workflow``, its graph is
            invalid, a source port fans out to more than one edge, a node is not a
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

    def __attrs_post_init__(self) -> None:
        self.validate()

    @classmethod
    def from_workflow(cls, workflow: Workflow, dispatcher: Dispatcher) -> Self:
        """
        Builds an executable snapshot of ``workflow`` with every node resolved once.

        Args:

            workflow: The ``Workflow`` to prepare.

            dispatcher: Finds each node's pipe by name, whether a module such as
                ``fetch`` or a stored workflow's ``pipe_<id>``.

        Returns:

            The prepared plan: its graph index and resolved nodes. No node runs and
            no resource is acquired here.

        Raises:

            InvalidPipelineError: If the graph is invalid, a source port fans out to
                more than one edge, a node isn't a module node (write, action, cache,
                or subscribe), or a node runs a multi-output splitter.

            UnsupportedModuleError: If no module has the name a node gives.

            UnsupportedWorkflowError: If no stored workflow has the ``pipe_<id>`` name
                a node gives.

        Examples:

            >>> from riko import Endpoint, Workflow
            >>> from riko.ext import ModuleNode
            >>> from riko.runtime._resolver import dispatcher
            >>>
            >>> workflow = Workflow(
            ...     nodes=[ModuleNode(id="count-1", name="count")],
            ...     outputs={"default": Endpoint("count-1", "out")},
            ... )
            >>> plan = ExecutionPlan.from_workflow(workflow, dispatcher)
            >>> sorted(plan.nodes)
            ['count-1']

        """
        resolve = partial(ResolvedModule.from_dispatcher, dispatcher)
        modules = {k: resolve(n.name, n.conf) for k, n in workflow.module_nodes.items()}
        embeds = {k: resolve(e["name"], e["conf"]) for k, e in workflow.embeds.items()}
        return cls(workflow, modules, embeds)

    @property
    def index(self) -> GraphIndex:
        """The workflow's graph index, including each workflow output's subgraph."""
        return self.workflow.index

    @cached_property
    def nodes(self) -> PreparedNodes:
        """Each workflow node paired with its resolved module and embed."""
        embeds, modules, incoming = self.embeds, self.modules, self.index.incoming
        pairs = self.workflow.module_nodes.items()
        prepared = {
            k: PreparedNode(n, modules[k], embeds.get(k), incoming.get(k, ()))
            for k, n in pairs
        }
        return FrozenDict.from_frozen(prepared)

    def validate(self) -> None:
        """
        Validates that the workflow is runnable and the plan resolves exactly its nodes.

        Raises:

            InvalidPipelineError: If the graph is invalid, a source port fans out to
                more than one edge, a workflow node is not a module node, ``modules``
                does not resolve the workflow's nodes, or ``embeds`` does not resolve
                its loop embeds.

        """
        workflow = self.workflow

        if not workflow.is_empty:
            workflow.validate()

        workflow.require_executable()
        workflow.require_module_only("execution")

        if unresolved := set(workflow.module_nodes).symmetric_difference(self.modules):
            msg = f"modules must match the workflow's nodes: {sorted(unresolved)}"
            raise InvalidPipelineError(msg)
        elif mismatched := set(workflow.embeds).symmetric_difference(self.embeds):
            msg = f"embeds must match the workflow's loop embeds: {sorted(mismatched)}"
            raise InvalidPipelineError(msg)


__all__ = ["ExecutionPlan", "PreparedNode", "ResolvedModule"]
