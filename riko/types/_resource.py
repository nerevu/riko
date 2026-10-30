# vim: sw=4:ts=4:expandtab
"""
Resource factory contracts, factory guards, and the lifecycle plans an execution drives.

A lifecycle factory is a generator function or context manager factory whose value
lives between setup and cleanup; a value factory is a plain callable that returns
the value. Classifying either produces a resource plan: one record per way an
execution acquires and cleans up a resource, independent of how it was declared.

Examples:

    Basic usage::

        >>> from riko.types import ResourceStrategy
        >>>
        >>> [strategy.name for strategy in ResourceStrategy]
        ['EXTERNAL', 'OWNED', 'VALUE_FACTORY', 'LIFECYCLE']

"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Awaitable, Callable, Generator, Iterator
from contextlib import (
    AbstractAsyncContextManager,
    AbstractContextManager,
    asynccontextmanager,
    contextmanager,
)
from enum import Enum, auto
from functools import partial
from inspect import isasyncgenfunction, isgeneratorfunction, unwrap
from typing import TYPE_CHECKING, Literal, TypeGuard

from attrs import define, field
from typing_extensions import TypeIs

from riko.base._guards import is_async_callable
from riko.base._iterutils import noop

from ._frozendict import FrozenDict, freeze
from ._io import is_async_closeable, is_sync_closeable

if TYPE_CHECKING:
    from types import CodeType

    from ._io import Closeable

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
type ResolvedValue[T] = T | Closeable
type LifecyclePlan[T] = SyncLifecyclePlan[T] | AsyncLifecyclePlan[T]

type ResourcePlan[T] = (
    ExternalPlan[T] | OwnedPlan[T] | ValueFactoryPlan[T] | LifecyclePlan[T]
)

# Every function the decorators build shares their helper's code object, so any
# callable decorated once yields it.
_SYNC_CM_CODE: CodeType = contextmanager(iter).__code__
_ASYNC_CM_CODE: CodeType = asynccontextmanager(aiter).__code__  # pyright: ignore[reportArgumentType, reportCallIssue]


class ResourceStrategy(Enum):
    """The acquisition shape an execution drives for a resource."""

    EXTERNAL = auto()
    OWNED = auto()
    VALUE_FACTORY = auto()
    LIFECYCLE = auto()


def _gen_wrapper_chain(val: object) -> Iterator[object]:
    """Walks ``val`` and each function it wraps."""
    link: object = val

    while link is not None:
        yield link
        link = getattr(link, "__wrapped__", None)


def _is_built_by(val: object, code: CodeType) -> bool:
    """Tells whether ``contextmanager`` or its async twin built ``val`` or its base."""
    chain = _gen_wrapper_chain(val)
    return any(getattr(link, "__code__", None) is code for link in chain)


def _is_sync_cm_factory[T](
    val: LifecycleFactory[T],
) -> TypeGuard[Callable[..., AbstractContextManager[T]]]:
    return _is_built_by(val, _SYNC_CM_CODE)


def _is_async_cm_factory[T](
    val: LifecycleFactory[T],
) -> TypeGuard[Callable[..., AbstractAsyncContextManager[T]]]:
    return _is_built_by(val, _ASYNC_CM_CODE)


def _is_sync_gen_factory[T](
    val: LifecycleFactory[T],
) -> TypeGuard[Callable[..., Generator[T, None, None]]]:
    return isgeneratorfunction(unwrap(val))


def _is_async_gen_factory[T](
    val: LifecycleFactory[T],
) -> TypeGuard[Callable[..., AsyncGenerator[T, None]]]:
    return isasyncgenfunction(unwrap(val))


def _is_sync_context_manager[T](
    val: LifecycleFactory[T] | AnyContextManager[T],
) -> TypeIs[AbstractContextManager[T]]:
    return isinstance(val, AbstractContextManager)


def _is_async_context_manager[T](
    val: LifecycleFactory[T] | AnyContextManager[T],
) -> TypeIs[AbstractAsyncContextManager[T]]:
    return isinstance(val, AbstractAsyncContextManager)


def is_context_manager(val: object) -> TypeIs[AnyContextManager]:
    return isinstance(val, (AbstractContextManager, AbstractAsyncContextManager))


def is_lifecycle_factory(val: object) -> TypeGuard[LifecycleFactory]:
    """
    Detects a factory that manages a lifecycle around the value it yields.

    Args:

        val: The value to test, usually a resource factory.

    Returns:

        Whether ``val`` is a sync or async generator function, including one wrapped
        by ``contextmanager``/``asynccontextmanager`` or another decorator.

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
    candidate = unwrap(val) if callable(val) else val
    return isasyncgenfunction(candidate) or isgeneratorfunction(candidate)


