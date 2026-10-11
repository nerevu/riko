# vim: sw=4:ts=4:expandtab
"""
Classifies a resource definition into an executable acquisition plan.

A resource declaration arrives as a resolved value, a caller-owned value, a
value-producing factory, or a generator/context-manager lifecycle. The plan
translates each shape into one uniform record: how to acquire the value, whether
entry and teardown are async, and how to tear it down. The execution consumes the
plan and never re-inspects the original declaration.
"""

from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager
from enum import Enum, auto
from typing import TYPE_CHECKING, Literal, cast

from attrs import define, field

from riko.bado._util import maybe_async
from riko.definitions._resources import VALUE_FACTORY_KINDS
from riko.types._collections import thaw
from riko.types._guards import is_async_closeable
from riko.types._resource import FactoryKind
from riko.types._sentinels import MISSING

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable, Generator, Mapping

    from riko.definitions._resource_definition import Resource
    from riko.types._io import SyncCloseable
    from riko.types._resource import AnyContextManager, Cleanup, ValueFactory
    from riko.types._sentinels import MissingType


_ASYNC_KINDS = frozenset(
    {
        FactoryKind.ASYNC_GEN_FACTORY,
        FactoryKind.ASYNC_CM_FACTORY,
        FactoryKind.ASYNC_CONTEXTMANAGER,
    }
)
_CM_FACTORY_KINDS = frozenset(
    {FactoryKind.SYNC_CM_FACTORY, FactoryKind.ASYNC_CM_FACTORY}
)


class _ResourceStrategy(Enum):
    """The acquisition shape a resource plan drives during execution."""

    EXTERNAL = auto()
    OWNED = auto()
    VALUE_FACTORY = auto()
    LIFECYCLE = auto()


@define(frozen=True, slots=True)
class _ResourcePlan[T]:
    """
    An executable acquisition plan derived once from a resource definition.

    Attributes:

        strategy: How the execution acquires and tears down the resource.
        native_async: Whether entry/teardown is async-native rather than sync.
        value: The already-resolved value for external/owned strategies.
        factory: The producer callable for the value-factory strategy.
        args: Positional arguments bound to the factory.
        kwargs: Keyword arguments bound to the factory.
        cleanup: The teardown override: a callable, ``False`` for none, or ``None``
            to close the value itself.
        context_manager: The lifecycle to enter for the lifecycle strategy.

    """

    strategy: _ResourceStrategy
    native_async: bool = False
    value: T | MissingType = MISSING
    factory: ValueFactory[T] | None = None
    args: tuple[object, ...] = ()
    kwargs: Mapping[str, object] = field(factory=dict)
    cleanup: Cleanup[T] | Literal[False] | None = None
    context_manager: AnyContextManager[T] | None = None


def _thaw_arguments[T](
    resource: Resource[T],
) -> tuple[tuple[object, ...], dict[str, object]]:
    """Copies a factory's frozen arguments into mutable ones for a single call."""
    kwargs = {key: thaw(item) for key, item in resource.kwargs.items()}
    return tuple(map(thaw, resource.args)), kwargs


def _build_context_manager[T](
    resource: Resource[T], *args: object, **kwargs: object
) -> AnyContextManager[T]:
    kind = resource.kind
    factory = resource.factory

    if kind is FactoryKind.ASYNC_GEN_FACTORY:
        factory = cast("Callable[..., AsyncGenerator[T, None]]", factory)
        made = asynccontextmanager(factory)
        cm: AnyContextManager[T] = made(*args, **kwargs)
    elif kind is FactoryKind.SYNC_GEN_FACTORY:
        made = contextmanager(cast("Callable[..., Generator[T, None, None]]", factory))
        cm = made(*args, **kwargs)
    elif kind in _CM_FACTORY_KINDS:
        cm = cast("Callable[..., AnyContextManager[T]]", factory)(*args, **kwargs)
    else:
        cm = cast("AnyContextManager[T]", resource.value)

    return cm


def build_resource_plan[T](resource: Resource[T]) -> _ResourcePlan[T]:
    """
    Classifies ``resource`` into a single executable acquisition plan.

    Args:

        resource: The resource definition to acquire.

    Returns:

        A plan carrying the strategy, native mode, and teardown data the
        execution needs to open and close the resource.

    """
    kind = resource.kind
    value = cast("T", resource.value)
    args, kwargs = _thaw_arguments(resource)

    if resource.external:
        plan = _ResourcePlan(_ResourceStrategy.EXTERNAL, value=value)
    elif kind is None:
        plan = _ResourcePlan(
            _ResourceStrategy.OWNED, value=value, cleanup=resource.cleanup
        )
    elif kind in VALUE_FACTORY_KINDS:
        plan = _ResourcePlan(
            _ResourceStrategy.VALUE_FACTORY,
            native_async=kind is FactoryKind.ASYNC_CALLABLE_FACTORY,
            factory=cast("ValueFactory[T]", resource.factory),
            args=args,
            kwargs=kwargs,
            cleanup=resource.cleanup,
        )
    else:
        plan = _ResourcePlan(
            _ResourceStrategy.LIFECYCLE,
            native_async=kind in _ASYNC_KINDS,
            cleanup=resource.cleanup,
            context_manager=_build_context_manager(resource, *args, **kwargs),
        )

    return plan


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


__all__ = ["aclose_resource", "build_resource_plan", "close_resource"]
