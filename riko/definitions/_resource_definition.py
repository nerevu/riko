"""Declares owned, external, one-shot, and reusable resource definitions."""

from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
    Never,
    Self,
    TypedDict,
    Unpack,
    cast,
    overload,
)
from warnings import warn

from attrs import define, field

from riko.base.exceptions import ResourceInterpretationWarning
from riko.types._collections import FrozenDict, freeze
from riko.types._io import is_closeable
from riko.types._resource import (
    VALUE_FACTORY_KINDS,
    AnyContextManager,
    Cleanup,
    FactoryKind,
    LifecycleFactory,
    ResourceFactory,
    ValueFactory,
    get_factory_kind,
    is_async_context_manager,
    is_context_manager,
    is_lifecycle_factory,
    is_sync_context_manager,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from riko.types._io import Closeable


type AnyFactory[T] = ResourceFactory[T] | AnyContextManager[T]
type ResourcesLike = str | Iterable[str] | Mapping[str, str]
type Values = Mapping[str, Any | Closeable]
type ResolvedValue[T] = T | Closeable


class _ResourceFields(TypedDict, total=False):
    """The optional fields an alternate constructor passes to the generated init."""

    credential: str | None
    lazy: bool
    cleanup: Cleanup[Any] | Literal[False] | None
    _kind: FactoryKind | None
    _factory: AnyFactory[Any] | None
    _args: tuple[object, ...]
    _kwargs: Mapping[str, object]
    _external: bool


@define(frozen=True, slots=True, eq=False, repr=False)
class Resource[T]:
    """
    An immutable execution-resource definition.

    A resource is a resolved value, a caller-owned value, a value-producing
    factory, or a generator/context-manager lifecycle. The variant is carried as
    data rather than a subclass: ``external`` marks caller-owned lifecycles and
    ``factory``/``kind`` mark declarations the execution layer enters.

    Attributes:

        value: The resolved value this resource hands to parsers.
        external: Whether the caller owns the lifecycle (Riko never closes it).
        credential: A credential reference resolved by the connector layer.
        cleanup: Overrides the value's ``aclose``/``close`` to close an owned handle.
        lazy: Whether entry should defer until first use. Not yet honored: a run
            acquires every resource its nodes bind, whether or not it is used.
        kind: How a factory produces its value, or ``None`` for a resolved value.
        factory: The factory or lifecycle the execution layer enters, if any.
        args: Frozen positional arguments for ``factory``.
        kwargs: Frozen keyword arguments for ``factory``.

    Examples:

        >>> from riko.definitions._resource_definition import Resource
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

    value: ResolvedValue[T]
    credential: str | None = field(default=None, kw_only=True)
    lazy: bool = field(default=False, kw_only=True)
    cleanup: Cleanup[T] | Literal[False] | None = field(default=None, kw_only=True)
    kind: FactoryKind | None = field(default=None, kw_only=True, alias="_kind")
    factory: AnyFactory[T] | None = field(default=None, kw_only=True, alias="_factory")
    args: tuple[object, ...] = field(
        factory=tuple, converter=freeze, kw_only=True, alias="_args"
    )
    kwargs: FrozenDict[str, object] = field(
        factory=FrozenDict, converter=FrozenDict, kw_only=True, alias="_kwargs"
    )
    external: bool = field(default=False, kw_only=True, alias="_external")

    @overload
    def __new__(  # noqa: E704
        cls,
        value: Closeable,
        *,
        cleanup: Cleanup[T] | None = ...,
        credential: str | None = ...,
        lazy: bool = ...,
    ) -> OneShotResource[T]: ...
    @overload  # noqa: E301
    def __new__(  # noqa: E704
        cls,
        value: ResolvedValue[T],
        *,
        cleanup: Cleanup[T] | Literal[False],
        credential: str | None = ...,
        lazy: bool = ...,
    ) -> OneShotResource[T]: ...
    @overload  # noqa: E301
    def __new__(cls, value: Self) -> Never: ...  # noqa: E704
    @overload  # noqa: E301
    def __new__(cls, value: LifecycleFactory[T]) -> Never: ...  # noqa: E704
    @overload  # noqa: E301
    def __new__(cls, value: AnyContextManager[T]) -> Never: ...  # noqa: E704
    @overload  # noqa: E301
    def __new__(cls, value: T) -> Never: ...  # noqa: E704
    def __new__(  # noqa: E301
        cls, *_: object, **_kw: object
    ) -> OneShotResource[T] | ReusableResource[T]:
        target = OneShotResource if cls is Resource else cls
        return cast("OneShotResource[T] | ReusableResource[T]", object.__new__(target))

    @staticmethod
    def _validate_value(value: object) -> None:
        is_resource = isinstance(value, Resource)

        if is_resource or is_lifecycle_factory(value) or is_context_manager(value):
            msg = f"Expected a resolved resource value but got a: {type(value)}."
            raise TypeError(msg)

    def _validate_fields(self) -> None:
        if (self.factory is None) != (self.kind is None):
            msg = "A resource factory and its kind must be given together. "
            msg += "Use Resource.from_factory(...) or Resource.from_lifecycle(...)."
            raise TypeError(msg)
        elif self.external and self.factory is not None:
            msg = "An external resource cannot carry a factory. "
            msg += "Use Resource.from_external(value)."
            raise TypeError(msg)
        elif self.external and not isinstance(self, ReusableResource):
            msg = "An external resource must be reusable. "
            msg += "Use Resource.from_external(value)."
            raise TypeError(msg)

    def __attrs_post_init__(self) -> None:
        self._validate_fields()

        if self.factory is None and not self.external:
            self._validate_value(self.value)

            if self.cleanup is None and not is_closeable(self.value):
                msg = "Must provide a Closeable value or cleanup function for riko "
                msg += f"owned resources. Not a {type(self.value).__name__}. If this "
                msg += "value's lifecycle is externally managed, use "
                msg += "Resource.from_external(...) instead."
                raise TypeError(msg)

    @classmethod
    def _from_data[R: Resource[Any]](
        cls, target: type[R], value: object, **fields: Unpack[_ResourceFields]
    ) -> R:
        resource = object.__new__(target)
        target.__init__(resource, value, **fields)
        return resource

    @property
    def reusable(self) -> bool:
        return isinstance(self, ReusableResource)

    @overload
    @classmethod
    def from_factory[T](  # noqa: E704  # pyright: ignore[reportGeneralTypeIssues]
        cls,
        factory: ValueFactory[T],
        *args: object,
        cleanup: Cleanup[T] | Literal[False],
        credential: str | None = ...,
        lazy: bool = ...,
        **kwargs: object,
    ) -> ReusableResource[T]: ...
    @overload  # noqa: E301
    @classmethod
    def from_factory[T](  # noqa: E704  # pyright: ignore[reportGeneralTypeIssues]
        cls,
        factory: LifecycleFactory[T],
        *args: object,
        cleanup: None = ...,
        credential: str | None = ...,
        lazy: bool = ...,
        **kwargs: object,
    ) -> ReusableResource[T]: ...
    @classmethod  # noqa: E301
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
        kind = get_factory_kind(factory, lifecycle=False)

        if kind in VALUE_FACTORY_KINDS:
            if cleanup is None:
                raise TypeError("ValueFactory requires an explicit cleanup function")
        elif cleanup is not None:
            msg = "Cleanup is not allowed for generator/context-manager factories. "
            msg += "Use Resource.from_lifecycle(...) instead if you want riko to "
            msg += "manage the lifecycle."
            raise TypeError(msg)

        if is_context_manager(factory):
            warn(
                "Resource.from_factory() received a context manager. It will be treated"
                " as a ValueFactory and called normally; its context-manager lifecycle "
                "will not be entered. Use Resource.from_lifecycle(...) to use "
                "__enter__/__exit__ semantics.",
                ResourceInterpretationWarning,
                stacklevel=2,
            )

        return cls._from_data(
            ReusableResource,
            factory,
            _factory=factory,
            _kind=kind,
            _args=args,
            _kwargs=kwargs,
            cleanup=cleanup,
            credential=credential,
            lazy=lazy,
        )

    @overload
    @classmethod
    def from_external[T](  # noqa: E704  # pyright: ignore[reportGeneralTypeIssues]
        cls, value: Resource[T]
    ) -> Never: ...
    @overload  # noqa: E301
    @classmethod
    def from_external[T](  # noqa: E704  # pyright: ignore[reportGeneralTypeIssues]
        cls, value: LifecycleFactory[T]
    ) -> Never: ...
    @overload  # noqa: E301
    @classmethod
    def from_external[T](  # noqa: E704  # pyright: ignore[reportGeneralTypeIssues]
        cls, value: AnyContextManager[T]
    ) -> Never: ...
    @overload  # noqa: E301
    @classmethod
    def from_external[T](  # noqa: E704  # pyright: ignore[reportGeneralTypeIssues]
        cls, value: ResolvedValue[T]
    ) -> ReusableResource[T]: ...
    @classmethod  # noqa: E301
    def from_external[T](  # pyright: ignore[reportInconsistentOverload,reportGeneralTypeIssues]  # noqa: E501
        cls, value: ResolvedValue[T]
    ) -> ReusableResource[T]:
        """
        Creates a resource whose lifecycle remains owned by the caller.

        Args:

            value: The resolved external value.

        Returns:

            A resource that always resolves to ``value`` and never closes it.

        Examples:

            >>> from riko.definitions._resource_definition import Resource
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
        cls._validate_value(value)
        return cls._from_data(ReusableResource, value, _external=True)

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

            >>> from riko.definitions._resource_definition import (
            ...     OneShotResource,
            ...     Resource,
            ... )
            >>> from riko.types._resource import FactoryKind
            >>>
            >>> def db():
            ...     yield object()
            >>>
            >>> resource = Resource.from_lifecycle(db, credential="microsoft/cif")
            >>> isinstance(resource, OneShotResource)
            True
            >>> resource.kind
            <FactoryKind.SYNC_GEN_FACTORY: 'sync_gen_factory'>
            >>> resource.external
            False
            >>> resource.reusable
            False

        """
        if is_sync_context_manager(factory):
            kind = FactoryKind.SYNC_CONTEXTMANAGER
        elif is_async_context_manager(factory):
            kind = FactoryKind.ASYNC_CONTEXTMANAGER
        else:
            kind = get_factory_kind(factory)

        return cls._from_data(
            OneShotResource,
            factory,
            _factory=factory,
            _kind=kind,
            credential=credential,
            lazy=lazy,
        )


class OneShotResource[T](Resource[T]):
    """A Resource that may only be used once."""

    __slots__ = ()


class ReusableResource[T](Resource[T]):
    """A Resource that may be stored in a reusable Context."""

    __slots__ = ()


type ReusableResources = FrozenDict[str, ReusableResource[Any]]
type ResourceDefinition[T] = ReusableResource[T] | LifecycleFactory[T]

__all__ = ["OneShotResource", "Resource", "ReusableResource"]
