# vim: sw=4:ts=4:expandtab
"""
Resource factory classification.

Attributes:

    VALUE_FACTORY_KINDS: Factory kinds that produce values without providing a
        lifecycle context.

"""

from __future__ import annotations

from inspect import unwrap

from riko.types._guards import (
    is_async_callable,
    is_async_cm_factory,
    is_async_gen_factory,
    is_sync_callable,
    is_sync_cm_factory,
    is_sync_gen_factory,
)
from riko.types._resource import FactoryKind, ResourceFactory

VALUE_FACTORY_KINDS = {
    FactoryKind.SYNC_CALLABLE_FACTORY,
    FactoryKind.ASYNC_CALLABLE_FACTORY,
}


def get_factory_kind[T](
    factory: ResourceFactory[T], lifecycle: bool = True
) -> FactoryKind:
    """
    Classifies a resource factory (owned resource) by its lifecycle shape.

    Narrows an untyped definition at the ``with_resource`` boundary.

    Args:

        factory: A sync/async generator function or a sync/async context manager that
            yields the value, or a callable that produces one.

        lifecycle: Whether ``factory`` must manage a lifecycle (a generator or context
            manager factory). When false, a plain callable that returns the value is
            accepted too.

    Returns:

        The :class:`FactoryKind` describing how the execution layer enters it.

    Raises:

        TypeError: When ``factory`` is neither a generator function, a context
            manager, nor a callable.

    Examples:

        >>> from contextlib import contextmanager
        >>> from riko.definitions._resources import FactoryKind, get_factory_kind
        >>>
        >>> def db(ctx):
        ...     yield object()
        >>>
        >>> get_factory_kind(contextmanager(db))
        <FactoryKind.SYNC_CM_FACTORY: 'sync_cm_factory'>
        >>> get_factory_kind(db, lifecycle=False)
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


__all__ = ["ResourceFactory", "get_factory_kind"]