def _is_lifecycle[T](val: ResourceFactory[T]) -> TypeGuard[LifecycleFactory[T]]:
    return is_lifecycle_factory(val)


def _is_value_factory[T](val: ResourceFactory[T]) -> TypeGuard[ValueFactory[T]]:
    return callable(val) and not _is_lifecycle(val)


def _enter_sync_gen[T](
    func: Callable[..., Generator[T, None, None]], /, *args: object, **kwargs: object
) -> AbstractContextManager[T]:
    return contextmanager(func)(*args, **kwargs)


def _enter_async_gen[T](
    func: Callable[..., AsyncGenerator[T, None]], /, *args: object, **kwargs: object
) -> AbstractAsyncContextManager[T]:
    return asynccontextmanager(func)(*args, **kwargs)


@define(frozen=True, slots=True)
class ExternalPlan[T]:
    """
    Hands an execution a caller-owned value it never closes.

    Attributes:

        value: The resolved value.

    """

    value: ResolvedValue[T]

    @property
    def requires_async_cleanup(self) -> bool:
        """Whether cleaning up the resource needs the event loop. Never."""
        return False


@define(frozen=True, slots=True)
class OwnedPlan[T]:
    """
    Hands an execution a resolved value it closes when the execution ends.

    Attributes:

        value: The resolved value.
        cleanup: The cleanup override: a callable, ``False`` for none, or ``None``
            for the value's own ``close()``/``aclose()``.

    """

    value: ResolvedValue[T]
    cleanup: Cleanup[T] | Literal[False] | None = None

    @property
    def requires_async_cleanup(self) -> bool:
        """Whether cleaning up the resource needs the event loop."""
        value = self.value

        if self.cleanup is None:
            is_async = is_async_closeable(value) and not is_sync_closeable(value)
        else:
            is_async = is_async_callable(self.cleanup)

        return is_async

    @property
    def has_async_cleanup(self) -> bool:
        """Whether the resource can clean up natively async."""
        if self.cleanup is None:
            is_async = is_async_closeable(self.value)
        else:
            is_async = is_async_callable(self.cleanup)

        return is_async


@define(frozen=True, slots=True)
class ValueFactoryPlan[T]:
    """
    Calls a factory for the value and hands the value to a cleanup callback.

    Attributes:

        func: The callable that produces the value.
        cleanup: The cleanup callback, or ``False`` for none.
        args: Frozen positional arguments for ``func``.
        kwargs: Frozen keyword arguments for ``func``.

    """

    func: ValueFactory[T]
    cleanup: Cleanup[T] | Literal[False]
    args: tuple[object, ...] = field(default=(), converter=freeze)
    kwargs: FrozenDict[str, object] = field(factory=FrozenDict, converter=FrozenDict)

    @property
    def is_async(self) -> bool:
        """Whether ``func`` is natively async."""
        return is_async_callable(self.func)

    @property
    def requires_async_cleanup(self) -> bool:
        """Whether cleaning up the resource needs the event loop."""
        return is_async_callable(self.cleanup)


@define(frozen=True, slots=True)
class SyncLifecyclePlan[T]:
    """
    Enters a sync context manager for the value and exits it when the execution ends.

    Attributes:

        source: The generator function, context-manager factory, or context manager
            the resource was declared with.

        enter: Builds the context manager from ``args`` and ``kwargs``.
        args: Frozen positional arguments for ``enter``.
        kwargs: Frozen keyword arguments for ``enter``.

    """

    source: object
    enter: Callable[..., AbstractContextManager[T]]
    args: tuple[object, ...] = field(default=(), converter=freeze)
    kwargs: FrozenDict[str, object] = field(factory=FrozenDict, converter=FrozenDict)

    @property
    def requires_async_cleanup(self) -> bool:
        """Whether cleaning up the resource needs the event loop. Never."""
        return False


