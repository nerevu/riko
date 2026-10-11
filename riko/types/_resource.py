"""Resource factory and lifecycle typing contracts."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Awaitable, Callable, Generator
from contextlib import AbstractAsyncContextManager, AbstractContextManager
from enum import StrEnum


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
