# vim: sw=4:ts=4:expandtab
"""
riko.resources
~~~~~~~~~~~~~~

Execution resources for a pipeline (PRIVATE).

A ``Resource`` is an immutable definition of an external dependency (e.g., an HTTP
client, database session, credential-backed provider handle). riko owns the
lifecycle of an owned resource and opens it during execution preparation. An
``external`` resource is supplied by the caller and never closed by riko. A
``ResourceView`` is the execution-bound mapping of resolved handles passed to
parsers.

This is the thin slice covering owned/external resources, sync/async open and close,
the execution-bound view, and binding normalization. Lazy opening, ``from_factory``
dependency graphs, and cross-mode bridging remain deferred.

Examples:

    Basic usage::

        >>> from riko.resources import Resource, ResourceView
        >>>
        >>> resource = Resource.from_external(object())
        >>> resource.external
        True
        >>> resource.reusable
        True
        >>> view = ResourceView({"db": resource.open()})
        >>> view.db is view["db"]
        True

"""

from collections.abc import Iterable, Iterator, Mapping
from inspect import unwrap
from types import MappingProxyType
from typing import Literal, Never, Self, cast, overload
from warnings import warn

from riko.bado._util import maybe_deferred
from riko.types._guards import (
    is_async_callable,
    is_async_closeable,
    is_async_cm_factory,
    is_async_context_manager,
    is_async_gen_factory,
    is_closeable,
    is_context_manager,
    is_lifecycle_factory,
    is_sync_callable,
    is_sync_cm_factory,
    is_sync_context_manager,
    is_sync_gen_factory,
)
from riko.types._io import Closeable, SyncCloseable
from riko.types._resource import (
    AnyContextManager,
    Cleanup,
    LifecycleFactory,
    ResolvedValue,
    ResourceFactory,
    ResourcesLike,
    ReusableResources,
    ValueFactory,
    Values,
    _FactoryKind,
)
from riko.warnings import ResourceInterpretationWarning

VALUE_FACTORY_KINDS = {
    _FactoryKind.SYNC_CALLABLE_FACTORY,
    _FactoryKind.ASYNC_CALLABLE_FACTORY,
}


def classify_factory[T](
    factory: ResourceFactory[T], lifecycle: bool = True
) -> _FactoryKind:
    """
    Classifies a resource factory (owned resource) by its lifecycle shape.

    Narrows an untyped definition at the ``with_resource`` boundary.

    Args:

        factory: A sync/async generator function or a sync/async context manager
            that yields the value, or a callable that produces one.

    Returns:

        The :class:`_FactoryKind` describing how the execution layer enters it.

    Raises:

        TypeError: When ``factory`` is neither a generator function, a context
            manager, nor a callable.

    Examples:

        >>> from contextlib import contextmanager
        >>> from riko.resources import _FactoryKind, classify_factory
        >>>
        >>> def db(ctx):
        ...     yield object()
        >>>
        >>> classify_factory(contextmanager(db))
        <_FactoryKind.SYNC_CM_FACTORY: 'sync_cm_factory'>
        >>> classify_factory(db, lifecycle=False)
        <_FactoryKind.SYNC_GEN_FACTORY: 'sync_gen_factory'>

    """
    candidate = unwrap(factory) if callable(factory) else factory

    if is_async_cm_factory(factory, candidate):
        kind = _FactoryKind.ASYNC_CM_FACTORY
    elif is_sync_cm_factory(factory, candidate):
        kind = _FactoryKind.SYNC_CM_FACTORY
    elif is_async_gen_factory(factory, candidate):
        kind = _FactoryKind.ASYNC_GEN_FACTORY
    elif is_sync_gen_factory(factory, candidate):
        kind = _FactoryKind.SYNC_GEN_FACTORY
    elif lifecycle:
        raise TypeError(
            f"Invalid lifecycle factory: {type(factory)}. Expected a generator or "
            "context manager factory."
        )
    elif is_async_callable(factory):
        kind = _FactoryKind.ASYNC_CALLABLE_FACTORY
    elif is_sync_callable(factory):
        kind = _FactoryKind.SYNC_CALLABLE_FACTORY
    else:
        raise TypeError(
            f"Invalid resource factory: {type(factory)}. Expected a generator or "
            "context manager factory, or callable."
        )

    return kind


