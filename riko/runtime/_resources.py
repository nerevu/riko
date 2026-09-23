"""Executes owned, external, one-shot, and reusable resource lifecycles."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Never, Self, cast, overload
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

    __slots__ = ("_cleanup", "_credential", "_kind", "_lazy", "_value")

    _external: bool = False
    _reusable: bool = False

    @overload
    def __new__(  # noqa: E704
        cls,  # _OwnedResource
        value: Closeable,
        *,
        cleanup: Cleanup[T] | None = ...,
        credential: str | None = ...,
        lazy: bool = ...,
    ) -> OneShotResource[T]: ...
    @overload  # noqa: E301
    def __new__(  # noqa: E704
        cls,  # _FactoryResource
        value: ResourceFactory[T],
        *args: object,
        cleanup: Cleanup[T] | Literal[False] | None = ...,
        credential: str | None = ...,
        lazy: bool = ...,
        **kwargs: object,
    ) -> ReusableResource[T]: ...
    @overload  # noqa: E301
    def __new__(  # noqa: E704
        cls,  # _OwnedResource
        value: ResolvedValue[T],
        *,
        cleanup: Cleanup[T] | Literal[False],
        credential: str | None = ...,
        lazy: bool = ...,
    ) -> OneShotResource[T]: ...
    @overload  # noqa: E301
    def __new__(  # noqa: E704
        cls,  # _LifecycleResource
        value: LifecycleFactory[T] | AnyContextManager[T],
        *,
        credential: str | None = ...,
        lazy: bool = ...,
    ) -> OneShotResource[T]: ...
    @overload  # noqa: E301
    def __new__(  # noqa: E704
        cls,  # _ExternalResource
        value: ResolvedValue[T],
    ) -> ReusableResource[T]: ...
    def __new__(  # noqa: E301
        cls, *_: object, **_kw: object
    ) -> OneShotResource[T] | ReusableResource[T]:
        cls_ = _OwnedResource if cls is Resource else cls

        if cls_ in {_OwnedResource, _LifecycleResource}:
            obj = cast("OneShotResource", object.__new__(cls_))
        else:
            obj = cast("ReusableResource", object.__new__(cls_))

        return obj

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
    def __init__(  # noqa: E704
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

        if (
            isinstance(value, Resource)
            or is_lifecycle_factory(value)
            or is_context_manager(value)
        ):
            msg = f"Expected a resolved resource value but got a: {type(value)}."
            raise TypeError(msg)
        elif self.external:
            pass
        elif cleanup is None and not is_closeable(value):
            msg = "Must provide a Closeable value or cleanup function for riko owned "
            msg += f"resources. Not a {type(value).__name__}. If this value's lifecycle"
            msg += "is externally managed, use Resource.from_external(...) instead."
            raise TypeError(msg)

    @property
    def value(self) -> ResolvedValue[T]:
        return self._value

    @property
    def credential(self) -> str | None:
        return self._credential

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
        return self._reusable

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
        return _FactoryResource[T](
            factory, *args, cleanup=cleanup, credential=credential, lazy=lazy, **kwargs
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

        """
        return _ExternalResource[T](value)

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
        return _LifecycleResource[T](factory, credential=credential, lazy=lazy)

    def open(self) -> ResolvedValue[T]:
        """
        Resolves this resource's value.

        Returns:

            The wrapped value.

        """
        return self.value

    async def aopen(self) -> ResolvedValue[T]:
        """
        Resolves this resource's value for an async parser.

        Returns:

            The wrapped value.

        """
        return self.value

    def close(self, value: T) -> None:
        """
        Closes an owned ``handle``.

        A ``cleanup`` override supplies the return value; otherwise the value's own
        ``close()`` is invoked for its side effect and ``None`` is returned.

        Args:

            value: The resource value to close.

        Returns:

            The ``cleanup`` result, or ``None`` when there is no override.

        """
        if self._cleanup is False:
            pass
        elif self._cleanup is None:
            cast("SyncCloseable", value).close()
        else:
            self._cleanup(value)

    async def aclose(self, value: T) -> None:
        """
        Closes an owned ``handle`` preferring ``aclose()`` then ``close()``.

        A ``cleanup`` override supplies the return value; otherwise the value's own
        ``aclose()``/``close()`` is invoked for its side effect.

        Args:

            value: The resource value to close.

        Returns:

            The ``cleanup`` result, or ``None`` when there is no override.

        """
        if self._cleanup is False:
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
    _reusable: bool = True


class _OwnedResource[T](OneShotResource[T]):
    __slots__ = ()


