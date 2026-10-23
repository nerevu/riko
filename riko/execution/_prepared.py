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
from typing import TYPE_CHECKING, NamedTuple, Self, cast

from attrs import define, evolve, field
from typing_extensions import TypeIs

from riko.bado._util import async_partial, maybe_async
from riko.bado.itertools import as_async
from riko.base._iterutils import gen_non_none, map_values
from riko.base.exceptions import InvalidPipelineError
from riko.definitions._nodes import (
    FROZEN_CONF,
    NO_OPTIONS,
    CallableNode,
    ModuleNode,
    conf_converter,
    require_runnable_node,
)
from riko.definitions._workflow_definition import Workflow
from riko.types._collections import (
    FrozenConf,
    FrozenDict,
    instances_freezer,
    mapping_converter,
    narrow_from_require,
    normalize_mapping,
    optional_mapping_converter,
    require_instance,
    require_str,
    validator_from_require,
)
from riko.types._guards import is_async_callable
from riko.types._workflow import parse_port
from riko.types._wrappers import build_call, require_single_output

if TYPE_CHECKING:
    from collections.abc import (
        AsyncIterator,
        Awaitable,
        Callable,
        Iterable,
        Iterator,
        Mapping,
    )

    from riko.definitions._context import Context
    from riko.definitions._nodes import ConfInput, RunnableNode
    from riko.types._collections import FrozenJSON
    from riko.types._streams import AnyIterable
    from riko.types._workflow import Endpoint, GraphEdge, GraphIndex, NodeId, ParsedPort
    from riko.types._wrappers import (
        AnyModuleWrapper,
        AsyncModuleWrapper,
        Dispatcher,
        ExtraNames,
        ModuleWrapper,
        PreparedCall,
        SyncModuleWrapper,
    )
    from riko.types.modules import CallOptions

type PreparedNodes = FrozenDict[NodeId, PreparedNode]
type ResolvedModules = FrozenDict[NodeId, ResolvedModule]
type ResolvedModulesInput = Mapping[NodeId, ResolvedModule]

_is_single = validator_from_require(require_single_output, optional=True)
_rmodule_conf_converter = conf_converter(what="ModuleNode 'conf'")


def _is_distinct(
    instance: ResolvedModule, _: object, value: AsyncModuleWrapper | None
) -> None:
    if value is not None and value is instance.sync_pipe:
        msg = f"{instance.name!r} uses one callable for both sync and async"
        raise InvalidPipelineError(msg)


def _has_pipe(
    instance: ResolvedModule, _: object, value: AsyncModuleWrapper | None
) -> None:
    if value is None and instance.sync_pipe is None:
        msg = f"{instance.name!r} has neither a sync nor an async callable"
        raise InvalidPipelineError(msg)


_MODULE_FLAGS = ("loopable", "sequential_inputs")


def _has_flag(pipe: AnyModuleWrapper, flag: str) -> bool:
    return getattr(pipe, flag, False) is True


def _has_flag_mismatch(
    flag: str, sync_pipe: SyncModuleWrapper, async_pipe: AsyncModuleWrapper
) -> bool:
    return _has_flag(sync_pipe, flag) != _has_flag(async_pipe, flag)