def normalize_resources(resources: ResourcesLike) -> Mapping[str, str]:
    """
    Normalizes a declared binding into local-alias-to-Context-name form.

    Args:

        resources: A bare name, an iterable of names (each bound to itself), or
            an explicit local-to-Context mapping.

    Returns:

        An immutable mapping of local alias to Context resource name.

    Examples:

        >>> from riko.resources import normalize_resources
        >>>
        >>> normalize_resources(["db", "cache"])
        mappingproxy({'db': 'db', 'cache': 'cache'})
        >>> normalize_resources({"db": "primary_db"})
        mappingproxy({'db': 'primary_db'})

    """
    if isinstance(resources, str):
        binding = {resources: resources}
    elif isinstance(resources, Mapping):
        binding = dict(resources)
    else:
        binding = {name: name for name in resources}

    return MappingProxyType(binding)


def coerce_binding(raw: object) -> ResourcesLike | None:
    """
    Narrows an untyped decoration option into a resource binding, or ``None``.

    Args:

        raw: The ``resources`` value pulled from a module's opts .

    Returns:

        A ``ResourcesLike`` representation of raw, or ``None`` when unset.

    Raises:

        TypeError: When ``raw`` is neither a string, mapping, nor iterable.

    Examples:

        >>> from riko.resources import coerce_binding
        >>>
        >>> coerce_binding("client")
        'client'
        >>> coerce_binding(["db", "cache"])
        ['db', 'cache']
        >>> coerce_binding(None)

    """
    if raw is None:
        binding: ResourcesLike | None = None
    elif isinstance(raw, str):
        binding = raw
    elif isinstance(raw, Mapping):
        binding = {str(key): str(value) for key, value in raw.items()}
    elif isinstance(raw, Iterable):
        binding = [str(name) for name in raw]
    else:
        raise TypeError(f"invalid 'resources' binding: {raw!r}")

    return binding


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

        >>> from riko.resources import Resource
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

    _external: bool = False
    _reusable: bool = False
    kind: _FactoryKind | None = None

    @overload
    def __new__(  # noqa: E704
        cls,  # _OwnedResource
        value: Closeable,
        *,
        cleanup: Cleanup[T] | None = ...,
        credential: str | None = ...,
        lazy: bool = ...,
    ) -> "OneShotResource[T]": ...
    @overload  # noqa: E301
    def __new__(  # noqa: E704
        cls,  # _FactoryResource
        value: ResourceFactory[T],
        *args: object,
        cleanup: Cleanup[T] | Literal[False] | None = ...,
        credential: str | None = ...,
        lazy: bool = ...,
        **kwargs: object,
    ) -> "ReusableResource[T]": ...
    @overload  # noqa: E301
    def __new__(  # noqa: E704
        cls,  # _OwnedResource
        value: ResolvedValue[T],
        *,
        cleanup: Cleanup[T] | Literal[False],
        credential: str | None = ...,
        lazy: bool = ...,
    ) -> "OneShotResource[T]": ...
    @overload  # noqa: E301
    def __new__(  # noqa: E704
        cls,  # _LifecycleResource
        value: LifecycleFactory[T] | AnyContextManager[T],
        *,
        credential: str | None = ...,
        lazy: bool = ...,
    ) -> "OneShotResource[T]": ...
    @overload  # noqa: E301
    def __new__(  # noqa: E704
        cls,  # _ExternalResource
        value: ResolvedValue[T],
    ) -> "ReusableResource[T]": ...
    def __new__(  # noqa: E301
        cls, *_: object, **_kw: object
    ) -> "OneShotResource[T] | ReusableResource[T]":
        cls_ = _OwnedResource if cls is Resource else cls

        if cls_ in {_OwnedResource, _LifecycleResource}:
            obj = cast(OneShotResource, object.__new__(cls_))
        else:
            obj = cast(ReusableResource, object.__new__(cls_))

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
        self.value = value
        self.credential = credential
        self.lazy = lazy
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
    def external(self) -> bool:
        return self._external

    @property
    def reusable(self) -> bool:
        return self._reusable

    @overload
    @classmethod
    def from_factory(  # noqa: E704
        cls,
        factory: ValueFactory[T],
        *args: object,
        cleanup: Cleanup[T] | Literal[False],
        credential: str | None = ...,
        lazy: bool = ...,
        **kwargs: object,
    ) -> "ReusableResource[T]": ...
    @overload  # noqa: E301
    @classmethod
    def from_factory(  # noqa: E704
        cls,
        factory: LifecycleFactory[T],
        *args: object,
        cleanup: None = ...,
        credential: str | None = ...,
        lazy: bool = ...,
        **kwargs: object,
    ) -> "ReusableResource[T]": ...
    @classmethod  # noqa: E301
    def from_factory(
        cls,
        factory: ResourceFactory[T],
        *args: object,
        cleanup: Cleanup[T] | Literal[False] | None = None,
        credential: str | None = None,
        lazy: bool = False,
        **kwargs: object,
    ) -> "ReusableResource[T]":
        """
        The alternate form of ``Context.with_resource(name, factory)``
        """
        return _FactoryResource[T](
            factory, *args, cleanup=cleanup, credential=credential, lazy=lazy, **kwargs
        )

    @overload
    @classmethod
    def from_external(cls, value: "Resource[T]") -> Never: ...  # noqa: E704
    @overload
    @classmethod
    def from_external(cls, value: LifecycleFactory[T]) -> Never: ...  # noqa: E704
    @overload
    @classmethod
    def from_external(cls, value: AnyContextManager[T]) -> Never: ...  # noqa: E704
    @overload  # noqa: E301
    @classmethod
    def from_external(  # noqa: E704
        cls, value: ResolvedValue[T]
    ) -> "ReusableResource[T]": ...
    @classmethod  # noqa: E301
    def from_external(  # pyright: ignore[reportInconsistentOverload]
        cls, value: ResolvedValue[T]
    ) -> "ReusableResource[T]":
        """
        Creates a resource whose lifecycle remains owned by the caller.

        Args:

            value: The resolved external value.

        Returns:

            A resource that always resolves to ``value`` and never closes it.

        """
        return _ExternalResource[T](value)

    @classmethod
    def from_lifecycle(
        cls,
        factory: LifecycleFactory[T] | AnyContextManager[T],
        *,
        credential: str | None = None,
        lazy: bool = False,
    ) -> "OneShotResource[T]":
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

            >>> from riko.resources import OneShotResource, Resource, _FactoryKind
            >>>
            >>> def db():
            ...     yield object()
            >>>
            >>> resource = Resource.from_lifecycle(db, credential="microsoft/cif")
            >>> isinstance(resource, OneShotResource)
            True
            >>> resource.kind
            <_FactoryKind.SYNC_GEN_FACTORY: 'sync_gen_factory'>
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
            cast(SyncCloseable, value).close()
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
            cast(SyncCloseable, value).close()


