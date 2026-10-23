# vim: sw=4:ts=4:expandtab
"""
The immutable, composable ``PipelineDefinition`` around a ``Workflow``.

Composition (chaining modules, appending writes, providing a context, resources, or
execution settings, and seeding it with items) derives a new definition and leaves the
original unchanged. Running one belongs to ``riko.Pipeline``.

"""

from __future__ import annotations

from functools import partial
from inspect import isawaitable
from typing import (
    TYPE_CHECKING,
    Any,
    Concatenate,
    Generic,
    Literal,
    Self,
    TypeGuard,
    cast,
    overload,
)

from attrs import define, evolve, field, fields
from typing_extensions import TypeVar

from riko.base.exceptions import InvalidPipelineError
from riko.types._collections import (
    FrozenConf,
    narrow_def_from_require,
    require_instance,
    validator_from_require,
)
from riko.types._guards import is_mapping, is_streamlike
from riko.types._module_ids import BUILTIN_MODULE_IDS
from riko.types._sentinels import MISSING, MissingType
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
    from riko.types._pipedef import Embed
    from riko.types._resource import LifecycleFactory
    from riko.types._streams import SourceLike
    from riko.types.modules import AnyModuleConf, CallOptionsLike, Conf

    from ._nodes import CallableVersion
    from ._resource_definition import (
        ResourceDefinition,
        ResourcesLike,
        ReusableResource,
    )
    from ._write import Destination

T = TypeVar("T", default=Item)


def _is_source(value: object) -> TypeGuard[SourceLike]:
    """A seed on the left of ``|``: a stream, an async stream, or an awaitable."""
    seedlike = is_streamlike(value) or isawaitable(value)
    return seedlike and not isinstance(value, PipelineDefinition)


def _is_module_pair(value: object) -> TypeGuard[tuple[str, AnyModuleConf]]:
    """A ``(name, conf)`` pair on the right of ``|``."""
    return (
        isinstance(value, tuple)
        and len(value) == 2
        and isinstance(value[0], str)
        and is_mapping(value[1])
    )


_EMPTY_WORKFLOW = Workflow(nodes=[], outputs={}, inputs={})


