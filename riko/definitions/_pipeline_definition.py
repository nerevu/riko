# vim: sw=4:ts=4:expandtab
"""
The immutable, composable ``PipelineDefinition`` around a ``Workflow``.

Composition (chaining modules; appending writes; or providing a context, resources, or
execution settings) derives a new definition and leaves the original unchanged. Running
a ``Workflow`` belongs to ``riko.Pipeline``.

"""

from __future__ import annotations

from collections.abc import Iterable
from functools import partial
from typing import (
    TYPE_CHECKING,
    Concatenate,
    Generic,
    Literal,
    Self,
    TypeGuard,
    overload,
)

from attrs import define, evolve, field, fields
from typing_extensions import TypeVar

from riko.base._exceptions import InvalidPipelineError
from riko.base._guards import is_mapping
from riko.base._require_guards import (
    narrow_def_from_require,
    require_instance,
    validator_from_require,
)
from riko.base._sentinels import MISSING, MissingType
from riko.types._enums import ExecutionMode
from riko.types._module_ids import BUILTIN_MODULE_IDS
from riko.types._streams import Item

from ._context import Context
from ._module_definition import get_callable_name
from ._nodes import CallableNode, ModuleNode, WriteNode
from ._settings import DEF_EXECUTION_SETTINGS, ExecutionSettings
from ._targets import build_write
from ._workflow_definition import Workflow
from ._write import WriteMode

if TYPE_CHECKING:
    from collections.abc import Callable

    from riko.types._enums import (
        ConcurrencyLike,
        ExecutorLike,
        FmtLike,
        IdentityModeLike,
        ModuleNameLike,
        StrLike,
    )
    from riko.types._events import EventSink
    from riko.types._frozendict import FrozenConf
    from riko.types._options import CallOptionsLike
    from riko.types._pipedef import Embed
    from riko.types._resource import LifecycleFactory
    from riko.types.modules import AnyModuleConf, Conf

    from ._nodes import CallableVersion
    from ._resource_definition import (
        ResourceDefinition,
        ResourcesLike,
        ReusableResource,
    )
    from ._write import Destination

_EMPTY_WORKFLOW = Workflow(nodes=[], outputs={}, inputs={})

T_co = TypeVar("T_co", covariant=True, default=Item)


def _is_module_pair(value: object) -> TypeGuard[tuple[str, AnyModuleConf]]:
    """A ``(name, conf)`` pair, which the constructor refuses with a hint."""
    return (
        isinstance(value, tuple)
        and len(value) == 2
        and isinstance(value[0], str)
        and is_mapping(value[1])
    )


def _require_workflow(value: object, what: str | None = None, **_) -> Workflow:
    if not isinstance(value, Workflow):
        msg = "Pipeline() takes a Workflow or None. "

        if isinstance(value, PipelineDefinition):
            msg += "Got a Pipeline. Did you mean Pipeline(pipeline.workflow)?"
        elif is_mapping(value):
            msg += "Got a mapping. Did you mean Pipeline(Workflow.parse(document))?"
        elif isinstance(value, str):
            msg += "Got a str. Did you mean Pipeline.from_module(name)?"
        elif _is_module_pair(value):
            msg += "Got a module pair."
            msg += " Did you mean Pipeline.from_module(name, conf=conf)?"
        elif isinstance(value, Iterable):
            msg += "Got an iterable. Did you mean:\n\n    "
            msg += "pipeline = Pipeline.from_module(name)\n    pipeline(items)"
        else:
            msg += f"Got {type(value).__name__!r} instead."

        raise TypeError(msg)

    return value


_optional_workflow = narrow_def_from_require(_require_workflow, default=_EMPTY_WORKFLOW)
_is_context = validator_from_require(
    require_instance, Context, optional=True, error=TypeError
)
_is_settings = validator_from_require(
    require_instance, ExecutionSettings, error=TypeError
)