def _is_consistent(
    instance: ResolvedModule, _: object, value: AsyncModuleWrapper | None
) -> None:
    if (sync_pipe := instance.sync_pipe) is not None and value is not None:
        _diff = partial(_has_flag_mismatch, sync_pipe=sync_pipe, async_pipe=value)

        if differing := tuple(filter(_diff, _MODULE_FLAGS)):
            msg = f"{instance.name!r} has sync and async callables that disagree on "
            msg += ", ".join(repr(flag) for flag in differing)
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

        InvalidPipelineError: If neither callable is given, either resolved callable is
            a splitter, one callable fills both slots, or the two callables disagree on
            whether the module is loopable or reads its input streams one at a time.

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
        default=None, validator=[_is_single, _is_distinct, _has_pipe, _is_consistent]
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
        Chooses the callable a synchronous execution runs.

        Returns:

            The synchronous pipe, or the asynchronous pipe to adapt.

        """
        return self.select_async() if self.sync_pipe is None else self.sync_pipe

    def select_async(self) -> AnyModuleWrapper:
        """
        Chooses the callable an asynchronous execution runs.

        Returns:

            The asynchronous pipe, or the synchronous pipe to adapt.

        """
        return self.select_sync() if self.async_pipe is None else self.async_pipe

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
    def loopable(self) -> bool:
        """
        Whether the module runs one item at a time.

        A loopable module gives the same results whether it is called once with the
        whole stream or once per item. Its items may be spread across workers.
        """
        return _has_flag(self.select_async(), "loopable")

    @property
    def sequential_inputs(self) -> bool:
        """
        Whether the module reads its input streams one at a time.

        Its input streams never hold their node threads at the same time.
        """
        return _has_flag(self.select_async(), "sequential_inputs")


_CALLABLE_MODULE = "udf"


def _gen_item_result(
    fn: Callable[..., object],
    item: object = None,
    *,
    context: Context | None = None,
    resources: Mapping[str, object] | None = None,
    **kwargs: FrozenJSON,
) -> Iterator[object]:
    """
    Applies a callable node's ``fn`` to exactly one item, whatever its type.

    The item reaches ``fn`` as is, even a list or an iterator, and the return value is
    the one result, even ``None`` or an iterator. The ``context`` is accepted for the
    prepared call signature but never passed on to ``fn``.
    """
    yield fn(item, **kwargs, **normalize_mapping(resources))


async def _agen_item_result[T](
    fn: Callable[..., T | Awaitable[T]],
    item: object = None,
    *,
    context: Context | None = None,
    resources: Mapping[str, object] | None = None,
    **kwargs: FrozenJSON,
) -> AsyncIterator[T]:
    """The async twin of ``_gen_item_result``: an async ``fn`` is awaited."""
    yield await maybe_async(fn, item, **kwargs, **normalize_mapping(resources))


def _gen_stream_results[T](
    fn: Callable[..., T],
    item: Iterable[object] = (),
    *,
    context: Context | None = None,
    resources: Mapping[str, object] | None = None,
    **kwargs: FrozenJSON,
) -> Iterator[T]:
    """Applies a callable node's ``fn`` to each item of a stream, one result each."""
    call = partial(fn, **kwargs, **normalize_mapping(resources))
    return map(call, item)


async def _agen_stream_results[T](
    fn: Callable[..., T | Awaitable[T]],
    item: AnyIterable[object] = (),
    *,
    context: Context | None = None,
    resources: Mapping[str, object] | None = None,
    **kwargs: FrozenJSON,
) -> AsyncIterator[T]:
    """
    Applies a callable node's ``fn`` to each item of a stream, awaiting an async ``fn``.

    The async twin of ``_gen_stream_results``; the stream may be async or sync.
    """
    call = async_partial(fn, **kwargs, **normalize_mapping(resources))

    async for value in as_async(item):
        yield await call(value)


class PreparedInterface(NamedTuple):
    """
    The pipe a sync or async execution runs for a node, with its call prepared once.

    Attributes:

        pipe: The callable that execution runs.
        call: The pipe with the node's configuration, options, and extras applied.
        item_call: The per-item call the mapped paths run (``call`` for a module node).
        native: Whether ``pipe`` runs natively for the execution, without an adapter.

    """

    pipe: AnyModuleWrapper
    call: PreparedCall
    item_call: PreparedCall
    native: bool


