# vim: sw=4:ts=4:expandtab
"""Produces the values and context managers a resource plan describes."""

from __future__ import annotations

from typing import TYPE_CHECKING, overload

from riko.base._iterutils import map_values
from riko.types._frozendict import thaw

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from contextlib import AbstractAsyncContextManager, AbstractContextManager

    from riko.types._resource import (
        AsyncLifecyclePlan,
        SyncLifecyclePlan,
        ValueFactoryPlan,
    )


def _call_thawed[R](func: Callable[..., R], *args: object, **kwargs: object) -> R:
    return func(*map(thaw, args), **map_values(thaw, kwargs))


def call_factory[T](plan: ValueFactoryPlan[T]) -> T | Awaitable[T]:
    """
    Calls a value factory with fresh copies of its arguments.

    Args:

        plan: The value-factory plan.

    Returns:

        The factory's result, which an async factory leaves to be awaited.

    Examples:

        >>> from riko.types._resource import build_factory_plan
        >>>
        >>> plan = build_factory_plan(dict, cleanup=False, name="main")
        >>> call_factory(plan)
        {'name': 'main'}

    """
    return _call_thawed(plan.func, *plan.args, **plan.kwargs)


@overload
def build_context_manager[T](  # noqa: E704
    plan: SyncLifecyclePlan[T],
) -> AbstractContextManager[T]: ...
@overload  # noqa: E302
def build_context_manager[T](  # noqa: E704
    plan: AsyncLifecyclePlan[T],
) -> AbstractAsyncContextManager[T]: ...
def build_context_manager[T](  # noqa: E302
    plan: SyncLifecyclePlan[T] | AsyncLifecyclePlan[T],
) -> AbstractContextManager[T] | AbstractAsyncContextManager[T]:
    """
    Builds a lifecycle plan's context manager with fresh copies of its arguments.

    Args:

        plan: The sync or async lifecycle plan.

    Returns:

        The context manager to enter.

    Examples:

        >>> from riko.types._resource import build_lifecycle_plan
        >>>
        >>> def db(name):
        ...     yield {"name": name}
        >>>
        >>> plan = build_lifecycle_plan(db, "main")
        >>> with build_context_manager(plan) as connection:
        ...     connection
        {'name': 'main'}

    """
    return _call_thawed(plan.enter, *plan.args, **plan.kwargs)


__all__ = ["build_context_manager", "call_factory"]