def _require_workflow(value: object, what: str | None = None, **_) -> Workflow:
    if not isinstance(value, Workflow):
        msg = "Pipeline() takes a Workflow or None; use Pipeline.from_module(name) "
        msg += "for a module, Pipeline(source=items) to seed an item stream, or "
        msg += "Workflow.parse(document) for a document"
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
class PipelineDefinition(Generic[T]):
    """
    An immutable, composable pipeline definition around a ``Workflow``.

    Composition returns the caller's own class; ``Pipeline`` adds running. Build one
    from a ``Workflow``, ``from_module(name)``, ``source=items``, or empty for ``|``.
    A seed is not copied, so a generator is consumed by the first run.

    Attributes:

        workflow: The ``Workflow`` this pipeline runs.

        source: The seed (the items the pipeline starts from), or ``None`` when the
            graph supplies its own.

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
        >>> PipelineDefinition(source=[{"x": 1}]).source
        [{'x': 1}]

    """

    workflow: Workflow = field(default=_EMPTY_WORKFLOW, converter=_optional_workflow)
    source: SourceLike | None = field(default=None, repr=False)
    context: Context | None = field(
        default=None, kw_only=True, repr=False, validator=_is_context
    )
    settings: ExecutionSettings = field(
        default=DEF_EXECUTION_SETTINGS, kw_only=True, repr=False, validator=_is_settings
    )

    def __repr__(self) -> str:
        seed = "" if self.source is None else "; seed"
        context = "" if self.context is None else "; context"
        summary = self.workflow.summary
        return f"{type(self).__name__}({summary}{seed}{context})"

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
        return cls().pipe(name, conf=conf, options=options, embed=embed)

    def replace(
        self,
        *,
        workflow: Workflow | None = None,
        source: SourceLike | MissingType | None = MISSING,
    ) -> Self:
        """
        Derives a fresh pipeline with the given workflow or source.

        The original is left unchanged, and the new pipeline keeps its context and
        execution settings.

        Kwargs:

            workflow: Replacement workflow, or ``None`` to keep the current one.

            source: Replacement source, omitted to keep the current one, or ``None`` for
                no source.

        Returns:

            A new pipeline of the same type.

        Examples:

            >>> sort = PipelineDefinition.from_module("sort")
            >>> seeded = sort.replace(source=[{"x": 1}])
            >>> seeded.source
            [{'x': 1}]
            >>> seeded.workflow == sort.workflow
            True
            >>> seeded.replace(source=None).source
            >>> seeded.replace(workflow=Workflow()).source
            [{'x': 1}]

        """
        return evolve(
            self,
            workflow=self.workflow if workflow is None else workflow,
            source=self.source if isinstance(source, MissingType) else source,
        )

    def pipe(
        self,
        name: ModuleNameLike,
        *,
        conf: FrozenConf | Conf | None = None,
        options: CallOptionsLike | None = None,
        embed: Embed | None = None,
    ) -> Self:
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
        module, flow = str(name), self.workflow
        node_id = flow.get_node_id(module)
        node = ModuleNode(
            id=node_id, name=module, conf=conf, options=options, embed=embed
        )
        return self.replace(workflow=flow.with_node(node))

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

        Given a destination, the new pipeline declares where its items go, how
        they are serialized, and how they reconcile with what is already there.
        Given no destination, the call chains the shipped ``write`` module with
        the module arguments instead, so attribute chaining keeps working.
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

            >>> definition = PipelineDefinition(source=[{"x": 1}]).write("out.csv")
            >>> sorted(definition.workflow.nodes)
            ['write-1']
            >>> definition.workflow.outputs["default"]
            Endpoint(node='write-1', port='out')

        """
        if dest is None:
            written = self.pipe("write", conf=conf, options=options, embed=embed)
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
                (default: None, sequential processing).

            ordered: Whether results keep source order (default: False, completion
                order).

            event_sink: The sink that receives the run's events (default: None, events
                are discarded).

            shutdown_timeout: The bound, in seconds, on teardown under asynchronous
                iteration (default: None, no bound).

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

            A new pipeline bound to ``context``; this one is unchanged.

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
    def with_resource[R](  # noqa: E704
        self,
        name: str,
        definition: LifecycleFactory[R],
        *,
        credential: str | None = ...,
        lazy: bool = ...,
    ) -> Self: ...
    @overload  # noqa: E301
    def with_resource[R](  # noqa: E704
        self,
        name: str,
        definition: ReusableResource[R],
        *,
        credential: None = ...,
        lazy: Literal[False] = ...,
    ) -> Self: ...
    def with_resource[R](  # noqa: E301
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
        bound = base.with_resource(name, definition, credential=credential, lazy=lazy)
        return evolve(self, context=bound)

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
        fn: Callable[[T], R] | Callable[Concatenate[T, ...], R],
        *,
        resources: ResourcesLike = (),
        version: CallableVersion = MISSING,
        identity: IdentityModeLike | None = None,
        **kwargs: object,
    ) -> PipelineDefinition[R]:
        """
        Chains ``fn`` as its own node and calls it with each item.

        ``fn`` receives each item as is and its return value becomes the next item. It
        is called with the item, then the keyword arguments, then each bound resource as
        a keyword named after its alias. Keyword arguments must be JSON-native, so use
        ``functools.partial`` to pass a non-JSON-native value.

        Args:

            fn: The callable to apply to each item.

        Kwargs:

            resources: The Context resources ``fn`` receives as keywords.
            version: The durable identity of ``fn``'s behavior, if declared.

            identity: How each result's identity relates to its input item
                (``"preserve"``, ``"derive"``, or ``"combine"``), if declared. Not yet
                implemented.

            kwargs (JSONValue): The JSON-native keywords ``fn`` receives with each item.

        Returns:

            A new pipeline whose default output is the callable node.

        Raises:

            InvalidPipelineError: If a resource alias is not a Python identifier, a
                keyword argument shares its name with a resource alias, a keyword
                argument is not JSON-native, or ``identity`` is not an identity mode.

            TypeError: If ``fn`` is not callable, or ``version`` is ``None`` or
                unhashable.

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
        flow = self.workflow
        name = get_callable_name(fn, "map")
        args = {"version": version, "identity": identity, "kwargs": kwargs}
        _id = flow.get_node_id(name)
        node = CallableNode(id=_id, name=name, fn=fn, resources=resources, **args)
        mapped = self.replace(workflow=flow.with_node(node))
        return cast("PipelineDefinition[R]", mapped)

    def __getattr__(self, name: str) -> Callable[..., Self]:
        """
        Chains a module by attribute. E.g., ``.sort()`` appends the sort module.

        Only built-in modules chain by attribute. Any other name raises
        ``AttributeError``. A registered, stored, or Context-defined module chains with
        ``.pipe(name)``, as does a built-in module named like a ``Pipeline`` method
        (e.g., ``split``).
        """
        if name not in BUILTIN_MODULE_IDS:
            raise AttributeError(name)

        return partial(self.pipe, name)

    def _or_template(self, other: PipelineDefinition[Any]) -> Self:
        """Chains a single-node, source-less pipeline used as a reusable template."""
        flow = other.workflow
        single = len(flow.nodes) == len(flow.runnable_nodes) == 1
        node = next(iter(flow.runnable_nodes.values())) if single else None

        if other.source is not None or node is None:
            msg = "pipeline template must define exactly one module or callable"
            raise InvalidPipelineError(msg)

        fresh = evolve(node, id=self.workflow.get_node_id(node.name))
        return self.replace(workflow=self.workflow.with_node(fresh))

    def __or__(self, other: object) -> Self:
        """
        Chains a module name, config pair, or single-module template using ``|``.

        Args:

            other: A module name, a ``(name, conf)`` pair, or a one-module pipeline.

        Returns:

            A new pipeline with the module appended.

        Examples:

            >>> definition = PipelineDefinition.from_module("fetch") | "sort"
            >>> sorted(definition.workflow.nodes)
            ['fetch-1', 'sort-1']
            >>> fetch = PipelineDefinition.from_module("fetch")
            >>> configured = fetch | ("sort", {"combine": "a"})
            >>> dict(configured.workflow.nodes["sort-1"].conf)
            {'combine': 'a'}

        """
        if isinstance(other, str):
            chained = self.pipe(other)
        elif _is_module_pair(other):
            name, conf = other
            chained = self.pipe(name, conf=conf)
        elif isinstance(other, PipelineDefinition):
            chained = self._or_template(other)
        else:
            chained = cast("Self", NotImplemented)

        return chained

    def __ror__(self, other: object) -> Self:
        """
        Seeds the pipeline with the items on the left of ``|``.

        Args:

            other: The item stream, async item stream, or awaitable to seed this
                pipeline with.

        Returns:

            A new pipeline seeded with ``other``.

        Examples:

            >>> items = [{"x": 1}, {"x": 2}]
            >>> definition = items | PipelineDefinition.from_module("sort")
            >>> definition.source is items
            True

        """
        if self.source is None and _is_source(other):
            primed = self.replace(source=other)
        else:
            primed = cast("Self", NotImplemented)

        return primed


__all__ = ["PipelineDefinition"]
