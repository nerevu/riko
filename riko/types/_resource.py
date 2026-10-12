# vim: sw=4:ts=4:expandtab
"""
Resource factory and lifecycle typing contracts, classification, and guards.

A lifecycle factory is a generator function or context manager factory whose value
lives between setup and teardown; a value factory is a plain callable that returns
the value.

Attributes:

    VALUE_FACTORY_KINDS: Factory kinds that produce values without providing a
        lifecycle context.

"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Awaitable, Callable, Generator
from contextlib import AbstractAsyncContextManager, AbstractContextManager
from enum import StrEnum
from inspect import isasyncgenfunction, isgeneratorfunction, unwrap
from typing import TypeGuard

from typing_extensions import TypeIs

from ._guards import is_async_callable, is_sync_callable


class FactoryKind(StrEnum):
    """
    The lifecycle shape of an owned resource definition.

    Attributes:

        SYNC_GEN_FACTORY: A sync generator function (setup, ``yield`` value,
            teardown).
        ASYNC_GEN_FACTORY: An async generator function.
        SYNC_CM_FACTORY: A callable returning a sync context manager, such as a
            ``@contextmanager`` function.
        ASYNC_CM_FACTORY: A callable returning an async context manager, such as an
            ``@asynccontextmanager`` function.
        SYNC_CALLABLE_FACTORY: A plain sync callable that returns the value.
        ASYNC_CALLABLE_FACTORY: A plain async function that returns the value.
        SYNC_CONTEXTMANAGER: A sync context-manager instance, entered as is.
        ASYNC_CONTEXTMANAGER: An async context-manager instance, entered as is.

    """

    SYNC_GEN_FACTORY = "sync_gen_factory"
    ASYNC_GEN_FACTORY = "async_gen_factory"
    SYNC_CM_FACTORY = "sync_cm_factory"
    ASYNC_CM_FACTORY = "async_cm_factory"
    SYNC_CALLABLE_FACTORY = "sync_callable_factory"
    ASYNC_CALLABLE_FACTORY = "async_callable_factory"
    SYNC_CONTEXTMANAGER = "sync_contextmanager"
    ASYNC_CONTEXTMANAGER = "async_contextmanager"


VALUE_FACTORY_KINDS = {
    FactoryKind.SYNC_CALLABLE_FACTORY,
    FactoryKind.ASYNC_CALLABLE_FACTORY,
}

type ValueFactory[T] = Callable[..., T | Awaitable[T]]
type GeneratorFactory[T] = Callable[
    ..., Generator[T, None, None] | AsyncGenerator[T, None]
]
type AnyContextManager[T] = AbstractContextManager[T] | AbstractAsyncContextManager[T]
type ContextManagerFactory[T] = Callable[..., AnyContextManager[T]]
type LifecycleFactory[T] = GeneratorFactory[T] | ContextManagerFactory[T]
type ResourceFactory[T] = LifecycleFactory[T] | ValueFactory[T]
type LifecycleValue[T] = AnyContextManager[T]
type Cleanup[T] = Callable[[T], Awaitable[None] | None]


def _resolve_candidate(val: object, candidate: object = None) -> object:
    """Unwraps a decorated callable so a guard inspects the function it wraps."""
    return (unwrap(val) if callable(val) else val) if candidate is None else candidate


def is_sync_gen_factory(
    val: object, candidate: object = None
) -> TypeGuard[Callable[..., Generator]]:
    candidate = _resolve_candidate(val, candidate)
    return candidate is val and isgeneratorfunction(val)


def is_async_gen_factory(
    val: object, candidate: object = None
) -> TypeGuard[Callable[..., AsyncGenerator]]:
    candidate = _resolve_candidate(val, candidate)
    return candidate is val and isasyncgenfunction(val)


def is_sync_context_manager(
    val: object, candidate: object = None
) -> TypeIs[AbstractContextManager]:
    candidate = _resolve_candidate(val, candidate)
    return candidate is val and isinstance(val, AbstractContextManager)


def is_async_context_manager(
    val: object, candidate: object = None
) -> TypeIs[AbstractAsyncContextManager]:
    candidate = _resolve_candidate(val, candidate)
    return candidate is val and isinstance(val, AbstractAsyncContextManager)


def is_sync_cm_factory(
    val: object, candidate: object = None
) -> TypeGuard[Callable[..., AbstractContextManager]]:
    candidate = _resolve_candidate(val, candidate)
    return candidate is not val and isgeneratorfunction(candidate)


def is_async_cm_factory(
    val: object, candidate: object = None
) -> TypeGuard[Callable[..., AbstractAsyncContextManager]]:
    candidate = _resolve_candidate(val, candidate)
    return candidate is not val and isasyncgenfunction(candidate)


def is_context_manager(
    val: object, candidate: object = None
) -> TypeIs[AnyContextManager]:
    candidate = _resolve_candidate(val, candidate)

    if candidate is val:
        result = isinstance(val, (AbstractContextManager, AbstractAsyncContextManager))
    else:
        result = False

    return result


def is_lifecycle_factory(
    val: object, candidate: object = None
) -> TypeGuard[LifecycleFactory]:
    """
    Detects a factory that manages a lifecycle around the value it yields.

    Args:

        val: The value to test, usually a resource factory.
        candidate: The callable to inspect in place of ``val``, when a wrapper has
            already been unwrapped.

    Returns:

        Whether ``val`` is a sync or async generator function, including one wrapped
        by ``contextmanager``/``asynccontextmanager``.

    Examples:

        >>> from contextlib import contextmanager
        >>> from riko.types._resource import is_lifecycle_factory
        >>>
        >>> @contextmanager
        ... def connect(ctx):
        ...     yield object()
        >>>
        >>> is_lifecycle_factory(connect), is_lifecycle_factory(object())
        (True, False)

    """
    candidate = _resolve_candidate(val, candidate)
    return isasyncgenfunction(candidate) or isgeneratorfunction(candidate)


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
        >>> from riko.types._resource import FactoryKind, get_factory_kind
        >>>
        >>> def db(ctx):
        ...     yield object()
        >>>
        >>> get_factory_kind(contextmanager(db))
        <FactoryKind.SYNC_CM_FACTORY: 'sync_cm_factory'>
        >>> get_factory_kind(db, lifecycle=False)
        <FactoryKind.SYNC_GEN_FACTORY: 'sync_gen_factory'>

    """
    candidate = _resolve_candidate(factory)

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
