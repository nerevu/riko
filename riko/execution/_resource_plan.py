# vim: sw=4:ts=4:expandtab
"""
Plans one acquisition of a resource definition and closes owned resource values.

A resource declaration arrives as a resolved value, a caller-owned value, a value-
producing factory, or a generator/context-manager lifecycle. The plan adds what one
acquisition needs: fresh factory arguments, the factory call or context manager to
enter, and whether teardown is async.
"""

from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager
from functools import cached_property
from typing import TYPE_CHECKING, Literal, cast

from attrs import define

from riko.bado._util import maybe_async
from riko.types._collections import thaw
from riko.types._guards import is_async_callable
from riko.types._io import is_async_closeable, is_sync_closeable
from riko.types._resource import FactoryKind, ResourceStrategy

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Callable, Generator

    from riko.definitions._resource_definition import ResolvedValue, Resource
    from riko.types._io import SyncCloseable
    from riko.types._resource import AnyContextManager, Cleanup, ValueFactory


def _is_async_only_closeable(value: object) -> bool:
    """Tells whether ``value`` closes only through an async ``aclose``."""
    return is_async_closeable(value) and not is_sync_closeable(value)


@define(frozen=True, slots=True)
class _ResourcePlan[T]:
    """
    One acquisition of a resource definition, as the execution drives it.

    The definition classifies itself. The plan adds the per-acquisition work: fresh
    copies of the factory arguments, the factory call, and the context manager a
    lifecycle enters.

    Attributes:

        resource: The resource definition to acquire.

    """

    resource: Resource[T]

    @property
    def strategy(self) -> ResourceStrategy:
        """How the execution acquires and tears down the resource."""
        return self.resource.strategy

    @property
    def async_native(self) -> bool:
        """Whether production or entry is async-native rather than sync."""
        return self.resource.async_native

    @property
    def value(self) -> ResolvedValue[T]:
        """The already-resolved value an external or owned resource carries."""
        return self.resource.value

    @property
    def cleanup(self) -> Cleanup[T] | Literal[False] | None:
        """The teardown override: a callable, ``False`` for none, or ``None``."""
        return self.resource.cleanup

    @cached_property
    def arguments(self) -> tuple[tuple[object, ...], dict[str, object]]:
        """Mutable copies of the factory's frozen arguments for one call."""
        resource = self.resource
        kwargs = {key: thaw(item) for key, item in resource.kwargs.items()}
        return tuple(map(thaw, resource.args)), kwargs

    @cached_property
    def is_teardown_async(self) -> bool:
        """Whether tearing the resource down needs the event loop."""
        strategy = self.strategy
        cleanup = self.cleanup

        if strategy is ResourceStrategy.LIFECYCLE:
            is_async = self.async_native
        elif strategy is ResourceStrategy.EXTERNAL:
            is_async = False
        elif strategy is ResourceStrategy.OWNED and cleanup is None:
            is_async = _is_async_only_closeable(self.value)
        else:
            is_async = is_async_callable(cleanup)

        return is_async

    def call_factory(self) -> T | Awaitable[T]:
        """
        Calls a value factory with fresh copies of its arguments.

        Returns:

            The factory's result, which an async factory leaves to be awaited.

        """
        factory = cast("ValueFactory[T]", self.resource.factory)
        args, kwargs = self.arguments
        return factory(*args, **kwargs)

    def build_context_manager(self) -> AnyContextManager[T]:
        """
        Builds the context manager a lifecycle resource enters.

        A factory is called with fresh copies of its arguments. A failing call surfaces
        when the execution enters the resource.

        Returns:

            The sync or async context manager to enter.

        """
        resource = self.resource
        kind = resource.kind
        factory = resource.factory
        args, kwargs = self.arguments

        if kind is FactoryKind.ASYNC_GEN_FACTORY:
            factory = cast("Callable[..., AsyncGenerator[T, None]]", factory)
            cm: AnyContextManager[T] = asynccontextmanager(factory)(*args, **kwargs)
        elif kind is FactoryKind.SYNC_GEN_FACTORY:
            factory = cast("Callable[..., Generator[T, None, None]]", factory)
            cm = contextmanager(factory)(*args, **kwargs)
        elif kind is not None and kind.is_cm_factory:
            cm = cast("Callable[..., AnyContextManager[T]]", factory)(*args, **kwargs)
        else:
            cm = cast("AnyContextManager[T]", factory)

        return cm


def close_resource[T](cleanup: Cleanup[T] | Literal[False] | None, value: T) -> None:
    """
    Closes an owned resource's value.

    A ``cleanup`` override is called with the value, ``False`` leaves the value
    open, and ``None`` invokes the value's own ``close()``.

    Args:

        cleanup: The resource's teardown override.
        value: The resource value to close.

    Examples:

        >>> class Client:
        ...     closed = False
        ...     def close(self):
        ...         self.closed = True
        >>>
        >>> closed, kept = Client(), Client()
        >>> close_resource(None, closed)
        >>> close_resource(False, kept)
        >>> closed.closed, kept.closed
        (True, False)

    """
    if cleanup is False:
        pass
    elif cleanup is None:
        cast("SyncCloseable", value).close()
    else:
        cleanup(value)


async def aclose_resource[T](
    cleanup: Cleanup[T] | Literal[False] | None, value: T
) -> None:
    """
    Closes an owned resource's value with a preference of ``aclose()`` over ``close()``.

    A ``cleanup`` override is called (and awaited when async) with the value,
    ``False`` leaves the value open, and ``None`` invokes the value's own
    ``aclose()`` or ``close()``.

    Args:

        cleanup: The resource's teardown override.
        value: The resource value to close.

    """
    if cleanup is False:
        pass
    elif cleanup is not None:
        await maybe_async(cleanup, value)
    elif is_async_closeable(value):
        await value.aclose()
    else:
        cast("SyncCloseable", value).close()


__all__ = ["aclose_resource", "close_resource"]
