# vim: sw=4:ts=4:expandtab
"""
Builds a ``Workflow``'s immutable execution plan via ``ExecutionPlan.from_workflow``.

The plan carries each node's pipe, found by name (a module such as ``fetch``, or a
stored workflow's ``pipe_<id>``). Building it runs no node and acquires no resources,
and the sync/async executions run it without re-inspecting the ``Workflow``,
dispatcher, or registry.
"""

from __future__ import annotations

from collections import Counter
from functools import cached_property, partial
from inspect import Parameter, signature
from itertools import chain, islice
from operator import attrgetter
from typing import TYPE_CHECKING, ClassVar, Self

from attrs import asdict, define, evolve, field, fields_dict

from riko.bado._util import async_partial
from riko.bado.itertools import as_async
from riko.base._config import DEFAULT_OUTPUT
from riko.base._exceptions import InvalidPipelineError
from riko.base._funcutils import map_values, resolve_default
from riko.base._guards import is_async_callable, require_value
from riko.base._iterutils import gen_nested_mappings, gen_non_null
from riko.base._require_guards import (
    def_from_require,
    narrow_from_require,
    require_instance,
    require_non_null,
    require_str,
    typed_dict_keys,
    validator_from_require,
)
from riko.base._sentinels import SentinelValue
from riko.base._strutils import replacer
from riko.base._typing import require_enum
from riko.definitions._inputs import (
    freeze_inputs,
    gen_input_references,
    resolve_input_references,
)
from riko.definitions._nodes import (
    FROZEN_CONF,
    NO_OPTIONS,
    CallableNode,
    ModuleNode,
    conf_converter,
    gen_positional_names,
    require_runnable_node,
)
from riko.definitions._workflow_definition import Inputs, Workflow
from riko.definitions._wrapping import build_call
from riko.types._enums import IdentityMode
from riko.types._frozendict import (
    FrozenConf,
    FrozenDict,
    FrozenInputs,
    JSONValue,
    instances_freezer,
    json_freeze,
    mapping_converter,
    normalize_mapping,
    optional_mapping_converter,
)
from riko.types._options import RawCallOptions
from riko.types._workflow import OUT, PortKey, is_input_ref, parse_port
from riko.types._wrappers import (
    PARSER_POSITIONALS,
    DeclaresIdentity,
    Func,
    NodeCall,
    NormalizesItems,
    is_splitter,
)

if TYPE_CHECKING:
    from collections.abc import (
        AsyncIterator,
        Awaitable,
        Callable,
        Iterable,
        Iterator,
        Mapping,
        Sequence,
    )

    from riko.definitions._context import Context
    from riko.definitions._nodes import ConfInput, RunnableNode
    from riko.types._frozendict import FrozenJSON, FrozenWorkflowEdges
    from riko.types._options import CallOptions
    from riko.types._streams import (
        AnyIterable,
        AsyncCascade,
        AsyncStreamOf,
        Cascade,
        StreamOf,
    )
    from riko.types._workflow import (
        Endpoint,
        NodeId,
        OutputName,
        ParsedPort,
        Port,
        PortName,
        ResourceName,
        WorkflowIndex,
    )
    from riko.types._wrappers import (
        AnyModuleWrapper,
        AsyncModuleWrapper,
        Dispatcher,
        ExtraNames,
        ModuleWrapper,
        SyncModuleWrapper,
    )

    from ._resource_view import ResourceView

type AnyPreparedNode = PreparedNode | PreparedSplitter
type PreparedNodes = FrozenDict[NodeId, AnyPreparedNode]
type ResolvedModules = FrozenDict[NodeId, ResolvedModule]
type ResolvedModulesInput = Mapping[NodeId, ResolvedModule]

_MODULE_ATTRS = ("type", "subtype", "identity")
_MODULE_FLAGS = ("loopable", "sequential_inputs")
_DEFAULT_SPLITS = 2
_normalize_identity = def_from_require(
    require_enum, IdentityMode, what="module 'identity'"
)
_CALLABLE_MODULE = "udf"
_REFERENCE_KEYS = ("subkey", SentinelValue)
_VALUE_SOURCE_MODULES = frozenset({"strconcat"})
_KEYWORD_KINDS = frozenset({Parameter.POSITIONAL_OR_KEYWORD, Parameter.KEYWORD_ONLY})
_EMPTY_EMBEDS: ResolvedModules = FrozenDict()
_NO_INPUTS: FrozenInputs = FrozenDict()

# Operators keep ``count`` as a port: stored workflows wire a count stream into
# ``in:count`` on ``truncate``/``tail``. A processor's parser receives the ``count``
# option instead, so a processor reserves it.
_CALL_OPTION_NAMES = frozenset().union(*typed_dict_keys(RawCallOptions)) - {"count"}

_AWAITABLE_RESULT = (
    "a map function returned an awaitable; iterate with `async for` to await it"
)

NO_PIPE_MSG = "{0!r} has neither a sync nor an async callable"


def _convert_others(arg: Iterable[object] | None) -> Sequence[object] | None:
    return tuple(arg) if arg else None


@define(frozen=True, slots=True, kw_only=True)
class ExecutionExtras[V]:
    """
    The keyword arguments an execution adds to a node's call.

    They sit beside the node's named input streams. No input port may share a field's
    name; the ``item`` argument's; or the ``emit``, ``assign``, or ``field`` call
    options.

    Attributes:

        others: The streams wired to the node's positional input ports.
        resources: The Context resources bound to the node.
        embed: The loop node's callable selected for the loop pipe's mode.

    Examples:

        >>> extras = ExecutionExtras(others=[[1]])
        >>> list(extras.kwargs)
        ['others']

    """

    others: Sequence[V] | None = field(converter=_convert_others)
    resources: ResourceView | None = None
    embed: ModuleWrapper | None = None

    @staticmethod
    def _get_delivered(node: RunnableNode, *ports: ParsedPort) -> dict[str, bool]:
        return {
            "others": any(map(attrgetter("is_positional"), ports)),
            "resources": bool(node.resources),
            "embed": isinstance(node, ModuleNode) and node.embed is not None,
        }

    @classmethod
    def get_names(cls, node: RunnableNode, *ports: ParsedPort) -> tuple[str, ...]:
        """
        Gets the names of the fields an execution delivers to ``node``, in field order.

        Args:

            node: The node the execution calls.
            ports: The node's input ports.

        Returns:

            The delivered field names.

        """
        names = fields_dict(cls)
        delivered = cls._get_delivered(node, *ports)
        return tuple(filter(delivered.get, names))

    @property
    def kwargs(self) -> dict[str, Sequence[V] | ResourceView | ModuleWrapper]:
        """The fields that are set, keyed by name."""
        return asdict(self, recurse=False, filter=lambda _, value: value is not None)

    def map_kwargs(
        self, func: Callable[[V], object], named: Mapping[PortName, V]
    ) -> dict[str, object]:
        """
        Maps ``func`` over a node's secondary input streams to build its call's kwargs.

        Args:

            func: Applied to each ``named`` stream and each ``others`` stream.
            named: The streams wired to the node's named input ports.

        Returns:

            The node's call kwargs: each ``named`` and ``others`` stream with ``func``
            applied, plus ``resources`` and ``embed`` when they are set.

        Examples:

            >>> extras = ExecutionExtras(others=[[1], [2]])
            >>> extras.map_kwargs(len, {"other": [3, 4]})
            {'other': 2, 'others': (1, 1)}

        """
        others = None if self.others is None else map(func, self.others)
        mapped = ExecutionExtras(
            others=others, resources=self.resources, embed=self.embed
        )
        return {**map_values(func, named), **mapped.kwargs}