@define(frozen=True, slots=True, repr=False)
class PipelineDefinition(Generic[T_co]):
    """
    An immutable, composable pipeline definition around a ``Workflow``.

    Build one from a ``Workflow`` or with ``.from_module(name)``. Use an empty one to
    chain callables (via ``.map``) or other pipelines (via ``|``). To run a ``Workflow``
    use ``Pipeline`` instead.

    Attributes:

        workflow: The ``Workflow`` this pipeline composes.

        context: The environment each run uses, including the resources it provides, or
            ``None`` for a default one.

        settings: How each run executes its per-item work.

    Raises:

        TypeError: If ``context`` is not a ``Context`` or ``settings`` is not an
            ``ExecutionSettings``.

    Examples:

        >>> fetch = PipelineDefinition.from_module("fetch")
        >>> definition = fetch.sort(conf={"combine": "a"})
        >>> sorted(definition.workflow.nodes)
        ['fetch-1', 'sort-1']
        >>> definition.workflow.outputs["default"]
        Endpoint(node='sort-1', port='out')
        >>> definition
        PipelineDefinition(fetch-1 -> sort-1; outputs: default)

    """

    workflow: Workflow = field(default=_EMPTY_WORKFLOW, converter=_optional_workflow)
    context: Context | None = field(
        default=None, kw_only=True, repr=False, validator=_is_context
    )
    settings: ExecutionSettings = field(
        default=DEF_EXECUTION_SETTINGS, kw_only=True, repr=False, validator=_is_settings
    )

    def __repr__(self) -> str:
        context = "" if self.context is None else "; context"
        summary = self.workflow.summary
        return f"{type(self).__name__}({summary}{context})"

    @classmethod
    def from_module(
        cls,
        name: ModuleNameLike,
        *,
        conf: Conf | None = None,
        options: CallOptionsLike | None = None,
        embed: Embed | None = None,
    ) -> Self:
        """
        Builds a pipeline whose sole node is the named module.

        Module existence is not checked here, so a typo surfaces as a
        module-resolution failure when the pipeline runs rather than now.

        Args:

            name: The module's name.
            conf: The module's configuration, if any.
            options: The call options forwarded to the module, if any.
            embed: The module a loop runs per item, with its configuration, if any.

        Returns:

            A new pipeline whose sole node is the named module.

        Examples:

            >>> fetch = PipelineDefinition.from_module("fetch")
            >>> definition = fetch.sort(conf={"combine": "a"})
            >>> sorted(definition.workflow.nodes)
            ['fetch-1', 'sort-1']
            >>> definition.workflow.outputs["default"]
            Endpoint(node='sort-1', port='out')

        """
        flow = cls()._build_module_workflow(
            name, conf=conf, options=options, embed=embed
        )
        return cls(workflow=flow)

    def replace(self, *, workflow: Workflow | None = None) -> Self:
        """
        Derives a fresh pipeline with the given workflow.

        The original is left unchanged, and the new pipeline keeps its context and
        execution settings.

        Kwargs:

            workflow: Replacement workflow, or ``None`` to keep the current one.

        Returns:

            A new pipeline of the same type.

        Examples:

            >>> sort = PipelineDefinition.from_module("sort")
            >>> sorted(sort.workflow.nodes)
            ['sort-1']
            >>> fetch = PipelineDefinition.from_module("fetch")
            >>> sorted(sort.replace(workflow=fetch.workflow).workflow.nodes)
            ['fetch-1']

        """
        return evolve(self, workflow=self.workflow if workflow is None else workflow)

    def pipe(
        self,
        name: ModuleNameLike,
        *,
        conf: FrozenConf | Conf | None = None,
        options: CallOptionsLike | None = None,
        embed: Embed | None = None,
    ) -> PipelineDefinition[Item]:
        """
        Chains the next module by name by re-pointing the default output to it.

        Module existence is not checked here, so a typo surfaces as a
        module-resolution failure when the pipeline runs rather than now.

        Args:

            name: The module to append.
            conf: The module's configuration, if any.
            options: The call options forwarded to the module, if any.
            embed: The module a loop runs per item, with its configuration, if any.

        Returns:

            A new pipeline whose default output is the appended module.

        Examples:

            >>> fetch = PipelineDefinition.from_module("fetch")
            >>> definition = fetch.pipe("sort", conf={"combine": "a"})
            >>> sorted(definition.workflow.nodes)
            ['fetch-1', 'sort-1']
            >>> definition.workflow.outputs["default"]
            Endpoint(node='sort-1', port='out')
            >>> delimiter = {"type": "text", "value": " "}
            >>> embed = {"name": "tokenizer", "conf": {"delimiter": delimiter}}
            >>> builder = PipelineDefinition.from_module("itembuilder")
            >>> looped = builder.loop(embed=embed, options={"emit": True})
            >>> looped.workflow.nodes["loop-1"].embed["name"]
            'tokenizer'
            >>> looped.workflow.nodes["loop-1"].options
            CallOptions(emit=True)

        """
        flow = self._build_module_workflow(
            name, conf=conf, options=options, embed=embed
        )
        return PipelineDefinition[Item](
            flow, context=self.context, settings=self.settings
        )

    def _build_module_workflow(
        self,
        name: ModuleNameLike,
        *,
        conf: FrozenConf | Conf | None = None,
        options: CallOptionsLike | None = None,
        embed: Embed | None = None,
    ) -> Workflow:
        """Appends module ``name`` to the workflow as its new default output."""
        module, flow = str(name), self.workflow
        node_id = flow.get_node_id(module)
        node = ModuleNode(
            id=node_id, name=module, conf=conf, options=options, embed=embed
        )
        return flow.with_node(node)

    def write(
        self,
        dest: Destination | None = None,
        /,
        *,
        mode: WriteMode | str = WriteMode.REPLACE,
        fmt: FmtLike | None = None,
        keys: StrLike | None = None,
        conf: FrozenConf | Conf | None = None,
        options: CallOptionsLike | None = None,
        embed: Embed | None = None,
    ) -> Self:
        """
        Appends a write to ``dest``, or chains the ``write`` module without one.

        Given a destination, the new pipeline declares where its items go, how they are
        serialized, and how they reconcile with what is already there. Without a
        destination, it chains the ``write`` module with module arguments instead.
        Supplying both a destination and module arguments is a call-site error.

        Args:

            dest: The destination path or write target, or ``None`` to chain the
                ``write`` module.

            mode: How the items reconcile with the destination's contents.
            fmt: The serialization format, or ``None`` to derive one.
            keys: The match keys a keyed destination needs.
            conf: The ``write`` module's configuration, if any.
            options: The call options forwarded to the ``write`` module, if any.
            embed: The module a loop runs per item, with its configuration, if any.

        Returns:

            A new pipeline whose default output is the appended node.

        Raises:

            TypeError: If ``dest`` is given together with ``conf``, ``options``,
                or ``embed``.

            ValueError: If ``dest``, ``mode``, ``fmt``, and ``keys`` do not form a
                write the destination supports.

        Examples:

            >>> definition = PipelineDefinition.from_module("fetch").write("out.csv")
            >>> sorted(definition.workflow.nodes)
            ['fetch-1', 'write-1']
            >>> definition.workflow.outputs["default"]
            Endpoint(node='write-1', port='out')

        """
        if dest is None:
            flow = self._build_module_workflow(
                "write", conf=conf, options=options, embed=embed
            )
            written = self.replace(workflow=flow)
        elif conf is not None or options is not None or embed is not None:
            msg = "write() takes either a destination or module arguments, not both"
            raise TypeError(msg)
        else:
            prepared = build_write(dest, mode, fmt=fmt, keys=keys)
            node_id = self.workflow.get_node_id("write")
            node = WriteNode.from_prepared(prepared, id=node_id)
            written = self.replace(workflow=self.workflow.with_node(node))

        return written

    def with_execution(
        self,
        *,
        executor: ExecutorLike | MissingType | None = MISSING,
        concurrency: ConcurrencyLike | MissingType | None = MISSING,
        ordered: bool | MissingType | None = MISSING,
        event_sink: EventSink | MissingType | None = MISSING,
        shutdown_timeout: float | MissingType | None = MISSING,
    ) -> Self:
        """
        Derives a pipeline whose runs execute with the given settings.

        Without settings, a run processes one item at a time in source order. An omitted
        argument keeps the current setting. An explicit ``None`` restores that setting's
        default. Settings are validated here, not when the pipeline runs.

        Args:

            executor: Picks where per-item work runs: ``"auto"``, ``"inline"``,
                ``"thread"``, or ``"process"`` (default: "auto").

            concurrency: Max number of items that item-wise modules can work on at once
                across the whole run. ``"auto"`` selects a size based on the machine.
                (default: None, i.e., sequential processing).

            ordered: Whether results keep source order (default: False, i.e., completion
                order).

            event_sink: The sink that receives the run's events (default: None, i.e.,
                events are discarded).

            shutdown_timeout: The bound, in seconds, on cleanup under asynchronous
                iteration, and on how long stopped worker processes get, together,
                before any still running are killed. ``math.inf`` means no bound
                (default: None, i.e., 30 seconds unless ``RIKO_SHUTDOWN_TIMEOUT`` is
                set).

        Returns:

            A new pipeline carrying the updated settings.

        Raises:

            ValueError: If ``executor`` names no known executor, ``concurrency``
                is below one, or ``shutdown_timeout`` is negative or NaN.

            TypeError: If ``concurrency``, ``ordered``, or ``shutdown_timeout``
                has the wrong type.

        Examples:

            >>> base = PipelineDefinition.from_module("fetch")
            >>> threaded = base.with_execution(executor="thread", concurrency=4)
            >>> threaded.settings.executor.value, threaded.settings.concurrency
            ('thread', 4)
            >>> threaded.with_execution(ordered=True).settings.concurrency
            4
            >>> print(threaded.with_execution(concurrency=None).settings.concurrency)
            None
            >>> print(base.settings.concurrency)
            None

        """
        requested = {
            "executor": executor,
            "concurrency": concurrency,
            "ordered": ordered,
            "event_sink": event_sink,
            "shutdown_timeout": shutdown_timeout,
        }
        defaults = fields(ExecutionSettings)
        changes = {
            name: getattr(defaults, name).default if value is None else value
            for name, value in requested.items()
            if value is not MISSING
        }
        return evolve(self, settings=evolve(self.settings, **changes))

    def with_context(self, context: Context) -> Self:
        """
        Derives a pipeline whose runs use ``context``.

        The context supplies the run's input values, mode, and resources, and
        replaces any context this pipeline already carries.

        Args:

            context: The environment each run uses.

        Returns:

            A new pipeline that runs with ``context``.

        Examples:

            >>> from riko import Context
            >>>
            >>> context = Context(inputs={"limit": 5})
            >>> fetch = PipelineDefinition.from_module("fetch")
            >>> definition = fetch.with_context(context)
            >>> definition.context is context
            True

        """
        return evolve(self, context=context)

    @overload
    def with_resource[R](
        self,
        name: str,
        definition: LifecycleFactory[R],
        *,
        credential: str | None = ...,
        lazy: bool = ...,
    ) -> Self: ...
    @overload
    def with_resource[R](
        self,
        name: str,
        definition: ReusableResource[R],
        *,
        credential: None = ...,
        lazy: Literal[False] = ...,
    ) -> Self: ...
    def with_resource[R](
        self,
        name: str,
        definition: ResourceDefinition[R],
        *,
        credential: str | None = None,
        lazy: bool = False,
    ) -> Self:
        """
        Derives a pipeline whose runs provide a resource ``definition`` as ``name``.

        The resource is added to this pipeline's context, or to a default context
        when it has none, exactly as ``Context.with_resource`` provides it. A
        factory is entered by the run rather than here, so ``credential``/``lazy``
        apply only to a factory.

        Args:

            name: The Context name the resource is provided under.
            definition: A ``Resource``/``LifecycleFactory`` that wraps a resource value.
            credential: A credential reference for a factory.
            lazy: Whether entry should defer until first use. Not yet honored: a run
                acquires every resource its nodes bind, whether or not it is used.

        Returns:

            A new pipeline whose context carries the resource. This one is unchanged.

        Raises:

            TypeError: When ``credential``/``lazy`` accompany a ``Resource`` (they
                belong on a ``LifecycleFactory``).

        Examples:

            >>> def open_db():
            ...     yield {"rows": []}
            >>>
            >>> fetch = PipelineDefinition.from_module("fetch")
            >>> definition = fetch.with_resource("db", open_db)
            >>> sorted(definition.context.resources)
            ['db']

        """
        base = Context() if self.context is None else self.context
        context = base.with_resource(name, definition, credential=credential, lazy=lazy)
        return evolve(self, context=context)

    @classmethod
    def subscribe(cls, *args: object, **kwargs: object) -> Self:
        """
        Reserves the local-subscription constructor; its arguments are not settled.

        Args:

            args: The not-yet-settled positional arguments.
            kwargs: The not-yet-settled keyword arguments.

        Raises:

            NotImplementedError: Always; local subscriptions are not available yet.

        """
        raise NotImplementedError("local subscriptions are not available yet")

    def publish(self, *args: object, **kwargs: object) -> Self:
        """
        Reserves publishing to a subscription; its arguments are not settled.

        Args:

            args: The not-yet-settled positional arguments.
            kwargs: The not-yet-settled keyword arguments.

        Raises:

            NotImplementedError: Always; publishing is not available yet.

        """
        raise NotImplementedError("publishing to a subscription is not available yet")

    def split(self, *args: object, **kwargs: object) -> tuple[Self, ...]:
        """
        Reserves streaming fan-out into branches; its arguments are not settled.

        Args:

            args: The not-yet-settled positional arguments.
            kwargs: The not-yet-settled keyword arguments.

        Raises:

            NotImplementedError: Always; streaming fan-out is not available yet.

        """
        raise NotImplementedError("streaming fan-out is not available yet")

    def map[R](
        self,
        fn: Callable[[T_co], R] | Callable[Concatenate[T_co, ...], R],
        *,
        resources: ResourcesLike = (),
        version: CallableVersion = MISSING,
        identity: IdentityModeLike | None = None,
        **kwargs: object,
    ) -> PipelineDefinition[R]:
        """
        Chains ``fn`` as its own node and calls it with each item.

        ``Pipeline.map`` documents the call contract and its errors.

        Examples:

            >>> from operator import itemgetter
            >>>
            >>> fetch = PipelineDefinition.from_module("fetch")
            >>> definition = fetch.map(itemgetter("title"))
            >>> sorted(definition.workflow.nodes)
            ['fetch-1', 'map-1']
            >>> definition.workflow.outputs["default"]
            Endpoint(node='map-1', port='out')

        """
        flow = self._build_callable_workflow(
            fn, resources=resources, version=version, identity=identity, **kwargs
        )
        return PipelineDefinition[R](flow, context=self.context, settings=self.settings)

    def _build_callable_workflow(
        self,
        fn: Callable[..., object],
        *,
        resources: ResourcesLike = (),
        version: CallableVersion = MISSING,
        identity: IdentityModeLike | None = None,
        **kwargs: object,
    ) -> Workflow:
        """Appends a callable node for ``fn`` to the workflow as its default output."""
        flow, name = self.workflow, get_callable_name(fn, "map")
        _kwargs = {"version": version, "identity": identity, "kwargs": kwargs}
        _id = flow.get_node_id(name)
        node = CallableNode(id=_id, name=name, fn=fn, resources=resources, **_kwargs)
        return flow.with_node(node)

    def __getattr__(self, name: str) -> Callable[..., PipelineDefinition[Item]]:
        """
        Chains a module by attribute. E.g., ``.sort()`` appends the sort module.

        Only built-in modules chain by attribute. Any other name raises
        ``AttributeError``. A registered, stored, or Context-defined module chains with
        ``.pipe(name)``, as does a built-in module named like a ``Pipeline`` method
        (e.g., ``split``).
        """
        return partial(self.pipe, self._require_attribute(name))

    def _require_attribute(self, name: str) -> str:
        """Requires ``name`` to name a built-in module (``AttributeError`` if not)."""
        if name not in BUILTIN_MODULE_IDS:
            raise AttributeError(name)

        return name

    def _combine_context(self, other: Context | None) -> Context | None:
        """Combines ``other``'s resources into this pipeline's context."""
        base = Context() if self.context is None else self.context
        resources = {} if other is None else other.resources
        clashes = [k for k, v in resources.items() if base.resources.get(k, v) is not v]
        _run = (ExecutionMode.RUN, None, False)

        if other is not None and (other.mode, other.inputs, other.test) != _run:
            msg = "a pipeline on the right of '|' may provide resources, but not a "
            msg += "mode, inputs, or test flag; give them to the composed pipeline"
            raise InvalidPipelineError(msg)
        elif clashes:
            msg = f"both pipelines provide different resources named {sorted(clashes)}"
            raise InvalidPipelineError(msg)
        elif resources:
            context = evolve(base, _resources={**base.resources, **resources})
        else:
            context = self.context

        return context

    def _build_composed_workflow(self, other: PipelineDefinition[object]) -> Workflow:
        """Appends ``other``'s workflow unless it carries execution settings."""
        if other.settings != DEF_EXECUTION_SETTINGS:
            msg = "a pipeline on the right of '|' may not carry execution settings; "
            msg += "call with_execution on the composed pipeline"
            raise InvalidPipelineError(msg)

        return self.workflow.with_workflow(other.workflow)

    def _compose[R](self, other: PipelineDefinition[R]) -> PipelineDefinition[R]:
        """Chains ``other`` after this pipeline and combines their resources."""
        flow = self._build_composed_workflow(other)
        context = self._combine_context(other.context)
        return PipelineDefinition[R](flow, context=context, settings=self.settings)

    def _chain(self, other: object) -> PipelineDefinition[object]:
        """Chains a module name or another pipeline (the dispatch behind ``|``)."""
        if isinstance(other, PipelineDefinition):
            chained = self._compose(other)
        elif isinstance(other, str):
            chained = self.pipe(other)
        elif callable(other):
            msg = "'|' takes a module name or a pipeline, not a function. "
            msg += "Use .map(fn) to call a function with each item."
            raise TypeError(msg)
        else:
            chained = NotImplemented

        return chained

    @overload
    def __or__[R](self, other: PipelineDefinition[R]) -> PipelineDefinition[R]: ...
    @overload
    def __or__(self, other: ModuleNameLike) -> PipelineDefinition[Item]: ...
    def __or__(self, other: object) -> PipelineDefinition[object]:
        """
        Chains a module name or another pipeline using ``|``.

        ``Pipeline.__or__`` documents the composition contract and its errors.

        Examples:

            >>> from riko import Transforms
            >>>
            >>> definition = PipelineDefinition.from_module("fetch") | "sort"
            >>> sorted(definition.workflow.nodes)
            ['fetch-1', 'sort-1']
            >>> sort = PipelineDefinition.from_module("sort", conf={"combine": "a"})
            >>> steps = sort | Transforms.REVERSE
            >>> composed = PipelineDefinition.from_module("fetch") | steps
            >>> composed.workflow.index.order
            ('fetch-1', 'sort-1', 'reverse-1')
            >>> dict(composed.workflow.nodes["sort-1"].conf)
            {'combine': 'a'}
            >>> (composed | steps).workflow.index.order
            ('fetch-1', 'sort-1', 'reverse-1', 'sort-2', 'reverse-2')

        """
        return self._chain(other)


__all__ = ["PipelineDefinition"]