@define(frozen=True, slots=True)
class AsyncLifecyclePlan[T]:
    """
    Enters an async context manager for the value and exits it when the execution ends.

    Attributes:

        source: The generator function, context-manager factory, or context manager
            the resource was declared with.

        enter: Builds the context manager from ``args`` and ``kwargs``.
        args: Frozen positional arguments for ``enter``.
        kwargs: Frozen keyword arguments for ``enter``.

    """

    source: object
    enter: Callable[..., AbstractAsyncContextManager[T]]
    args: tuple[object, ...] = field(default=(), converter=freeze)
    kwargs: FrozenDict[str, object] = field(factory=FrozenDict, converter=FrozenDict)

    @property
    def requires_async_cleanup(self) -> bool:
        """Whether cleaning up the resource needs the event loop. Always."""
        return True


def build_lifecycle_plan[T](
    factory: LifecycleFactory[T] | AnyContextManager[T],
    /,
    *args: object,
    **kwargs: object,
) -> LifecyclePlan[T]:
    """
    Classifies a lifecycle declaration into the plan an execution enters.

    Args:

        factory: A sync/async generator function, a context-manager factory built
            with ``contextmanager``/``asynccontextmanager``, or a context manager.

        args: Positional arguments for ``factory``.

        kwargs: Keyword arguments for ``factory``.

    Returns:

        The sync or async lifecycle plan.

    Raises:

        TypeError: When ``factory`` is none of those forms.

    Examples:

        >>> from riko.types._resource import build_lifecycle_plan
        >>>
        >>> def db(name):
        ...     yield {"name": name}
        >>>
        >>> plan = build_lifecycle_plan(db, "main")
        >>> type(plan).__name__
        'SyncLifecyclePlan'
        >>> plan.args
        ('main',)

    """
    if _is_sync_context_manager(factory):
        plan: LifecyclePlan[T] = SyncLifecyclePlan(factory, partial(noop, factory))
    elif _is_async_context_manager(factory):
        plan = AsyncLifecyclePlan(factory, partial(noop, factory))
    elif _is_async_cm_factory(factory):
        plan = AsyncLifecyclePlan(factory, factory, args, kwargs)
    elif _is_sync_cm_factory(factory):
        plan = SyncLifecyclePlan(factory, factory, args, kwargs)
    elif _is_async_gen_factory(factory):
        enter = partial(_enter_async_gen, factory)
        plan = AsyncLifecyclePlan(factory, enter, args, kwargs)
    elif _is_sync_gen_factory(factory):
        enter = partial(_enter_sync_gen, factory)
        plan = SyncLifecyclePlan(factory, enter, args, kwargs)
    else:
        msg = f"Invalid lifecycle factory: {type(factory)}. Expected a generator or "
        msg += "context manager factory."
        raise TypeError(msg)

    return plan


def build_factory_plan[T](
    factory: ResourceFactory[T],
    /,
    *args: object,
    cleanup: Cleanup[T] | Literal[False] | None = None,
    **kwargs: object,
) -> ValueFactoryPlan[T] | LifecyclePlan[T]:
    """
    Classifies a factory into the plan an execution acquires.

    A generator or context-manager factory is a lifecycle and takes no ``cleanup``. Any
    other callable is a value factory and requires one.

    Args:

        factory: The lifecycle or value factory.
        args: Positional arguments for ``factory``.
        cleanup: The value factory's cleanup callback, or ``False`` for none.
        kwargs: Keyword arguments for ``factory``.

    Returns:

        The value-factory or lifecycle plan.

    Raises:

        TypeError: When ``cleanup`` does not fit the factory, or ``factory`` is not
            callable.

    Examples:

        >>> from riko.types._resource import build_factory_plan
        >>>
        >>> plan = build_factory_plan(dict, cleanup=False, name="main")
        >>> type(plan).__name__
        'ValueFactoryPlan'

    """
    if _is_lifecycle(factory):
        if cleanup is not None:
            msg = "Cleanup is not allowed for generator/context-manager factories. "
            msg += "Use Resource.from_lifecycle(...) instead if you want riko to "
            msg += "manage the lifecycle."
            raise TypeError(msg)

        plan: ValueFactoryPlan[T] | LifecyclePlan[T]
        plan = build_lifecycle_plan(factory, *args, **kwargs)
    elif not _is_value_factory(factory):
        msg = f"Invalid resource factory: {type(factory)}. Expected a generator or "
        msg += "context manager factory, or callable."
        raise TypeError(msg)
    elif cleanup is None:
        raise TypeError("ValueFactory requires an explicit cleanup function")
    else:
        plan = ValueFactoryPlan(factory, cleanup, args, kwargs)

    return plan