def _resolve_callable(dispatcher: Dispatcher, node: CallableNode) -> ResolvedModule:
    """
    Resolves the module a callable node runs as.

    An async ``fn`` has no synchronous implementation, so synchronous iteration
    bridges it the way it bridges any async-only module.
    """
    module = ResolvedModule.from_dispatcher(dispatcher, _CALLABLE_MODULE)
    return evolve(module, sync_pipe=None) if is_async_callable(node.fn) else module


_build_is_module = partial(validator_from_require, require_instance, ResolvedModule)
_is_optional_module = _build_is_module(optional=True)


@define(frozen=True, slots=True)
class PreparedNode:
    """
    One graph node ready to run: the node, its implementation, and its embed.

    Attributes:

        node: The ``Workflow`` module or callable node this was resolved from.

        module: The node's resolved implementation.

        embed: The resolved module a loop node runs per item, else ``None``.

        incoming: The stream edges that target the node.

        input_ports: The parsed target port of each incoming stream edge.

        extras: The names of the extra inputs delivered with each item: a named
            input stream under its port name, positional streams as ``others``, bound
            resources as ``resources``, and a loop's embed as ``embed``, in that order.

        sync_interface: The pipe a synchronous execution runs, with its call.

        async_interface: The pipe an asynchronous execution runs, with its call.

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
        >>> prepared.extras
        ('part', 'others', 'resources')

    """

    node: RunnableNode = field(converter=require_runnable_node)
    module: ResolvedModule = field(validator=_build_is_module())
    embed: ResolvedModule | None = field(default=None, validator=_is_optional_module)
    incoming: tuple[GraphEdge, ...] = field(default=(), converter=tuple)

    @property
    def resources(self) -> Mapping[str, str]:
        return self.node.resources

    @property
    def options(self) -> CallOptions:
        return self.node.options if isinstance(self.node, ModuleNode) else NO_OPTIONS

    @property
    def embed_or_self_conf(self) -> FrozenConf:
        return self.module.conf if self.embed is None else self.embed.conf

    @property
    def loopable(self) -> bool:
        return self.module.loopable

    @property
    def sequential_inputs(self) -> bool:
        return self.module.sequential_inputs

    @cached_property
    def input_ports(self) -> tuple[ParsedPort, ...]:
        """The parsed target port of each incoming stream edge, in edge order."""
        return tuple(parse_port(edge.target_port) for edge in self.incoming)

    @cached_property
    def extras(self) -> ExtraNames:
        """The names of the extra inputs delivered with each item, in call order."""
        named = gen_non_none(port.name for port in self.input_ports)
        has_others = any(port.is_positional for port in self.input_ports)
        others = ["others"] if has_others else []
        resources = ["resources"] if self.node.resources else []
        has_embed = isinstance(self.node, ModuleNode) and self.node.embed is not None
        embed = ["embed"] if has_embed else []
        return (*named, *others, *resources, *embed)

    @cached_property
    def has_secondary_input_streams(self) -> bool:
        """Whether a stream reaches the node on a port other than its default one."""
        return any(not port.is_default for port in self.input_ports)

    @cached_property
    def is_mappable(self) -> bool:
        """
        Whether the node's items may run one at a time across workers.

        Only a loopable node qualifies, and only when no secondary input stream
        reaches it: such a stream is shared by the whole call and cannot be split
        per item.
        """
        return self.loopable and not self.has_secondary_input_streams

    def is_thread_holder(self, *, mapped: bool) -> bool:
        """
        Reports whether an async run holds a thread while the node reads upstream.

        Only a node without an async implementation does. When items are mapped across
        workers, a loopable node with no secondary input stream instead runs each item
        after it has been read.

        Args:

            mapped: Whether the execution maps loopable nodes' items across workers.

        Returns:

            ``True`` when the node holds a thread while it reads upstream.

        """
        return self.module.async_pipe is None and not (mapped and self.is_mappable)

    def _build_native(self, pipe: AnyModuleWrapper) -> PreparedInterface:
        if isinstance(node := self.node, CallableNode):
            if self.module.is_async_pipe(pipe):
                stream, one = _agen_stream_results, _agen_item_result
            else:
                stream, one = _gen_stream_results, _gen_item_result

            call = cast("PreparedCall", partial(stream, node.fn, **node.kwargs))
            item_call = cast("PreparedCall", partial(one, node.fn, **node.kwargs))
        else:
            conf, options = self.embed_or_self_conf, self.options.kwargs
            call = item_call = build_call(pipe, *self.extras, conf=conf, **options)

        return PreparedInterface(pipe, call, item_call, native=True)

    @cached_property
    def sync_interface(self) -> PreparedInterface:
        """
        The pipe a synchronous execution runs, with its call prepared once.

        It is the synchronous pipe when the module has one, else the asynchronous
        pipe for the execution to adapt.
        """
        if (pipe := self.module.sync_pipe) is None:
            interface = self.async_interface._replace(native=False)
        else:
            interface = self._build_native(pipe)

        return interface

    @cached_property
    def async_interface(self) -> PreparedInterface:
        """
        The pipe an asynchronous execution runs, with its call prepared once.

        It is the asynchronous pipe when the module has one, else the synchronous
        pipe for the execution to adapt.
        """
        if (pipe := self.module.async_pipe) is None:
            interface = self.sync_interface._replace(native=False)
        else:
            interface = self._build_native(pipe)

        return interface

    @cached_property
    def is_sync_mappable(self) -> bool:
        """
        Whether a synchronous run may map the node's items across workers.

        Only a mappable node with a native synchronous pipe qualifies. An adapted
        asynchronous pipe streams its whole input in one call.
        """
        return self.is_mappable and self.sync_interface.native