class OneShotResource[T](Resource[T]):
    """A Resource that may only be used once."""


class ReusableResource[T](Resource[T]):
    """A Resource that may be stored in a reusable Context."""

    _reusable: bool = True


class _OwnedResource[T](OneShotResource[T]):
    pass


class _LifecycleResource[T](OneShotResource[T]):
    """
    An owned resource declared as a generator/context-manager definition.

    Entering (setup / ``yield`` / teardown) belongs to the execution layer. So
    ``open``/``aopen``/``close``/``aclose`` raise ``NotImplementedError``.

    Attributes:

        factory: The generator/context-manager that yields the value.
        kind: The :class:`_FactoryKind` describing the factory's lifecycle shape.
        credential: A credential reference resolved by the connector layer.
        lazy: Whether entry is deferred until first use (validated eagerly regardless).

    Examples:

        >>> from riko.resources import _LifecycleResource, _FactoryKind
        >>>
        >>> def db():
        ...     yield object()
        >>>
        >>> resource = _LifecycleResource(db)
        >>> resource.kind
        <_FactoryKind.SYNC_GEN_FACTORY: 'sync_gen_factory'>
        >>> resource.external
        False
        >>> resource.reusable
        False

    """

    def __init__(
        self,
        factory: LifecycleFactory[T] | AnyContextManager[T],
        *,
        credential: str | None = None,
        lazy: bool = False,
    ) -> None:
        self.factory = factory
        self.credential = credential
        self.lazy = lazy
        self._cleanup = None

        if is_sync_context_manager(factory):
            self.kind = _FactoryKind.SYNC_CONTEXTMANAGER
            self.value = factory
        elif is_async_context_manager(factory):
            self.kind = _FactoryKind.ASYNC_CONTEXTMANAGER
            self.value = factory
        else:
            self.kind = classify_factory(factory)
            self.value = factory()

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

        >>> from riko.resources import Resource
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

    _external: bool = True

    def close(self, value: T) -> None:
        return None

    async def aclose(self, value: T) -> None:
        return None


