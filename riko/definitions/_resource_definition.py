"""
Declares owned, external, one-shot, and reusable resource definitions.

Examples:

    Basic usage::

        >>> from riko import Resource
        >>>
        >>> resource = Resource({"connected": True}, cleanup=False)
        >>> resource.value, resource.external, resource.reusable
        ({'connected': True}, False, False)

"""

from __future__ import annotations

from inspect import isasyncgen, isgenerator
from typing import TYPE_CHECKING, Literal, Never, Self, overload
from warnings import warn

from attrs import define, field

from riko.base._exceptions import ResourceInterpretationWarning
from riko.types._frozendict import FrozenDict
from riko.types._io import is_closeable
from riko.types._resource import (
    AnyContextManager,
    AsyncLifecyclePlan,
    Cleanup,
    ExternalPlan,
    LifecycleFactory,
    OwnedPlan,
    ResolvedValue,
    ResourceFactory,
    ResourcePlan,
    ResourceStrategy,
    SyncLifecyclePlan,
    ValueFactory,
    ValueFactoryPlan,
    build_factory_plan,
    build_lifecycle_plan,
    is_context_manager,
    is_lifecycle_factory,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from riko.types._io import Closeable


type ResourcesLike = str | Iterable[str] | Mapping[str, str]
type Values = Mapping[str, object]


@define(frozen=True, slots=True, eq=False, repr=False, init=False)
class Resource[T]:
    """
    An immutable execution-resource definition.

    A resource is a resolved value, a caller-owned value, a value-producing factory, or
    a generator/context-manager lifecycle. Each constructor classifies its declaration
    once (see ``strategy``). ``Resource(value, cleanup=...)`` owns ``value`` and closes
    it after the run: with ``cleanup`` when given, never when ``cleanup`` is ``False``,
    and otherwise with the value's own ``aclose``/``close``.

    Attributes:

        credential: A credential reference resolved by the connector layer.
        lazy: Whether entry should defer until first use (not yet implemented).

    Examples:

        >>> from riko import Resource
        >>>
        >>> class _Connection:
        ...    def __init__(self):
        ...        self.opened = True
        ...
        ...    @property
        ...    def closed(self):
        ...        return not self.opened
        ...
        ...    def close(self) -> None:
        ...        self.opened = False
        >>>
        >>> resource = Resource.from_external(_Connection())
        >>> resource.value
        <..._Connection object at ...>
        >>> resource.external
        True
        >>> resource.reusable
        True

    """

    _plan: ResourcePlan[T]
    credential: str | None = field(default=None, kw_only=True)
    lazy: bool = field(default=False, kw_only=True)

    @classmethod
    def _validate_constructor(cls) -> None:
        if cls is not Resource:
            msg = f"{cls.__name__} is a declaration type. Construct it through "
            msg += "Resource(...), Resource.from_external(...), "
            msg += "Resource.from_factory(...), or Resource.from_lifecycle(...)."
            raise TypeError(msg)

    @overload
    def __new__(
        cls,
        value: Closeable,
        *,
        cleanup: Cleanup[T] | None = ...,
        credential: str | None = ...,
        lazy: bool = ...,
    ) -> OneShotResource[T]: ...
    @overload
    def __new__(
        cls,
        value: ResolvedValue[T],
        *,
        cleanup: Cleanup[T] | Literal[False],
        credential: str | None = ...,
        lazy: bool = ...,
    ) -> OneShotResource[T]: ...
    @overload
    def __new__(cls, value: Self) -> Never: ...
    @overload
    def __new__(cls, value: LifecycleFactory[T]) -> Never: ...
    @overload
    def __new__(cls, value: AnyContextManager[T]) -> Never: ...
    @overload
    def __new__(cls, value: T) -> Never: ...
    def __new__(cls, *args: object, **kwargs: object) -> Resource[T]:
        # pickle and copy rebuild an instance by calling __new__ with no arguments
        if args or kwargs:
            cls._validate_constructor()

        target = OneShotResource if cls is Resource else cls
        return object.__new__(target)

    @staticmethod
    def _validate_value(value: object) -> None:
        is_resource = isinstance(value, Resource)

        if is_resource or is_lifecycle_factory(value) or is_context_manager(value):
            msg = f"Expected a resolved resource value but got a: {type(value)}."
            raise TypeError(msg)

    def _set_fields(
        self, plan: ResourcePlan[T], credential: str | None, lazy: bool
    ) -> None:
        object.__setattr__(self, "_plan", plan)  # noqa: PLC2801
        object.__setattr__(self, "credential", credential)  # noqa: PLC2801
        object.__setattr__(self, "lazy", lazy)  # noqa: PLC2801

    def __init__(
        self,
        value: ResolvedValue[T],
        *,
        cleanup: Cleanup[T] | Literal[False] | None = None,
        credential: str | None = None,
        lazy: bool = False,
    ) -> None:
        self._validate_value(value)
        started = isgenerator(value) or isasyncgen(value)

        if cleanup is None and started:
            msg = "A generator object is not a resolved resource value. To run "
            msg += "a generator as setup and cleanup, pass the generator "
            msg += "function to Resource.from_lifecycle(...) instead."
            raise TypeError(msg)
        elif cleanup is None and not is_closeable(value):
            msg = "Must provide a Closeable value or cleanup function for riko "
            msg += f"owned resources. Not a {type(value).__name__}. If this "
            msg += "value's lifecycle is externally managed, use "
            msg += "Resource.from_external(...) instead."
            raise TypeError(msg)

        self._set_fields(OwnedPlan(value, cleanup), credential, lazy)

    @overload
    @staticmethod
    def _from_plan[V](
        target: type[ReusableResource[V]],
        plan: ResourcePlan[V],
        credential: str | None = ...,
        lazy: bool = ...,
    ) -> ReusableResource[V]: ...
    @overload
    @staticmethod
    def _from_plan[V](
        target: type[OneShotResource[V]],
        plan: ResourcePlan[V],
        credential: str | None = ...,
        lazy: bool = ...,
    ) -> OneShotResource[V]: ...
    @staticmethod
    def _from_plan[V](
        target: type[Resource[V]],
        plan: ResourcePlan[V],
        credential: str | None = None,
        lazy: bool = False,
    ) -> Resource[V]:
        resource = object.__new__(target)
        resource._set_fields(plan, credential, lazy)
        return resource

    @property
    def reusable(self) -> bool:
        """Whether a reusable Context may hold this resource."""
        return isinstance(self, ReusableResource)

    @property
    def external(self) -> bool:
        """Whether the caller owns the lifecycle (Riko never closes it)."""
        return isinstance(self._plan, ExternalPlan)

    @property
    def value(self) -> ResolvedValue[T]:
        """
        The resolved value an external or owned resource carries.

        Raises:

            AttributeError: When a factory or lifecycle produces the value at
                acquisition instead.

        """
        match self._plan:
            case ExternalPlan(value=value) | OwnedPlan(value=value):
                pass
            case _:
                msg = "A factory or lifecycle resource has no value until acquired."
                raise AttributeError(msg)

        return value

    @property
    def strategy(self) -> ResourceStrategy:
        """How an execution acquires and cleans up this resource."""
        match self._plan:
            case ExternalPlan():
                strategy = ResourceStrategy.EXTERNAL
            case OwnedPlan():
                strategy = ResourceStrategy.OWNED
            case ValueFactoryPlan():
                strategy = ResourceStrategy.VALUE_FACTORY
            case SyncLifecyclePlan() | AsyncLifecyclePlan():
                strategy = ResourceStrategy.LIFECYCLE

        return strategy

    @property
    def async_native(self) -> bool:
        """Whether an execution produces or enters this resource natively async."""
        match self._plan:
            case AsyncLifecyclePlan():
                is_async = True
            case ValueFactoryPlan():
                is_async = self._plan.is_async
            case _:
                is_async = False

        return is_async

    @overload
    @classmethod
    def from_factory[T](  # pyright: ignore[reportGeneralTypeIssues]
        cls,
        factory: ValueFactory[T],
        *args: object,
        cleanup: Cleanup[T] | Literal[False],
        credential: str | None = ...,
        lazy: bool = ...,
        **kwargs: object,
    ) -> ReusableResource[T]: ...
    @overload
    @classmethod
    def from_factory[T](  # pyright: ignore[reportGeneralTypeIssues]
        cls,
        factory: LifecycleFactory[T],
        *args: object,
        cleanup: None = ...,
        credential: str | None = ...,
        lazy: bool = ...,
        **kwargs: object,
    ) -> ReusableResource[T]: ...
    @classmethod
    def from_factory[T](  # pyright: ignore[reportGeneralTypeIssues]
        cls,
        factory: ResourceFactory[T],
        *args: object,
        cleanup: Cleanup[T] | Literal[False] | None = None,
        credential: str | None = None,
        lazy: bool = False,
        **kwargs: object,
    ) -> ReusableResource[T]:
        """The alternate form of ``Context.with_resource(name, factory)``."""
        cls._validate_constructor()
        plan = build_factory_plan(factory, *args, cleanup=cleanup, **kwargs)

        if is_context_manager(factory):
            warn(
                "Resource.from_factory() received a context manager. It will be treated"
                " as a ValueFactory and called normally; its context-manager lifecycle "
                "will not be entered. Use Resource.from_lifecycle(...) to use "
                "__enter__/__exit__ semantics.",
                ResourceInterpretationWarning,
                stacklevel=2,
            )

        return cls._from_plan(ReusableResource, plan, credential, lazy)

    @overload
    @classmethod
    def from_external[T](  # pyright: ignore[reportGeneralTypeIssues]
        cls, value: Resource[T]
    ) -> Never: ...
    @overload
    @classmethod
    def from_external[T](  # pyright: ignore[reportGeneralTypeIssues]
        cls, value: LifecycleFactory[T]
    ) -> Never: ...
    @overload
    @classmethod
    def from_external[T](  # pyright: ignore[reportGeneralTypeIssues]
        cls, value: AnyContextManager[T]
    ) -> Never: ...
    @overload
    @classmethod
    def from_external[T](  # pyright: ignore[reportGeneralTypeIssues]
        cls, value: ResolvedValue[T]
    ) -> ReusableResource[T]: ...
    @classmethod
    def from_external[T](  # pyright: ignore[reportInconsistentOverload,reportGeneralTypeIssues]
        cls, value: ResolvedValue[T]
    ) -> ReusableResource[T]:
        """
        Creates a resource whose lifecycle remains owned by the caller.

        Args:

            value: The resolved external value.

        Returns:

            A resource that always resolves to ``value`` and never closes it.

        Examples:

            >>> from riko import Resource
            >>>
            >>> class Client:
            ...     closed = False
            ...     def close(self):
            ...         self.closed = True
            >>>
            >>> value = Client()
            >>> resource = Resource.from_external(value)
            >>> resource.value is value
            True
            >>> resource.external
            True

        """
        cls._validate_constructor()
        cls._validate_value(value)
        return cls._from_plan(ReusableResource, ExternalPlan(value))

    @classmethod
    def from_lifecycle[T](  # pyright: ignore[reportGeneralTypeIssues]
        cls,
        factory: LifecycleFactory[T] | AnyContextManager[T],
        *,
        credential: str | None = None,
        lazy: bool = False,
    ) -> OneShotResource[T]:
        """
        Creates an owned resource from a generator/context-manager definition.

        The definition yields the value; the execution layer enters it during
        preparation and tears it down afterward. This is the explicit owned
        sibling of :meth:`from_external`.

        Args:

            factory: A sync/async generator function or context manager that
                yields the value, or a callable that produces one.

            credential: A credential reference resolved by the connector layer.

            lazy: Whether entry should defer until first use. Not yet honored: a run
                acquires every resource its nodes bind, whether or not it is used.

        Returns:

            An owned resource whose lifecycle Riko manages.

        Examples:

            >>> from riko import OneShotResource, Resource
            >>>
            >>> def db():
            ...     yield object()
            >>>
            >>> resource = Resource.from_lifecycle(db, credential="microsoft/cif")
            >>> isinstance(resource, OneShotResource)
            True
            >>> resource.strategy
            <ResourceStrategy.LIFECYCLE: 4>
            >>> resource.external
            False
            >>> resource.reusable
            False

        """
        cls._validate_constructor()
        plan = build_lifecycle_plan(factory)
        return cls._from_plan(OneShotResource, plan, credential, lazy)


class OneShotResource[T](Resource[T]):
    """
    A Resource that may only be used once.

    It is a declaration type: ``Resource(value)`` and ``Resource.from_lifecycle``
    construct it, and calling it or its constructors directly raises ``TypeError``.
    """

    __slots__ = ()

    if TYPE_CHECKING:

        def __new__(cls, *args: object, **kwargs: object) -> Never: ...


class ReusableResource[T](Resource[T]):
    """
    A Resource that may be stored in a reusable Context.

    It is a declaration type: ``Resource.from_external`` and ``Resource.from_factory``
    construct it, and calling it or its constructors directly raises ``TypeError``.
    """

    __slots__ = ()

    if TYPE_CHECKING:

        def __new__(cls, *args: object, **kwargs: object) -> Never: ...


type ReusableResources = FrozenDict[str, ReusableResource[object]]
type ResourceDefinition[T] = ReusableResource[T] | LifecycleFactory[T]

__all__ = ["OneShotResource", "Resource", "ReusableResource"]