def _get_keyword_names(*funcs: Func[object]) -> frozenset[str]:
    """Gets the names ``funcs`` accept by keyword, after each one's first parameter."""
    _params = (islice(signature(f).parameters.values(), 1, None) for f in funcs)
    params = chain.from_iterable(_params)
    return frozenset(p.name for p in params if p.kind in _KEYWORD_KINDS)


_RESERVED_INPUTS = frozenset(
    {"item", *fields_dict(ExecutionExtras), *_CALL_OPTION_NAMES}
) | _get_keyword_names(NodeCall.__call__, build_call)

_PROCESSOR_RESERVED_INPUTS = _RESERVED_INPUTS | {"count"}
_rmodule_conf_converter = conf_converter(what="ModuleNode 'conf'")


def _get_count(func: Func[object] | None) -> int:
    """Gets how many leading parameters ``func``'s call fills by position."""
    return 1 if getattr(func, "__wrapped__", None) is None else PARSER_POSITIONALS


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
        raise InvalidPipelineError(NO_PIPE_MSG.format(instance.name))


def _has_flag(pipe: AnyModuleWrapper, flag: str) -> bool:
    return getattr(pipe, flag, False) is True


def _has_flag_mismatch(
    sync_pipe: SyncModuleWrapper, async_pipe: AsyncModuleWrapper, flag: str
) -> bool:
    return _has_flag(sync_pipe, flag) != _has_flag(async_pipe, flag)


def _has_attr_mismatch(
    sync_pipe: SyncModuleWrapper, async_pipe: AsyncModuleWrapper, attr: str
) -> bool:
    return getattr(sync_pipe, attr, None) != getattr(async_pipe, attr, None)


def _is_consistent(
    instance: ResolvedModule, _: object, value: AsyncModuleWrapper | None
) -> None:
    if (sync_pipe := instance.sync_pipe) is not None and value is not None:
        _diff = partial(_has_flag_mismatch, sync_pipe, value)
        _attr_diff = partial(_has_attr_mismatch, sync_pipe, value)

        flags = tuple(filter(_diff, _MODULE_FLAGS))
        attrs = tuple(filter(_attr_diff, _MODULE_ATTRS))
        splitter = is_splitter(sync_pipe) != is_splitter(value)
        named = (*flags, *attrs)

        if differing := (*named, "splitter") if splitter else named:
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

        InvalidPipelineError: If neither callable is given or one callable fills both
            slots; or if the two callables disagree on whether the module is loopable,
            reads its input streams one at a time, is a splitter, or in its attributes
            (type, subtype, or identity mode).

    Examples:

        >>> from riko.runtime._resolver import dispatcher
        >>>
        >>> pipe = dispatcher.require("hash")
        >>> module = ResolvedModule("hash", {}, sync_pipe=pipe)
        >>> module.sync_pipe is pipe
        True
        >>> module.async_pipe

    """

    name: str = field(converter=require_str)
    conf: FrozenConf = field(default=FROZEN_CONF, converter=_rmodule_conf_converter)
    sync_pipe: SyncModuleWrapper | None = None
    async_pipe: AsyncModuleWrapper | None = field(
        default=None, validator=[_is_distinct, _has_pipe, _is_consistent]
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

        Kwargs:

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

    @cached_property
    def _positional_names(self) -> frozenset[str]:
        """The parameter names either pipe's call fills by position."""
        pipes = (self.sync_pipe, self.async_pipe)
        counts = map(_get_count, pipes)
        positional_names = map(gen_positional_names, pipes, counts)
        return frozenset().union(*positional_names)

    @property
    def _metadata_pipe(self) -> AnyModuleWrapper:
        """The pipe reported by the module metadata (async if the module has both)."""
        pipes = (self.async_pipe, self.sync_pipe)
        pipe = next((pipe for pipe in pipes if pipe is not None), None)
        return require_non_null(pipe, NO_PIPE_MSG, self.name)

    @property
    def loopable(self) -> bool:
        """
        Whether the module runs one item at a time.

        A loopable module gives the same results whether it is called once with the
        whole stream or once per item. Its items may be spread across workers.
        """
        return _has_flag(self._metadata_pipe, "loopable")

    @property
    def identity(self) -> IdentityMode | None:
        """
        How each of the module's per-item results relates to its input item.

        Read from the pipe's ``identity`` attribute, declared beside ``loopable``.
        ``None`` when the pipe declares none, so a per-item result derives a new
        identity.

        Raises:

            InvalidPipelineError: If the declared value is not an ``IdentityMode``.

        """
        return _normalize_identity(getattr(self._metadata_pipe, "identity", None))

    @property
    def sequential_inputs(self) -> bool:
        """
        Whether the module reads its input streams one at a time.

        Its input streams never hold their node threads at the same time.
        """
        return _has_flag(self._metadata_pipe, "sequential_inputs")

    @property
    def is_processor(self) -> bool:
        """Whether the module runs its parser once per item (a processor module)."""
        return getattr(self._metadata_pipe, "type", None) == "processor"

    @property
    def is_splitter(self) -> bool:
        """Whether the module splits its input into several streams (a splitter)."""
        return is_splitter(self._metadata_pipe)

    @property
    def is_source(self) -> bool:
        """
        Whether the module creates items on its own and needs no input stream.

        A module without a declared subtype is not a source.
        """
        return getattr(self._metadata_pipe, "subtype", None) == "source"


