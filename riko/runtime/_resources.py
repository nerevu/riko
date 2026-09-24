"""Executes owned, external, one-shot, and reusable resource lifecycles."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, Never, Self, cast, overload
from warnings import warn

from riko.bado._util import maybe_deferred
from riko.base.warnings import ResourceInterpretationWarning
from riko.definitions._resources import VALUE_FACTORY_KINDS, classify_factory
from riko.types._collections import freeze_mapping
from riko.types._guards import (
    is_async_closeable,
    is_async_context_manager,
    is_closeable,
    is_context_manager,
    is_lifecycle_factory,
    is_sync_context_manager,
)
from riko.types._resource import (
    AnyContextManager,
    Cleanup,
    FactoryKind,
    LifecycleFactory,
    ResourceFactory,
    ValueFactory,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from riko.definitions._resource_types import ResolvedValue
    from riko.types._io import Closeable, SyncCloseable


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
        lazy: Whether opening defers until first use (validated eagerly).

    Examples:

        >>> from riko.runtime._resources import Resource
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
        >>> value = resource.open()
        >>> value
        <..._Connection object at ...>
        >>> resource.close(value)
        >>> resource.external
        True
        >>> resource.reusable
        True

    """

    __slots__ = (
        "_args",
        "_cleanup",
        "_credential",
        "_external",
        "_factory",
        "_kind",
        "_kwargs",
        "_lazy",
        "_value",
    )

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

    @overload  # noqa: E301
    def __init__(  # noqa: E704
        self,
        value: Closeable,
        *,
        cleanup: Cleanup[T],
        credential: str | None = ...,
        lazy: bool = ...,
    ) -> None: ...
    @overload  # noqa: E301
    def __init__(  # noqa: E704, F811
        self,
        value: Closeable,
        *,
        cleanup: None = ...,
        credential: str | None = ...,
        lazy: bool = ...,
    ) -> None: ...
    @overload  # noqa: E301
    def __init__(  # noqa: E704, F811
        self,
        value: ResolvedValue[T],
        *,
        cleanup: Cleanup[T] | Literal[False],
        credential: str | None = ...,
        lazy: bool = ...,
    ) -> None: ...
    @overload  # noqa: E301
    def __init__(self, value: Self) -> Never: ...  # noqa: E704
    @overload  # noqa: E301
    def __init__(self, value: LifecycleFactory[T]) -> Never: ...  # noqa: E704
    @overload  # noqa: E301
    def __init__(self, value: AnyContextManager[T]) -> Never: ...  # noqa: E704
    @overload  # noqa: E301
    def __init__(self, value: T) -> Never: ...  # noqa: E704
    def __init__(  # noqa: E301 # pyright: ignore[reportInconsistentOverload]
        self,
        value: ResolvedValue[T],
        *,
        cleanup: Cleanup[T] | Literal[False] | None = None,
        credential: str | None = None,
        lazy: bool = False,
    ) -> None:
        self._value = value
        self._credential = credential
        self._lazy = lazy
        self._kind: FactoryKind | None = None
        self._cleanup: Cleanup[T] | Literal[False] | None = cleanup
        self._factory: ResourceFactory[T] | AnyContextManager[T] | None = None
        self._args: tuple[object, ...] = ()
        self._kwargs: Mapping[str, object] = freeze_mapping({})
        self._external = False

        self._reject_non_value(value)

        if cleanup is None and not is_closeable(value):
            msg = "Must provide a Closeable value or cleanup function for riko owned "
            msg += f"resources. Not a {type(value).__name__}. If this value's "
            msg += "lifecycle is externally managed, use Resource.from_external(...) "
            msg += "instead."
            raise TypeError(msg)

    @staticmethod
    def _reject_non_value(value: object) -> None:
        is_resource = isinstance(value, Resource)

        if is_resource or is_lifecycle_factory(value) or is_context_manager(value):
            msg = f"Expected a resolved resource value but got a: {type(value)}."
            raise TypeError(msg)

    @classmethod
    def _from_data[R: Resource[Any]](
        cls,
        target: type[R],
        *,
        value: object,
        factory: ResourceFactory[Any] | AnyContextManager[Any] | None = None,
        kind: FactoryKind | None = None,
        args: tuple[object, ...] = (),
        kwargs: Mapping[str, object] | None = None,
        cleanup: Cleanup[Any] | Literal[False] | None = None,
        credential: str | None = None,
        lazy: bool = False,
        external: bool = False,
    ) -> R:
        resource = object.__new__(target)
        resource._value = value
        resource._factory = factory
        resource._kind = kind
        resource._args = args
        resource._kwargs = freeze_mapping(dict(kwargs) if kwargs else {})
        resource._cleanup = cleanup
        resource._credential = credential
        resource._lazy = lazy
        resource._external = external
        return resource

    @property
    def value(self) -> ResolvedValue[T]:
        return self._value

    @property
    def credential(self) -> str | None:
        return self._credential

    @property
    def cleanup(self) -> Cleanup[T] | Literal[False] | None:
        return self._cleanup

    @property
    def lazy(self) -> bool:
        return self._lazy

    @property
    def kind(self) -> FactoryKind | None:
        return self._kind

    @property
    def external(self) -> bool:
        return self._external

    @property
    def reusable(self) -> bool:
        return isinstance(self, ReusableResource)

    @property
    def factory(self) -> ResourceFactory[T] | AnyContextManager[T] | None:
        return self._factory

    @property
    def args(self) -> tuple[object, ...]:
        return self._args

    @property
    def kwargs(self) -> Mapping[str, object]:
        return self._kwargs

    def _execution_error(self, action: str) -> str:
        noun = "Factory" if self.reusable else "Lifecycle"
        return f"{noun} resource {action} belongs to the execution layer"

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
        kind = classify_factory(factory, lifecycle=False)

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
            value=factory,
            factory=factory,
            kind=kind,
            args=args,
            kwargs=kwargs,
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

            >>> from riko.runtime._resources import Resource
            >>>
            >>> class Client:
            ...     closed = False
            ...     def close(self):
            ...         self.closed = True
            >>>
            >>> value = Client()
            >>> resource = Resource.from_external(value)
            >>> resource.open() is value
            True
            >>> resource.close(value)
            >>> value.closed
            False

        """
        cls._reject_non_value(value)
        return cls._from_data(ReusableResource, value=value, external=True)

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

            lazy: Whether entry defers until first use (validated eagerly).

        Returns:

            An owned resource whose lifecycle Riko manages.

        Examples:

            >>> from riko.runtime._resources import (
            ...     FactoryKind,
            ...     OneShotResource,
            ...     Resource,
            ... )
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
            kind = classify_factory(factory)

        return cls._from_data(
            OneShotResource,
            value=factory,
            factory=factory,
            kind=kind,
            credential=credential,
            lazy=lazy,
        )

    def open(self) -> ResolvedValue[T]:
        """
        Resolves this resource's value.

        Returns:

            The wrapped value.

        Raises:

            NotImplementedError: When the resource is a factory/lifecycle
                declaration; the execution layer enters it instead.

        """
        if self._factory is not None:
            raise NotImplementedError(self._execution_error("entry"))

        return self.value

    async def aopen(self) -> ResolvedValue[T]:
        """
        Resolves this resource's value for an async parser.

        Returns:

            The wrapped value.

        Raises:

            NotImplementedError: When the resource is a factory/lifecycle
                declaration; the execution layer enters it instead.

        """
        if self._factory is not None:
            raise NotImplementedError(self._execution_error("entry"))

        return self.value

    def close(self, value: T) -> None:
        """
        Closes an owned ``handle``.

        A ``cleanup`` override supplies the return value; otherwise the value's own
        ``close()`` is invoked for its side effect and ``None`` is returned. An
        external resource is a caller-owned no-op.

        Args:

            value: The resource value to close.

        Raises:

            NotImplementedError: When the resource is a factory/lifecycle
                declaration; the execution layer tears it down instead.

        """
        if self._factory is not None:
            raise NotImplementedError(self._execution_error("teardown"))
        elif self._external or self._cleanup is False:
            pass
        elif self._cleanup is None:
            cast("SyncCloseable", value).close()
        else:
            self._cleanup(value)

    async def aclose(self, value: T) -> None:
        """
        Closes an owned ``handle`` preferring ``aclose()`` then ``close()``.

        A ``cleanup`` override supplies the return value; otherwise the value's own
        ``aclose()``/``close()`` is invoked for its side effect. An external
        resource is a caller-owned no-op.

        Args:

            value: The resource value to close.

        Raises:

            NotImplementedError: When the resource is a factory/lifecycle
                declaration; the execution layer tears it down instead.

        """
        if self._factory is not None:
            raise NotImplementedError(self._execution_error("teardown"))
        elif self._external or self._cleanup is False:
            pass
        elif self._cleanup is not None:
            await maybe_deferred(self._cleanup, value)
        elif is_async_closeable(value):
            await value.aclose()
        else:
            cast("SyncCloseable", value).close()


class OneShotResource[T](Resource[T]):
    """A Resource that may only be used once."""

    __slots__ = ()


class ReusableResource[T](Resource[T]):
    """A Resource that may be stored in a reusable Context."""

    __slots__ = ()


__all__ = ["OneShotResource", "Resource", "ReusableResource"]