class _FactoryResource[T](ReusableResource[T]):
    """
    Constructed by :meth:`riko.context.Context.with_resource` when given a generator
    function or context manager rather than a resource value. ``with_resource`` stores
    the factory, but does **not** enter into it. Entering (setup / ``yield`` / teardown)
    belongs to the execution layer. So ``open``/``aopen``/``close``/``aclose`` raise
    ``NotImplementedError``.
    """

    def __init__(  # noqa: E301
        self,
        factory: ResourceFactory[T],
        *args: object,
        cleanup: Cleanup[T] | Literal[False] | None = None,
        credential: str | None = None,
        lazy: bool = False,
        **kwargs: object,
    ) -> None:
        self.factory = factory
        self.kind = classify_factory(factory, lifecycle=False)
        self.args = args
        self.kwargs = kwargs
        self.credential = credential
        self.lazy = lazy
        self._cleanup = cleanup

        if self.kind in VALUE_FACTORY_KINDS:
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


class ResourceView(Mapping[str, object]):
    """
    An execution-bound mapping of resolved resources by local binding name.

    Attribute access is a convenience for names that do not conflict with the mapping
    interface attributes/methods::

        resources.db

    Item access is authoritative and supports every resource name (including those
    that conflict with the mapping interface)::

        resources["items"]

    Examples:

        >>> from riko.resources import ResourceView
        >>>
        >>> value = object()
        >>> view = ResourceView({"db": value})
        >>> view.db is view["db"] is value
        True
        >>> "db" in view
        True
        >>> reserved = ResourceView({"keys": value})
        >>> reserved["keys"] is value
        True
        >>> reserved.keys is value
        False

    """

    __slots__ = ("_values",)

    def __init__(self, values: Values) -> None:
        self._values = dict(values)

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __getattr__(self, name: str) -> object | Closeable:
        if name not in self._values:
            raise AttributeError(name)

        return self._values[name]

    def __getitem__(self, name: str) -> object | Closeable:
        return self._values[name]

    def __contains__(self, name: object) -> bool:
        return name in self._values


def bind_resources(
    binding: ResourcesLike, resources: ReusableResources
) -> ResourceView:
    """
    Opens a node's declared ``binding`` against the Context resources.

    Each local name resolves to a Context resource, which is opened and exposed
    under that alias.

    Args:

        binding: The node's declared resource binding.
        resources: The Context's resource definitions (keyed by Context name).

    Returns:

        A view exposing each resource value under its local alias.

    All name validation completes before any resource is opened: a missing binding
    raises before a single sibling is acquired, so a name error never leaves a
    partially opened view behind.

    Raises:

        TypeError: When a binding names a resource absent from ``resources``;
            all declared bindings are required.

        NotImplementedError: When a resolved resource is owned (owned-resource
            lifecycle is deferred to the execution layer, so supply it as an
            ``external`` resource for now).

    Examples:

        >>> from riko.resources import Resource, bind_resources
        >>>
        >>> value = object()
        >>> resources = {"primary": Resource.from_external(value)}
        >>> bind_resources({"value": "primary"}, resources).value is value
        True

    """
    normalized = normalize_resources(binding)
    missing = [name for name in normalized.values() if name not in resources]

    if missing:
        names = ", ".join(repr(name) for name in missing)
        raise TypeError(f"The resource {names} is not bound to the Context")
    else:
        values: Values = {
            local: resources[name].open() for local, name in normalized.items()
        }

    return ResourceView(values)


__all__ = [
    "OneShotResource",
    "Resource",
    "ResourceFactory",
    "ResourceView",
    "ResourcesLike",
    "ReusableResource",
    "bind_resources",
    "classify_factory",
    "coerce_binding",
    "normalize_resources",
]