def _gen_references(value: FrozenJSON | FrozenConf) -> Iterator[tuple[str, str]]:
    """``subkey``/``terminal`` references."""
    for mapping in gen_nested_mappings(value):
        pairs = ((key, mapping.get(key)) for key in _REFERENCE_KEYS)
        yield from (
            (key, ref) for key, ref in pairs if isinstance(ref, str) and ref != ""
        )


def _gen_item_result(
    fn: Func[object],
    /,
    item: object = None,
    context: Context | None = None,
    *,
    resources: Mapping[str, object] | None = None,
    **kwargs: FrozenJSON,
) -> Iterator[object]:
    """
    Applies a callable node's ``fn`` to exactly one item, whatever its type.

    The item reaches ``fn`` as is, even a list or an iterator, and the return value is
    the one result, even ``None`` or an iterator. The ``context`` is accepted for the
    prepared call signature but never passed on to ``fn``.
    """
    result = fn(item, **kwargs, **normalize_mapping(resources))
    yield require_value(result, _AWAITABLE_RESULT)


async def _agen_item_result[T](
    fn: Func[T | Awaitable[T]],
    /,
    item: object = None,
    context: Context | None = None,
    *,
    resources: Mapping[str, object] | None = None,
    **kwargs: FrozenJSON,
) -> AsyncStreamOf[T]:
    """The async twin of ``_gen_item_result``: an async ``fn`` is awaited."""
    call = async_partial(fn, **kwargs, **normalize_mapping(resources))
    yield await call(item)


def _gen_stream_results[T](
    fn: Func[T | Awaitable[T]],
    items: Iterable[object] = (),
    context: Context | None = None,
    /,
    *,
    resources: Mapping[str, object] | None = None,
    **kwargs: FrozenJSON,
) -> Iterator[T]:
    """Applies a callable node's ``fn`` to each item of a stream, one result each."""
    options = dict(**kwargs, **normalize_mapping(resources))
    return (require_value(fn(item, **options), _AWAITABLE_RESULT) for item in items)


async def _agen_stream_results[T](
    fn: Func[T | Awaitable[T]],
    item: AnyIterable[object] = (),
    context: Context | None = None,
    /,
    *,
    resources: Mapping[str, object] | None = None,
    **kwargs: FrozenJSON,
) -> AsyncStreamOf[T]:
    """
    Applies a callable node's ``fn`` to each item of a stream, awaiting an async ``fn``.

    The async twin of ``_gen_stream_results``; the stream may be async or sync.
    """
    call = async_partial(fn, **kwargs, **normalize_mapping(resources))

    async for value in as_async(item):
        yield await call(value)


@define(frozen=True, slots=True)
class SyncInterface[O]:
    """
    The synchronous pipe an execution runs for a node and its prepared call.

    A synchronous execution runs it natively, and an asynchronous execution adapts it.

    Attributes:

        pipe: The synchronous callable.
        call: The pipe with the node's configuration, options, and extras applied.
        item_call: The per-item call the mapped paths run (``call`` for a module node).
        identity: How each result's identity relates to its input items.
        item_normalizer: The function the pipe applies to each input item.

    Examples:

        >>> from riko.ext import ModuleNode
        >>> from riko.runtime._resolver import dispatcher
        >>>
        >>> pipe = dispatcher.require("hash")
        >>> module = ResolvedModule("hash", sync_pipe=pipe)
        >>> prepared = PreparedNode(ModuleNode(id="h", name="hash"), module)
        >>> isinstance(prepared.sync_interface, SyncInterface)
        True

    """

    pipe: SyncModuleWrapper
    call: NodeCall[O]
    item_call: NodeCall[O]
    identity: IdentityMode | None
    item_normalizer: Func[object] | None = None


@define(frozen=True, slots=True)
class AsyncInterface[O]:
    """
    The asynchronous pipe an execution runs for a node and its prepared call.

    An asynchronous execution runs it natively, and a synchronous execution adapts it.

    Attributes:

        pipe: The asynchronous callable.
        call: The pipe with the node's configuration, options, and extras applied.
        item_call: The per-item call mapped paths run (``call`` for a module node).
        identity: How each result's identity relates to its input items.
        item_normalizer: The function the pipe applies to each input item.

    Examples:

        >>> from riko.ext import ModuleNode
        >>> from riko.runtime._resolver import dispatcher
        >>>
        >>> async_pipe = dispatcher.require("hash", is_async=True)
        >>> module = ResolvedModule("hash", async_pipe=async_pipe)
        >>> prepared = PreparedNode(ModuleNode(id="h", name="hash"), module)
        >>> interface = prepared.async_interface
        >>> isinstance(interface, AsyncInterface)
        True

    """

    pipe: AsyncModuleWrapper
    call: NodeCall[O]
    item_call: NodeCall[O]
    identity: IdentityMode | None
    item_normalizer: Func[object] | None = None


def _resolve_callable[T](
    dispatcher: Dispatcher, node: CallableNode[T]
) -> ResolvedModule:
    """
    Resolves the module a callable node runs as.

    An async ``fn`` has no synchronous implementation, so synchronous iteration bridges
    it the way it bridges any async-only module. The node's keyword arguments are the
    module's configuration, so their input references resolve like a module node's.
    """
    module = ResolvedModule.from_dispatcher(dispatcher, _CALLABLE_MODULE, node.kwargs)
    return evolve(module, sync_pipe=None) if is_async_callable(node.fn) else module


def _parse_splits(value: FrozenJSON | None) -> int:
    """Parses a splitter's ``splits`` conf value."""
    if value is None:
        splits = _DEFAULT_SPLITS
    elif isinstance(value, int) and not isinstance(value, bool):
        splits = value
    elif isinstance(value, str) and value.strip().lstrip("-").isdigit():
        splits = int(value)
    else:
        raise InvalidPipelineError(f"a split count must be an integer, got {value!r}")

    return splits


_build_is_module = partial(validator_from_require, require_instance, ResolvedModule)
_is_optional_module = _build_is_module(optional=True)