_rmodule_freezer = instances_freezer(ResolvedModule, "ExecutionPlan module")
_modules_converter = mapping_converter(
    _rmodule_freezer, ResolvedModulesInput, what="ExecutionPlan 'modules'"
)
_EMPTY_EMBEDS: ResolvedModules = FrozenDict()
_embeds_converter = optional_mapping_converter(
    _rmodule_freezer, ResolvedModulesInput, what="ExecutionPlan 'embeds'"
)
_require_workflow = narrow_from_require(
    require_instance, Workflow, what="ExecutionPlan 'workflow'"
)


def require_default_output_port(port: str, ref: str) -> None:
    """
    Rejects a non-default output port until multi-output delivery is executable.

    Only the bare ``out`` port is executable today. A positional ``out:N`` or
    semantic ``out:<name>`` source or selected workflow output is refused rather than
    silently read as the node's default ``out`` stream.

    Args:

        port: The source or selected workflow output's port string to check.
        ref: A human-readable reference to the offending edge or workflow output.

    Raises:

        InvalidPipelineError: If ``port`` is not the default ``out`` port.

    """
    if not parse_port(port).is_default:
        msg = f"{ref} uses the non-default output port {port!r}, which cannot run yet."
        raise InvalidPipelineError(msg)


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
            invalid, a source port fans out to more than one edge, a node is neither a
            module node nor a callable node, ``modules`` does not resolve exactly the
            workflow's nodes, or ``embeds`` does not resolve exactly its loop embeds.

    Examples:

        >>> from riko import Endpoint, Workflow
        >>> from riko.ext import ModuleNode
        >>> from riko.modules.hash import pipe
        >>>
        >>> flow = Workflow(
        ...     nodes=[ModuleNode(id="a", name="hash")],
        ...     outputs={"default": Endpoint("a", "out")},
        ... )
        >>> modules = {"a": ResolvedModule("hash", sync_pipe=pipe)}
        >>> plan = ExecutionPlan(workflow=flow, modules=modules)
        >>> plan.nodes["a"].node
        ModuleNode(id='a', name='hash', resources=FrozenDict({})...)
        >>> plan.index.order
        ('a',)

    """

    workflow: Workflow = field(converter=_require_workflow)
    modules: ResolvedModules = field(converter=_modules_converter)
    embeds: ResolvedModules = field(default=_EMPTY_EMBEDS, converter=_embeds_converter)

    def __attrs_post_init__(self) -> None:
        self.validate()

    @classmethod
    def from_workflow(cls, flow: Workflow, dispatcher: Dispatcher) -> Self:
        """
        Builds an executable snapshot of ``flow`` with every node resolved once.

        Args:

            flow: The ``Workflow`` to prepare.

            dispatcher: Finds each node's pipe by name, whether a module such as
                ``fetch`` or a stored workflow's ``pipe_<id>``.

        Returns:

            The prepared plan: its graph index and resolved nodes. No node runs and
            no resource is acquired here.

        Raises:

            InvalidPipelineError: If the graph is invalid, a source port fans out to
                more than one edge, a node isn't a module or callable node (write,
                action, cache, or subscribe), or a node runs a multi-output splitter.

            UnsupportedModuleError: If no module has the name a node gives.

            UnsupportedWorkflowError: If no stored workflow has the ``pipe_<id>`` name
                a node gives.

        Examples:

            >>> from riko import Endpoint, Workflow
            >>> from riko.ext import ModuleNode
            >>> from riko.runtime._resolver import dispatcher
            >>>
            >>> flow = Workflow(
            ...     nodes=[ModuleNode(id="count-1", name="count")],
            ...     outputs={"default": Endpoint("count-1", "out")},
            ... )
            >>> plan = ExecutionPlan.from_workflow(flow, dispatcher)
            >>> sorted(plan.nodes)
            ['count-1']

        """
        resolve = partial(ResolvedModule.from_dispatcher, dispatcher)
        resolve_callable = partial(_resolve_callable, dispatcher)
        modules = {k: resolve(n.name, n.conf) for k, n in flow.module_nodes.items()}
        embeds = {k: resolve(e["name"], e["conf"]) for k, e in flow.embeds.items()}
        callables = map_values(resolve_callable, flow.callable_nodes)
        return cls(flow, {**modules, **callables}, embeds)

    @property
    def index(self) -> GraphIndex:
        """The workflow's graph index, including each workflow output's subgraph."""
        return self.workflow.index

    @cached_property
    def nodes(self) -> PreparedNodes:
        """Each workflow node paired with its resolved module and embed."""
        embeds, modules, incoming = self.embeds, self.modules, self.index.incoming
        pairs = self.workflow.runnable_nodes.items()
        prepared = {
            k: PreparedNode(n, modules[k], embeds.get(k), incoming.get(k, ()))
            for k, n in pairs
        }
        return FrozenDict.from_frozen(prepared)

    def require_output(self, output: str) -> Endpoint:
        """
        Requires a default-port workflow output.

        Args:

            output: The name of the workflow output to run.

        Returns:

            The output's endpoint.

        Raises:

            InvalidPipelineError: If the plan exposes no such workflow output, or it
                reads a non-default output port.

        """
        if (endpoint := self.index.outputs.get(output)) is None:
            raise InvalidPipelineError(f"workflow has no workflow output {output!r}")

        require_default_output_port(endpoint.port, f"workflow output {output!r}")
        return endpoint

    def get_thread_demand(self, output: str, *, mapped: bool) -> int:
        """
        Computes how many node threads an async run of ``output`` may hold at once.

        A node without an async implementation holds a thread while it reads its input
        streams. Unless its items are mapped, it reads them one at a time and needs one
        thread more than the max number of threads any one of its input streams holds.

        Nodes with a module that reads its input streams one at a time, such as
        ``union`` or ``join``, need only the max any one input stream holds.
        Otherwise a node may read its input streams together, so it needs as many
        threads as the sum of its input streams.

        Args:

            output: The name of the workflow output being run.
            mapped: Whether the execution maps loopable nodes' items across workers.

        Returns:

            The most node threads held at once while the workflow output is read.

        Examples:

            >>> from riko import Endpoint, Workflow
            >>> from riko.ext import ModuleNode, StreamEdge
            >>> from riko.modules.hash import pipe
            >>>
            >>> a, b = ModuleNode(id="a", name="hash"), ModuleNode(id="b", name="hash")
            >>> flow = Workflow(
            ...     nodes=[a, b],
            ...     edges=[StreamEdge(Endpoint("a", "out"), Endpoint("b", "in"))],
            ...     outputs={"default": Endpoint("b", "out")},
            ... )
            >>> module = ResolvedModule("hash", sync_pipe=pipe)
            >>> plan = ExecutionPlan(workflow=flow, modules={"a": module, "b": module})
            >>> plan.get_thread_demand("default", mapped=False)
            2
            >>> plan.get_thread_demand("default", mapped=True)
            0

        """
        demand: dict[str, int] = {}

        for node_id in self.index.required[output]:
            upstream = [demand[source] for source in self.index.upstream[node_id]]
            node = self.nodes[node_id]
            max_count = max(upstream, default=0)

            if node.is_thread_holder(mapped=mapped):
                demand[node_id] = max_count + 1
            elif node.sequential_inputs:
                demand[node_id] = max_count
            else:
                demand[node_id] = sum(upstream)

        return max(demand.values(), default=0)

    def require_seed_target(self, output: str) -> str:
        """
        Requires the one node ``output`` runs whose default input is open to a seed.

        A node's default input is open when every stream edge reaching it, if any,
        targets a positional ``in:<n>`` port. An edge into its default port or a named
        ``in:<name>`` port closes it. A seed needs exactly one open node.

        Args:

            output: The name of the workflow output being run.

        Returns:

            The id of the single node whose default input a supplied seed feeds.

        Raises:

            InvalidPipelineError: If the output's subgraph has no single open input.

        """
        open_roots = list(filter(self.index.is_open, self.index.required[output]))

        if (count := len(open_roots)) == 1:
            target = open_roots[0]
        else:
            msg = f"a seed requires exactly one open input, found {count}"
            raise InvalidPipelineError(msg)

        return target

    def gen_build_order[V](
        self, output: str, *, seed: V | None = None
    ) -> Iterator[tuple[str, V | None]]:
        """
        Pairs each node ``output`` runs, in build order, with the seed it takes.

        Args:

            output: The name of the workflow output being run.
            seed: The seed stream for the workflow output's open input, if any.

        Yields:

            Each node id the output runs paired with the seed it takes, or ``None``.

        Raises:

            InvalidPipelineError: If a seed is given and the output's subgraph has no
                single open input.

        """
        seed_target = None if seed is None else self.require_seed_target(output)

        for node_id in self.index.required[output]:
            yield node_id, seed if node_id == seed_target else None

    def validate(self) -> None:
        """
        Validates that the workflow is runnable and the plan resolves exactly its nodes.

        Raises:

            InvalidPipelineError: If the graph is invalid, a source port fans out to
                more than one edge, a workflow node is neither a module node nor a
                callable node, ``modules`` does not resolve the workflow's nodes, or
                ``embeds`` does not resolve its loop embeds.

        """
        flow = self.workflow

        if not flow.is_empty:
            flow.validate()

        flow.require_executable()
        flow.require_runnable_only("execution")

        if unresolved := set(flow.runnable_nodes).symmetric_difference(self.modules):
            msg = f"modules must match the workflow's nodes: {sorted(unresolved)}"
            raise InvalidPipelineError(msg)
        elif mismatched := set(flow.embeds).symmetric_difference(self.embeds):
            msg = f"embeds must match the workflow's loop embeds: {sorted(mismatched)}"
            raise InvalidPipelineError(msg)


__all__ = ["ExecutionPlan", "PreparedInterface", "PreparedNode", "ResolvedModule"]
