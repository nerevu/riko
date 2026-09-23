# vim: sw=4:ts=4:expandtab
"""
Resource factory classification, binding normalization, and resolved resource views.

Attributes:

    VALUE_FACTORY_KINDS: Factory kinds that produce values without providing a
        lifecycle context.

"""

from __future__ import annotations

import copyreg
from collections.abc import Callable, Iterable, Iterator, Mapping
from inspect import unwrap
from types import MappingProxyType
from typing import TYPE_CHECKING, overload

from riko.types._collections import freeze_mapping
from riko.types._guards import (
    is_async_callable,
    is_async_cm_factory,
    is_async_gen_factory,
    is_sync_callable,
    is_sync_cm_factory,
    is_sync_gen_factory,
)
from riko.types._resource import FactoryKind, ResourceFactory

from ._resource_types import BindingLike, ResourcesLike, ReusableResources, Values

if TYPE_CHECKING:
    from riko.types._io import Closeable


def _reduce_mappingproxy(
    proxy: MappingProxyType[object, object],
) -> tuple[
    Callable[[Mapping[object, object]], MappingProxyType[object, object]],
    tuple[dict[object, object]],
]:
    """Reduces a read-only mapping so immutable containers survive pickling."""
    return (freeze_mapping, (dict(proxy),))


copyreg.pickle(MappingProxyType, _reduce_mappingproxy)

VALUE_FACTORY_KINDS = {
    FactoryKind.SYNC_CALLABLE_FACTORY,
    FactoryKind.ASYNC_CALLABLE_FACTORY,
}


def classify_factory[T](
    factory: ResourceFactory[T], lifecycle: bool = True
) -> FactoryKind:
    """
    Classifies a resource factory (owned resource) by its lifecycle shape.

    Narrows an untyped definition at the ``with_resource`` boundary.

    Args:

        factory: A sync/async generator function or a sync/async context manager
            that yields the value, or a callable that produces one.

    Returns:

        The :class:`FactoryKind` describing how the execution layer enters it.

    Raises:

        TypeError: When ``factory`` is neither a generator function, a context
            manager, nor a callable.

    Examples:

        >>> from contextlib import contextmanager
        >>> from riko.definitions._resources import FactoryKind, classify_factory
        >>>
        >>> def db(ctx):
        ...     yield object()
        >>>
        >>> classify_factory(contextmanager(db))
        <FactoryKind.SYNC_CM_FACTORY: 'sync_cm_factory'>
        >>> classify_factory(db, lifecycle=False)
        <FactoryKind.SYNC_GEN_FACTORY: 'sync_gen_factory'>

    """
    candidate = unwrap(factory) if callable(factory) else factory

    if is_async_cm_factory(factory, candidate):
        kind = FactoryKind.ASYNC_CM_FACTORY
    elif is_sync_cm_factory(factory, candidate):
        kind = FactoryKind.SYNC_CM_FACTORY
    elif is_async_gen_factory(factory, candidate):
        kind = FactoryKind.ASYNC_GEN_FACTORY
    elif is_sync_gen_factory(factory, candidate):
        kind = FactoryKind.SYNC_GEN_FACTORY
    elif lifecycle:
        raise TypeError(
            f"Invalid lifecycle factory: {type(factory)}. Expected a generator or "
            "context manager factory."
        )
    elif is_async_callable(factory):
        kind = FactoryKind.ASYNC_CALLABLE_FACTORY
    elif is_sync_callable(factory):
        kind = FactoryKind.SYNC_CALLABLE_FACTORY
    else:
        raise TypeError(
            f"Invalid resource factory: {type(factory)}. Expected a generator or "
            "context manager factory, or callable."
        )

    return kind


@overload
def resolve_binding(  # noqa: E704
    raw: BindingLike,
) -> ResourcesLike: ...
@overload
def resolve_binding(raw: None) -> None: ...  # noqa: E704
def resolve_binding(  # noqa: E302
    raw: BindingLike | None,
) -> ResourcesLike | None:
    """
    Narrows an untyped decoration option into a resource binding, or ``None``.

    Args:

        raw: The ``resources`` value pulled from a module's opts.

    Returns:

        A ``ResourcesLike`` representation of raw, or ``None`` when unset.

    Raises:

        TypeError: When ``raw`` is neither a string, mapping, nor iterable.

    Examples:

        >>> from riko.definitions._resources import resolve_binding
        >>>
        >>> resolve_binding("client")
        'client'
        >>> resolve_binding(["db", "cache"])
        ['db', 'cache']
        >>> resolve_binding(None)

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


def normalize_resources(resources: ResourcesLike) -> Mapping[str, str]:
    """
    Normalizes a declared binding into local-alias-to-Context-name form.

    Args:

        resources: A bare name, an iterable of names (each bound to itself), or
            an explicit local-to-Context mapping.

    Returns:

        An immutable mapping of local alias to Context resource name.

    Examples:

        >>> from riko.definitions._resources import normalize_resources
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

    return freeze_mapping(binding)


class ResourceView(Mapping[str, object]):
    """
    An execution-bound mapping of resolved resources by local binding name.

    Attribute access is a convenience for names that do not conflict with the mapping
    interface attributes/methods::

        resources.db

    Item access is authoritative and supports every resource name (including those
    that conflict with the mapping interface)::

        resources["items"]

    Args:

        values: Resolved resource values keyed by their local binding names.

    Examples:

        >>> from riko.runtime._resources import Resource
        >>>
        >>> resource = Resource.from_external(object())
        >>> resource.external
        True
        >>> resource.reusable
        True
        >>> view = ResourceView({"db": resource.open()})
        >>> view.db is view["db"]
        True
        >>> "db" in view
        True
        >>> value = object()
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
    under that alias. All name validation completes before any resource is opened:
    a missing binding raises before a single sibling is acquired, so a name error
    never leaves a partially opened view behind.

    Args:

        binding: The node's declared resource binding.
        resources: The Context's resource definitions (keyed by Context name).

    Returns:

        A view exposing each resource value under its local alias.

    Raises:

        TypeError: When a binding names a resource absent from ``resources``;
            all declared bindings are required.

        NotImplementedError: When a resolved resource is owned (owned-resource
            lifecycle is deferred to the execution layer, so supply it as an
            ``external`` resource for now).

    Examples:

        >>> from riko.definitions._resources import bind_resources
        >>> from riko.runtime._resources import Resource
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
    "ResourceFactory",
    "ResourceView",
    "ResourcesLike",
    "bind_resources",
    "classify_factory",
    "normalize_resources",
    "resolve_binding",
]