@define(frozen=True, slots=True)
class _PreparedBase:
    """
    What every graph node ready to run shares: the node, its module, and its inputs.

    Attributes:

        node: The ``Workflow`` module or callable node this was resolved from.
        module: The node's resolved implementation.
        incoming: The stream edges that target the node.

    """

    node: RunnableNode = field(converter=require_runnable_node)
    module: ResolvedModule = field(validator=_build_is_module())
    incoming: FrozenWorkflowEdges = field(default=(), converter=tuple)

    @property
    def resources(self) -> Mapping[str, ResourceName]:
        return self.node.resources

    @property
    def options(self) -> CallOptions:
        return self.node.options if isinstance(self.node, ModuleNode) else NO_OPTIONS

    @property
    def sequential_inputs(self) -> bool:
        return self.module.sequential_inputs

    @property
    def is_source(self) -> bool:
        """Whether the node's module creates items on its own; a callable never does."""
        return self.module.is_source

    @property
    def is_builtin(self) -> bool:
        """Whether every pipe the node runs comes from riko's own module of its name."""
        name = self.module.name
        pipes = gen_non_null((self.module.sync_pipe, self.module.async_pipe))

        return all(
            getattr(pipe, "__module__", None) == f"riko.modules.{name}"
            for pipe in pipes
        )

    @cached_property
    def input_ports(self) -> tuple[ParsedPort, ...]:
        """The parsed target port of each incoming stream edge, in edge order."""
        return tuple(parse_port(edge.target_port) for edge in self.incoming)

    @cached_property
    def is_self_starting(self) -> bool:
        """
        Whether the node runs without a seed.

        Only a source module or a built-in ``strconcat`` may, and only when their conf
        reads nothing from the default input. That means it has no ``subkey`` reference,
        and each ``terminal`` reference names a connected named input port. An empty
        ``subkey`` or ``terminal`` counts as unset.
        """
        is_self_starting, is_builtin = False, self.is_builtin

        if self.is_source or (is_builtin and self.module.name in _VALUE_SOURCE_MODULES):
            items = self.input_ports
            connected = set(gen_non_null(items, cmp_attr="name", arg_attr="name"))
            references = _gen_references(self.module.conf)

            is_self_starting = all(
                key == SentinelValue and replacer(name, "") in connected
                for key, name in references
            )

        return is_self_starting

    @cached_property
    def takes_default_seed(self) -> bool:
        """
        Whether an unseeded run feeds the default seed to the node's default input.

        True when no stream edge reaches the node's default or positional ports.
        """
        ports = self.input_ports
        return not any(port.is_default or port.is_positional for port in ports)

    @cached_property
    def extras(self) -> ExtraNames:
        """The names of the extra inputs delivered with each item, in call order."""
        named = gen_non_null(port.name for port in self.input_ports)
        delivered = ExecutionExtras.get_names(self.node, *self.input_ports)
        return (*named, *delivered)

    @cached_property
    def has_secondary_input_streams(self) -> bool:
        """Whether a stream reaches the node on a port other than its default one."""
        return any(not port.is_default for port in self.input_ports)


@define(frozen=True, slots=True)
class PreparedNode(_PreparedBase):
    """
    One graph node ready to run: the node with its implementation and embed.

    The node produces one output stream on its ``out`` port.

    Attributes:

        node: The ``Workflow`` module or callable node this was resolved from.
        module: The node's resolved implementation.
        incoming: The stream edges that target the node.
        embed: The loop node's sync and async callables.
        input_ports: The parsed target port of each incoming stream edge.
        sync_interface: The synchronous pipe with its call.
        async_interface: The asynchronous pipe with its call.

        extras: The names of the extra call inputs delivered with each item:

            - [PORT NAME]: a named input stream
            - others: positional streams
            - resources: bound resources
            - embed: the callable selected for the loop pipe's mode

    Examples:

        >>> from riko.ext import ModuleNode
        >>> from riko.runtime._resolver import dispatcher
        >>> from riko.types._workflow import WorkflowEdge
        >>>
        >>> node = ModuleNode(id="n", name="strconcat", resources="db")
        >>> named = WorkflowEdge("a", "n", "out", "in:part")
        >>> positional = WorkflowEdge("b", "n", "out", "in:1")
        >>> pipe = dispatcher.require("strconcat")
        >>>
        >>> module = ResolvedModule("strconcat", sync_pipe=pipe)
        >>> prepared = PreparedNode(node, module, incoming=(named, positional))
        >>> prepared.node.id
        'n'
        >>> dict(prepared.resources)
        {'db': 'db'}
        >>> prepared.extras
        ('part', 'others', 'resources')
        >>> prepared.is_self_starting
        True
        >>> prepared.output_ports
        ('out',)

    """

    output_ports: ClassVar[tuple[Port, ...]] = (OUT,)
    embed: ResolvedModule | None = field(default=None, validator=_is_optional_module)

    @property
    def embed_or_self_conf(self) -> FrozenConf:
        return self.module.conf if self.embed is None else self.embed.conf

    @property
    def loopable(self) -> bool:
        return self.module.loopable

    @cached_property
    def is_mappable(self) -> bool:
        """
        Whether the node's items may run one at a time across workers.

        Only a loopable node qualifies, and only when no secondary input stream
        reaches it: such a stream is shared by the whole call and cannot be split
        per item.
        """
        return self.loopable and not self.has_secondary_input_streams

    @cached_property
    def is_thread_holder(self) -> bool:
        """
        Whether an async run holds a thread while the node reads upstream.

        Only a node without an async implementation does, and only when it reads its
        whole input in one call. A mappable node runs each item after reading it.
        """
        return self.module.async_pipe is None and not self.is_mappable

    def _get_identity(self, prepared: object) -> IdentityMode | None:
        declared = prepared.identity if isinstance(prepared, DeclaresIdentity) else None
        return self.module.identity if declared is None else declared

    def _build_sync_interface(
        self, pipe: SyncModuleWrapper
    ) -> SyncInterface[Iterator[object]]:
        normalizer = None
        call: NodeCall[Iterator[object]]
        item_call: NodeCall[Iterator[object]]

        if isinstance(node := self.node, CallableNode):
            conf = self.module.conf
            stream_args = (_gen_stream_results, node.fn)
            item_args = (_gen_item_result, node.fn)

            # partials, not closures because it is sent to the process pool
            call = partial(*stream_args, **conf)
            item_call = partial(*item_args, **conf)
            identity = IdentityMode.PRESERVE if node.identity is None else node.identity
        else:
            conf, options = self.embed_or_self_conf, self.options.kwargs
            call = item_call = build_call(pipe, *self.extras, conf=conf, **options)
            identity = self._get_identity(call)

            if isinstance(call, NormalizesItems):
                normalizer = call.normalize_item

        return SyncInterface(pipe, call, item_call, identity, normalizer)

    @cached_property
    def sync_interface(self) -> SyncInterface[Iterator[object]] | None:
        """The synchronous pipe with its prepared call."""
        pipe = self.module.sync_pipe
        return None if pipe is None else self._build_sync_interface(pipe)

    def _build_async_interface(
        self, pipe: AsyncModuleWrapper
    ) -> AsyncInterface[AsyncIterator[object]]:
        normalizer = None
        call: NodeCall[AsyncIterator[object]]
        item_call: NodeCall[AsyncIterator[object]]

        if isinstance(node := self.node, CallableNode):
            conf = self.module.conf
            stream_args = (_agen_stream_results, node.fn)
            item_args = (_agen_item_result, node.fn)

            # partials, not closures because it is sent to the process pool
            call = partial(*stream_args, **conf)
            item_call = partial(*item_args, **conf)
            identity = IdentityMode.PRESERVE if node.identity is None else node.identity
        else:
            conf, options = self.embed_or_self_conf, self.options.kwargs
            call = item_call = build_call(pipe, *self.extras, conf=conf, **options)
            identity = self._get_identity(call)

            if isinstance(call, NormalizesItems):
                normalizer = call.normalize_item

        return AsyncInterface(pipe, call, item_call, identity, normalizer)

    @cached_property
    def async_interface(self) -> AsyncInterface[AsyncIterator[object]] | None:
        """The asynchronous pipe with its prepared call."""
        pipe = self.module.async_pipe
        return None if pipe is None else self._build_async_interface(pipe)

    @property
    def sync_map_interface(self) -> SyncInterface[Iterator[object]] | None:
        """
        The synchronous interface a run maps across workers, or ``None`` if it can't.

        Only a mappable node with a synchronous pipe qualifies. An adapted asynchronous
        pipe streams its whole input in one call.
        """
        return self.sync_interface if self.is_mappable else None


