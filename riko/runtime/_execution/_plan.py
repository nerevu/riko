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

from riko.definitions._resources import VALUE_FACTORY_KINDS
from riko.types._resource import FactoryKind
from riko.types._sentinels import MISSING

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable, Generator, Mapping

    from riko.runtime._resources import Resource
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
        resource: The originating definition, retained for native teardown.
        native_async: Whether entry/teardown is async-native rather than sync.
        value: The already-resolved value for external/owned strategies.
        factory: The producer callable for the value-factory strategy.
        args: Positional arguments bound to the factory.
        kwargs: Keyword arguments bound to the factory.
        cleanup: The teardown callable, ``False`` for none, for value factories.
        context_manager: The lifecycle to enter for the lifecycle strategy.

    """

    strategy: _ResourceStrategy
    resource: Resource[T]
    native_async: bool = False
    value: T | MissingType = MISSING
    factory: ValueFactory[T] | None = None
    args: tuple[object, ...] = ()
    kwargs: Mapping[str, object] = field(factory=dict)
    cleanup: Cleanup[T] | Literal[False] | None = None
    context_manager: AnyContextManager[T] | None = None


def _build_context_manager[T](resource: Resource[T]) -> AnyContextManager[T]:
    kind = resource.kind
    args = resource.args
    kwargs = resource.kwargs
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

    if resource.external:
        plan = _ResourcePlan(_ResourceStrategy.EXTERNAL, resource, value=value)
    elif kind is None:
        plan = _ResourcePlan(_ResourceStrategy.OWNED, resource, value=value)
    elif kind in VALUE_FACTORY_KINDS:
        plan = _ResourcePlan(
            _ResourceStrategy.VALUE_FACTORY,
            resource,
            native_async=kind is FactoryKind.ASYNC_CALLABLE_FACTORY,
            factory=cast("ValueFactory[T]", resource.factory),
            args=resource.args,
            kwargs=resource.kwargs,
            cleanup=resource.cleanup,
        )
    else:
        plan = _ResourcePlan(
            _ResourceStrategy.LIFECYCLE,
            resource,
            native_async=kind in _ASYNC_KINDS,
            context_manager=_build_context_manager(resource),
        )

    return plan


__all__ = ["build_resource_plan"]