class _LifecycleResource[T](OneShotResource[T]):
    """
    An owned resource declared as a generator/context-manager definition.

    Entering (setup / ``yield`` / teardown) belongs to the execution layer. So
    ``open``/``aopen``/``close``/``aclose`` raise ``NotImplementedError``.

    Attributes:

        factory: The generator/context-manager that yields the value.
        kind: The :class:`FactoryKind` describing the factory's lifecycle shape.
        credential: A credential reference resolved by the connector layer.
        lazy: Whether entry is deferred until first use (validated eagerly regardless).

    Examples:

        >>> from riko.runtime._resources import _LifecycleResource, FactoryKind
        >>>
        >>> def db():
        ...     yield object()
        >>>
        >>> resource = _LifecycleResource(db)
        >>> resource.kind
        <FactoryKind.SYNC_GEN_FACTORY: 'sync_gen_factory'>
        >>> resource.external
        False
        >>> resource.reusable
        False

    """

    __slots__ = ("_factory",)

    def __init__(
        self,
        factory: LifecycleFactory[T] | AnyContextManager[T],
        *,
        credential: str | None = None,
        lazy: bool = False,
    ) -> None:
        self._factory = factory
        self._credential = credential
        self._lazy = lazy
        self._cleanup = None

        if is_sync_context_manager(factory):
            self._kind = FactoryKind.SYNC_CONTEXTMANAGER
            self._value = factory
        elif is_async_context_manager(factory):
            self._kind = FactoryKind.ASYNC_CONTEXTMANAGER
            self._value = factory
        else:
            self._kind = classify_factory(factory)
            self._value = factory()

    @property
    def factory(self) -> LifecycleFactory[T] | AnyContextManager[T]:
        return self._factory

    def open(self) -> Never:
        raise NotImplementedError(
            "Lifecycle resource entry belongs to the execution layer; "
            "the generator/context-manager is entered there, not here"
        )

    async def aopen(self) -> Never:
        raise NotImplementedError(
            "Lifecycle resource entry belongs to the execution layer; "
            "the generator/context-manager is entered there, not here"
        )

    def close(self, value: T) -> Never:
        raise NotImplementedError(
            "Lifecycle resource teardown belongs to the execution layer; "
            "it is the generator's post-yield body, not a close() call"
        )

    async def aclose(self, value: T) -> Never:
        raise NotImplementedError(
            "Lifecycle resource teardown belongs to the execution layer; "
            "it is the generator's post-yield body, not an aclose() call"
        )


class _ExternalResource[T](ReusableResource[T]):
    """
    A caller-owned resource that resolves to a fixed value and never closes it.

    ``open``/``aopen`` return the supplied value unchanged (inherited).
    ``close``/``aclose`` are no-ops because the caller owns the lifecycle.

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
        >>> resource.external
        True
        >>> resource.reusable
        True

    """

    __slots__ = ()
    _external: bool = True

    def close(self, value: T) -> None:
        return None

    async def aclose(self, value: T) -> None:
        return None


class _FactoryResource[T](ReusableResource[T]):
    """
    Represent lifecycle factories stored by ``Context.with_resource``.

    This applies to generator functions and context managers rather than resource
    values. ``with_resource`` stores but does not enter the factory; setup,
    ``yield``, and teardown belong to execution. Therefore ``open``, ``aopen``,
    ``close``, and ``aclose`` raise ``NotImplementedError``.
    """

    __slots__ = ("_args", "_factory", "_kwargs")

    def __init__(  # noqa: E301
        self,
        factory: ResourceFactory[T],
        *args: object,
        cleanup: Cleanup[T] | Literal[False] | None = None,
        credential: str | None = None,
        lazy: bool = False,
        **kwargs: object,
    ) -> None:
        self._factory = factory
        self._kind = classify_factory(factory, lifecycle=False)
        self._args = tuple(args)
        self._kwargs = freeze_mapping(kwargs)
        self._credential = credential
        self._lazy = lazy
        self._cleanup = cleanup

        if self._kind in VALUE_FACTORY_KINDS:
            if cleanup is None:
                raise TypeError("ValueFactory requires an explicit cleanup function")
        elif cleanup is not None:
            msg = "Cleanup is not allowed for generator/context-manager factories."
            msg += "use Resource.from_lifecycle(...) instead if you want riko to manage"
            msg += "the lifecycle."
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

    @property
    def factory(self) -> ResourceFactory[T]:
        return self._factory

    @property
    def args(self) -> tuple[object, ...]:
        return self._args

    @property
    def kwargs(self) -> Mapping[str, object]:
        return self._kwargs

    def open(self) -> Never:
        msg = "Factory resource entry belongs to the execution layer"
        raise NotImplementedError(msg)

    async def aopen(self) -> Never:
        msg = "Factory resource entry belongs to the execution layer"
        raise NotImplementedError(msg)

    def close(self, value: T) -> None:
        return None

    async def aclose(self, value: T) -> None:
        return None


__all__ = ["OneShotResource", "Resource", "ReusableResource"]