@define(frozen=True, slots=True)
class PreparedSplitter(_PreparedBase):
    """
    One splitter node ready to run: it splits its input stream into several streams.

    Each stream is one output port: ``out`` for the first, then ``out:1``, ``out:2``,
    and so on. Each stream item keeps its input item's identity.

    Attributes:

        node: The ``Workflow`` module node this was resolved from.
        module: The node's resolved splitter.
        incoming: The stream edges that target the node.
        splits: The number of streams declared in the module's ``splits`` conf.
        output_ports: The output port of each stream.
        sync_interface: The synchronous splitter with its call.
        async_interface: The asynchronous splitter with its call.

    Raises:

        InvalidPipelineError: When ``splits`` is read and is not an integer.

    Examples:

        >>> from riko.ext import ModuleNode
        >>> from riko.runtime._resolver import dispatcher
        >>>
        >>> pipe = dispatcher.require("split")
        >>> module = ResolvedModule("split", {"splits": 3}, sync_pipe=pipe)
        >>> prepared = PreparedSplitter(ModuleNode(id="s", name="split"), module)
        >>> prepared.splits
        3
        >>> prepared.output_ports
        ('out', 'out:1', 'out:2')

    """

    @cached_property
    def splits(self) -> int:
        return _parse_splits(self.module.conf.get("splits"))

    @property
    def has_pending_splits(self) -> bool:
        """Whether ``splits`` is a workflow input reference not yet given its value."""
        return is_input_ref(self.module.conf.get("splits"))

    @cached_property
    def output_ports(self) -> tuple[Port, ...]:
        return (OUT, *(f"{OUT}:{k}" for k in range(1, self.splits)))

    def validate_streams(
        self, *owned: StreamOf[object] | AsyncStreamOf[object]
    ) -> None:
        """
        Validates that the splitter yielded one stream per declared split.

        Args:

            owned: The owned streams the splitter yielded, read up to one past
                ``splits``.

        Raises:

            InvalidPipelineError: If the number of ``owned`` streams differs from
                ``splits``.

        """
        if (count := len(owned)) != self.splits:
            yielded = f"more than {self.splits}" if count > self.splits else count
            msg = f"splitter node {self.node.id!r} yielded {yielded} streams but "
            raise InvalidPipelineError(msg + f"declares {self.splits}")

    @property
    def is_thread_holder(self) -> bool:
        """Whether an async run holds a thread while the splitter reads upstream."""
        return self.module.async_pipe is None

    @cached_property
    def sync_interface(self) -> SyncInterface[Cascade] | None:
        """The synchronous splitter with its prepared call."""
        if (pipe := self.module.sync_pipe) is None:
            interface = None
        elif is_splitter(pipe):
            conf, options = self.module.conf, self.options.kwargs
            call = build_call(pipe, *self.extras, conf=conf, **options)
            interface = SyncInterface(pipe, call, call, IdentityMode.PRESERVE)
        else:
            raise InvalidPipelineError(f"{self.module.name!r} is not a splitter")

        return interface

    @cached_property
    def async_interface(self) -> AsyncInterface[AsyncCascade] | None:
        """The asynchronous splitter with its prepared call."""
        if (pipe := self.module.async_pipe) is None:
            interface = None
        elif is_splitter(pipe):
            conf, options = self.module.conf, self.options.kwargs
            call = build_call(pipe, *self.extras, conf=conf, **options)
            interface = AsyncInterface(pipe, call, call, IdentityMode.PRESERVE)
        else:
            raise InvalidPipelineError(f"{self.module.name!r} is not a splitter")

        return interface


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


def _is_async_only(node: AnyPreparedNode) -> bool:
    """Whether a sync run reads the node or its embed through the portal."""
    embed = node.embed if isinstance(node, PreparedNode) else None
    isnt_sync = node.sync_interface is None
    return isnt_sync or (embed is not None and embed.sync_pipe is None)


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
        embeds: The resolved sync and async callables, keyed by loop node id.
        inputs: Values the nodes' configurations were built from, keyed by input name.
        index: The workflow's graph index, including each workflow output's subgraph.
        nodes: Each workflow node paired with its resolved module and embed.

    Raises:

        InvalidPipelineError: If any of these hold:

            - ``workflow`` is not a ``Workflow``, or its graph is invalid.
            - A node is neither a module node nor a callable node.
            - A named input port uses a reserved name (e.g., ``conf``) or a parameter
              name the module's pipe fills by position.
            - ``modules`` does not resolve the workflow's nodes, or ``embeds`` does not
              resolve its loop embeds.
            - An edge or workflow output reads a port its node does not produce.
            - A splitter has fewer than one split.

    Examples:

        >>> from riko import Workflow
        >>> from riko.ext import ModuleNode
        >>> from riko.runtime._resolver import dispatcher
        >>>
        >>> flow = Workflow().with_nodes(ModuleNode(id="a", name="hash"))
        >>> plan = ExecutionPlan.from_workflow(flow, dispatcher)
        >>> plan.nodes["a"].node
        ModuleNode(id='a', name='hash', resources=FrozenDict({})...)
        >>> plan.index.order
        ('a',)

    """

    workflow: Workflow = field(converter=_require_workflow)
    modules: ResolvedModules = field(converter=_modules_converter)
    embeds: ResolvedModules = field(default=_EMPTY_EMBEDS, converter=_embeds_converter)
    inputs: FrozenInputs | None = field(
        default=None, converter=freeze_inputs, alias="_inputs"
    )

    def __attrs_post_init__(self) -> None:
        self.validate()

    @classmethod
    def from_workflow(cls, flow: Workflow, dispatcher: Dispatcher) -> Self:
        """
        Builds an executable snapshot of ``flow`` with every node resolved once.

        Each distinct module name is looked up once. Nodes that share a name reuse its
        callables with their own conf.

        Args:

            flow: The ``Workflow`` to prepare.

            dispatcher: Finds each node's pipe by name, whether a module such as
                ``fetch`` or a stored workflow's ``pipe_<id>``.

        Returns:

            The prepared plan: its graph index and resolved nodes. No node runs and
            no resource is acquired here.

        Raises:

            InvalidPipelineError: If any of these hold:

                - The graph is invalid.
                - A node isn't a module or callable node (write, action, cache, or
                  subscribe).
                - A named input port uses a reserved name (e.g., ``conf``) or a
                  parameter name the module's pipe fills by position.
                - An edge or workflow output reads a port its node does not produce.
                - A splitter has fewer than one split.

            UnsupportedModuleError: If no module has the name a node gives.

            UnsupportedWorkflowError: If no stored workflow has the ``pipe_<id>`` name
                a node gives.

        Examples:

            >>> from riko import Workflow
            >>> from riko.ext import ModuleNode
            >>> from riko.runtime._resolver import dispatcher
            >>>
            >>> flow = Workflow().with_nodes(ModuleNode(id="count-1", name="count"))
            >>> plan = ExecutionPlan.from_workflow(flow, dispatcher)
            >>> sorted(plan.nodes)
            ['count-1']

        """
        by_name: dict[str, ResolvedModule] = {}

        def resolve(name: str, conf: ConfInput) -> ResolvedModule:
            if (module := by_name.get(name)) is None:
                result = ResolvedModule.from_dispatcher(dispatcher, name, conf)
                by_name[name] = result
            else:
                result = evolve(module, conf=conf)

            return result

        resolve_callable = partial(_resolve_callable, dispatcher)
        modules = {k: resolve(n.name, n.conf) for k, n in flow.module_nodes.items()}
        embeds = {k: resolve(e["name"], e["conf"]) for k, e in flow.embeds.items()}
        callables = map_values(resolve_callable, flow.callable_nodes)
        return cls(flow, {**modules, **callables}, embeds)

    @property
    def index(self) -> WorkflowIndex:
        """The workflow's graph index, including each workflow output's subgraph."""
        return self.workflow.index

    def _build_node(self, node_id: NodeId, node: RunnableNode) -> AnyPreparedNode:
        module, incoming = self.modules[node_id], self.index.incoming.get(node_id, ())

        if module.is_splitter:
            prepared: AnyPreparedNode = PreparedSplitter(node, module, incoming)
        else:
            embed = self.embeds.get(node_id)
            prepared = PreparedNode(node, module, incoming, embed=embed)

        return prepared

    @cached_property
    def nodes(self) -> PreparedNodes:
        """Each runnable node prepared with its resolved module and keyed by node id."""
        pairs = self.workflow.runnable_nodes.items()
        prepared = {k: self._build_node(k, n) for k, n in pairs}
        return FrozenDict.from_frozen(prepared)

    def require_output(self, output: OutputName) -> Endpoint:
        """
        Requires the plan to have a workflow output named ``output``.

        Args:

            output: The name of the workflow output to run.

        Returns:

            The output's endpoint.

        Raises:

            InvalidPipelineError: If the plan exposes no such workflow output.

        """
        if (endpoint := self.index.outputs.get(output)) is None:
            raise InvalidPipelineError(f"workflow has no workflow output {output!r}")

        return endpoint

    def get_port_demand(self, output: OutputName) -> Counter[PortKey]:
        """
        Counts workflow ``output`` ports' readers.

        Every edge into a node the run builds reads its source port once, and the
        workflow output reads its own port once. A port the run never reads is absent.

        Args:

            output: The name of the workflow output being run.

        Returns:

            The port reader count, keyed by node id and canonical port.

        Raises:

            InvalidPipelineError: If the plan doesn't expose workflow ``output``.

        Examples:

            >>> from riko import Workflow
            >>> from riko.ext import ModuleNode
            >>> from riko.runtime._resolver import dispatcher
            >>>
            >>> first = ModuleNode(id="a", name="uniq")
            >>> second = ModuleNode(id="b", name="uniq")
            >>>
            >>> flow = Workflow().with_nodes(first, second)
            >>> plan = ExecutionPlan.from_workflow(flow, dispatcher)
            >>> sorted(plan.get_port_demand("default").items())
            [(('a', 'out'), 1), (('b', 'out'), 1)]

        """
        endpoint = self.require_output(output)
        nodes = self.nodes
        required = self.index.required[output]
        edges = chain.from_iterable(nodes[i].incoming for i in required)
        return Counter(chain((edge.source_key for edge in edges), [endpoint.port_key]))

    def get_thread_demand(self, output: OutputName) -> int:
        """
        Computes how many node threads an async run of ``output`` may hold at once.

        A node without an async implementation that reads its whole input in one call
        holds a thread while it reads its input streams. It needs one thread more than
        the max number of threads any one of its input streams holds. A mappable node
        runs each item after it has been read. It needs no threads.

        Nodes with a ``union`` or ``join`` module read their input streams one at a
        time. They need only the max any one input stream holds. Otherwise a node may
        read its input streams together. In that case, it needs as many threads as the
        sum of its input streams.

        Args:

            output: The name of the workflow output being run.

        Returns:

            The most node threads held at once while the workflow output is read.

        Examples:

            >>> from riko import Workflow
            >>> from riko.ext import ModuleNode
            >>> from riko.runtime._resolver import dispatcher
            >>>
            >>> nodes = (ModuleNode(id=_id, name="uniq") for _id in "ab")
            >>> flow = Workflow().with_nodes(*nodes)
            >>> plan = ExecutionPlan.from_workflow(flow, dispatcher)
            >>> plan.get_thread_demand("default")
            0
            >>> pipe = dispatcher.require("uniq")
            >>> modules = dict.fromkeys("ab", ResolvedModule("uniq", sync_pipe=pipe))
            >>> sync_plan = ExecutionPlan(flow, modules=modules)
            >>> sync_plan.get_thread_demand("default")
            2

        """
        demand: dict[NodeId, int] = {}

        for node_id in self.index.required[output]:
            upstream_demand = [demand[src] for src in self.index.upstream[node_id]]
            node = self.nodes[node_id]
            max_count = max(upstream_demand, default=0)

            if node.is_thread_holder:
                demand[node_id] = max_count + 1
            elif node.sequential_inputs:
                demand[node_id] = max_count
            else:
                demand[node_id] = sum(upstream_demand)

        return max(demand.values(), default=0)

    def uses_portal(self, output: OutputName = DEFAULT_OUTPUT) -> bool:
        """
        Whether a sync run of ``output`` reads a node or an embed through the portal.

        Kwargs:

            output: The name of the workflow output being run.

        Returns:

            ``True`` when a node that ``output`` runs, or its host embed, has only an
            async pipe.

        Examples:

            >>> from riko import Workflow
            >>> from riko.ext import ModuleNode
            >>> from riko.runtime._resolver import dispatcher
            >>>
            >>> node = ModuleNode(id="a", name="hash")
            >>> flow = Workflow().with_nodes(node)
            >>> plan = ExecutionPlan.from_workflow(flow, dispatcher)
            >>> plan.uses_portal()
            False
            >>> async_pipe = dispatcher.require("hash", is_async=True)
            >>> module = ResolvedModule("hash", async_pipe=async_pipe)
            >>> async_plan = ExecutionPlan(flow, modules={"a": module})
            >>> async_plan.uses_portal()
            True

        """
        nodes = (self.nodes[node_id] for node_id in self.index.required[output])
        return any(map(_is_async_only, nodes))

    def _gen_seed_takers(self, output: OutputName) -> Iterator[NodeId]:
        """Ids of ``output``'s nodes that take a default seed and can't self start."""
        nodes, required = self.nodes, self.index.required[output]
        return (
            _id
            for _id in required
            if nodes[_id].takes_default_seed and not nodes[_id].is_self_starting
        )

    def is_self_starting_output(self, output: OutputName = DEFAULT_OUTPUT) -> bool:
        """
        Whether ``output`` runs without a seed.

        It does when every node it runs without a seed is self-starting (see
        ``PreparedNode.is_self_starting``). An empty workflow never does, since it
        streams its seed.

        Kwargs:

            output: The name of the workflow output to check.

        Returns:

            ``True`` when an unseeded run of ``output`` starts on its own.

        Examples:

            >>> from riko import Workflow
            >>> from riko.ext import ModuleNode
            >>> from riko.runtime._resolver import dispatcher
            >>>
            >>> def plan(name):
            ...     flow = Workflow().with_nodes(ModuleNode(id="n", name=name))
            ...     return ExecutionPlan.from_workflow(flow, dispatcher)
            >>>
            >>> plan("forever").is_self_starting_output()
            True
            >>> plan("hash").is_self_starting_output()
            False

        """
        if not (needy := self.workflow.is_empty):
            needy = next(self._gen_seed_takers(output), None) is not None

        return not needy

    def require_self_starting_output(self, output: OutputName) -> None:
        """
        Requires every default-seeded node that ``output`` runs to be self-starting.

        A node whose default input port gets neither an input stream nor a seed must be
        self-starting (see ``PreparedNode.is_self_starting``).

        Args:

            output: The name of the workflow output being run.

        Raises:

            InvalidPipelineError: If a node that takes the default seed is not
                self-starting.

        """
        if self.workflow.is_empty:
            msg = f"{self.workflow} has no nodes; an empty workflow requires a seed"
            raise InvalidPipelineError(msg)
        elif needy := list(self._gen_seed_takers(output)):
            names = ", ".join(map(repr, needy))
            msg = f"node(s) {names} take an input stream; this pipeline requires a seed"
            raise InvalidPipelineError(msg)

    def require_seed_target(self, output: OutputName) -> NodeId:
        """
        Requires that ``output``'s subgraph has exactly one node to feed.

        A node's default input is open when no stream edge targets its ``in`` port. The
        seed feeds the open node that isn't self-starting, or, when every open node is
        self-starting, the one open node.

        Args:

            output: The name of the workflow output being run.

        Returns:

            The node id whose default input can accept a seed.

        Raises:

            InvalidPipelineError: If the output's subgraph doesn't have exactly one node
                to feed.

        """
        open_nodes = list(filter(self.index.is_open, self.index.required[output]))
        needy = [_id for _id in open_nodes if not self.nodes[_id].is_self_starting]
        candidates = needy or open_nodes

        if (count := len(candidates)) == 1:
            target = candidates[0]
        else:
            msg = f"a seed requires exactly one open input, found {count}"
            raise InvalidPipelineError(msg)

        return target

    def require_seed[S](self, seed: S | None, output: OutputName) -> S:
        """
        Requires the seed that an empty workflow streams back unchanged.

        A workflow with no nodes is an identity plan: it outputs its seed. It can't run
        without a seed, and exposes only the default workflow output.

        Args:

            seed: Items for the workflow output's open input.
            output: The name of the workflow output being run.

        Returns:

            ``seed``.

        Raises:

            InvalidPipelineError: If ``output`` is not the default workflow output, or
                ``seed`` is not given.

        """
        if output != DEFAULT_OUTPUT:
            raise InvalidPipelineError(f"workflow has no workflow output {output!r}")
        elif seed is None:
            msg = "workflow has no nodes; an empty workflow requires a seed"
            raise InvalidPipelineError(msg)

        return seed

    def gen_build_order[V](
        self, output: OutputName, *, seed: V | None = None
    ) -> Iterator[tuple[NodeId, V | None]]:
        """
        Pairs each node that ``output`` runs, in build order, with the seed it takes.

        Args:

            output: The name of the workflow output being run.

        Kwargs:

            seed: Items for the workflow output's open input.

        Yields:

            Each node id the output runs paired with the seed it takes, or ``None``.

        Raises:

            InvalidPipelineError: If a seed is given and the output's subgraph doesn't
                have exactly one node for it to feed, or no seed is given and a node
                requires one.

        """
        if seed is None:
            self.require_self_starting_output(output)
            seed_target = None
        else:
            seed_target = self.require_seed_target(output)

        for node_id in self.index.required[output]:
            yield node_id, seed if node_id == seed_target else None

    def with_inputs(self, inputs: Inputs | None) -> Self:
        """
        Builds the plan whose nodes run with the given ``Inputs``.

        Each ``{"input": name}`` mapping in a module node's conf, a loop's embed conf,
        or a callable node's keyword arguments is replaced by ``inputs[name]``. A
        resolved module whose conf refers to no input is used as is.

        Args:

            inputs: The inputs keyed by input name.

        Returns:

            A new plan whose ``inputs`` hold the inputs its nodes' configurations were
            built from.

        Raises:

            InvalidPipelineError: If the plan's configurations were already built from
                inputs.

        Examples:

            >>> from riko import Workflow
            >>> from riko.ext import ModuleNode
            >>> from riko.runtime._resolver import dispatcher
            >>>
            >>> conf = {"attrs": {"key": "q", "value": {"input": "q"}}}
            >>> node = ModuleNode(id="b", name="itembuilder", conf=conf)
            >>> schemas = {"q": {"type": "integer"}}
            >>> flow = Workflow(input_schemas=schemas).with_nodes(node)
            >>>
            >>> plan_a = ExecutionPlan.from_workflow(flow, dispatcher)
            >>> plan_b = plan_a.with_inputs({"q": 2})
            >>> dict(plan_b.inputs)
            {'q': 2}
            >>> dict(plan_b.modules["b"].conf["attrs"])
            {'key': 'q', 'value': 2}

        """
        if self.inputs is not None:
            msg = "The plan's configurations were already built from inputs."
            raise InvalidPipelineError(msg)

        _inputs: Inputs = resolve_default(inputs, _NO_INPUTS)

        def substitute(value: JSONValue) -> FrozenJSON:
            json_value = resolve_input_references(value, _inputs)
            return json_freeze(json_value)

        def resolve(module: ResolvedModule) -> ResolvedModule:
            if next(gen_input_references(module.conf), None) is None:
                result = module
            else:
                result = evolve(module, conf=substitute(module.conf))

            return result

        modules = map_values(resolve, self.modules)
        embeds = map_values(resolve, self.embeds)
        return evolve(self, modules=modules, embeds=embeds, _inputs=inputs)

    def _is_reserved_input(self, target: tuple[NodeId, Port]) -> bool:
        node_id, port = target
        module = self.modules.get(node_id)
        is_processor = module is not None and module.is_processor
        reserved = _PROCESSOR_RESERVED_INPUTS if is_processor else _RESERVED_INPUTS
        positional = frozenset() if module is None else module._positional_names
        return parse_port(port).name in reserved | positional

    def validate(self) -> None:
        """
        Validates that the workflow is runnable and the plan resolves its nodes.

        Raises:

            InvalidPipelineError: If any of these hold:

                - The graph is invalid.
                - A workflow node is neither a module node nor a callable node.
                - A named input port uses a reserved name (e.g., ``conf``) or a
                  parameter name the module's pipe fills by position.
                - ``modules`` does not resolve the workflow's nodes, or ``embeds``
                  does not resolve its loop embeds.
                - A splitter has fewer than one split.
                - An edge or workflow output reads a port its node does not produce.

        """
        flow = self.workflow

        if not flow.is_empty:
            flow.validate()

        flow.require_runnable_only("execution")
        targets = ((e.target_id, e.target_port) for e in flow.graph_edges)

        if reserved := sorted(filter(self._is_reserved_input, targets)):
            msg = f"input port(s) {reserved} use a reserved name. Rename the port(s)."
            raise InvalidPipelineError(msg)
        elif unresolved := set(flow.runnable_nodes).symmetric_difference(self.modules):
            msg = f"modules must match the workflow's nodes: {sorted(unresolved)}"
            raise InvalidPipelineError(msg)
        elif mismatched := set(flow.embeds).symmetric_difference(self.embeds):
            msg = f"embeds must match the workflow's loop embeds: {sorted(mismatched)}"
            raise InvalidPipelineError(msg)

        self._validate_port_wiring()

    def _gen_read_ports(self) -> Iterator[PortKey]:
        """The node id and canonical port of each edge source and workflow output."""
        yield from (edge.source_key for edge in self.workflow.graph_edges)
        yield from (endpoint.port_key for endpoint in self.index.outputs.values())

    def _validate_port_wiring(self) -> None:
        """
        Validates that every splitter has an output and every read port exists.

        Input reference splitter counts are checked once ``with_inputs`` supplies the
        value.
        """
        nodes = self.nodes
        pending = {
            node_id
            for node_id, node in nodes.items()
            if isinstance(node, PreparedSplitter) and node.has_pending_splits
        }

        for node_id, node in nodes.items():
            if (
                isinstance(node, PreparedSplitter)
                and node_id not in pending
                and (splits := node.splits) < 1
            ):
                msg = f"node {node_id!r} needs at least one split, got {splits}"
                raise InvalidPipelineError(msg)

        read = (key for key in self._gen_read_ports() if key[0] not in pending)

        for node_id, port in read:
            if port not in (ports := nodes[node_id].output_ports):
                msg = f"node {node_id!r} has no output port {port!r}; it produces "
                msg += f"{ports}"
                raise InvalidPipelineError(msg)


__all__ = [
    "AsyncInterface",
    "ExecutionExtras",
    "ExecutionPlan",
    "PreparedNode",
    "PreparedSplitter",
    "ResolvedModule",
    "SyncInterface",
]
