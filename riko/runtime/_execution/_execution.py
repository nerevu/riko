# vim: sw=4:ts=4:expandtab
"""
Private sync/async executions that run a pipeline definition.

A pipeline definition is a reusable structural snapshot; running it creates one
of these one-shot executions. Each owns the task group, exit stack, and sync/async
bridge that bound a run's spawned tasks and acquired resources. These types are
private to the runtime and belong to no supported surface.
"""

from __future__ import annotations

from contextlib import AsyncExitStack, ExitStack, nullcontext
from inspect import isawaitable
from typing import TYPE_CHECKING, Any, Self, cast

from attrs import define

from riko.bado._backend import (
    CancelScope,
    asyncify,
    create_task_group,
    fail_after,
    start_blocking_portal,
)
from riko.bado._util import as_awaitable, maybe_deferred
from riko.base.exceptions import InvalidPipelineError, PipelineStateError
from riko.types._guards import is_async_callable

from ._plan import _ResourcePlan, _ResourceStrategy, build_resource_plan

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Coroutine
    from contextlib import AbstractAsyncContextManager, AbstractContextManager
    from types import TracebackType

    from anyio.abc import TaskGroup
    from anyio.from_thread import BlockingPortal

    from riko.runtime._resources import Resource
    from riko.runtime.context import Context


@define(frozen=True, slots=True)
class _Acquired:
    """Holds a successfully acquired resource value for single-flight replay."""

    value: object


@define(frozen=True, slots=True)
class _FailedAcquisition:
    """Holds a failed acquisition so repeated use replays the same error."""

    error: BaseException


class _BaseExecution:
    """Shares the definition reference and closed-state guard across executions."""

    __slots__ = ("_closing", "_context")

    def __init__(self, context: Context | None = None) -> None:
        self._context = context
        self._closing = False

    @property
    def context(self) -> Context | None:
        return self._context

    @property
    def closing(self) -> bool:
        return self._closing

    def _require_open(self, action: str) -> None:
        if self._closing:
            raise PipelineStateError("closing", action)


class SyncExecution(_BaseExecution):
    """
    Runs a pipeline definition synchronously behind one owned exit stack.

    Async-only components run through a lazily started blocking portal.

    Examples:

        >>> from contextlib import contextmanager
        >>> from riko.runtime._execution import SyncExecution
        >>>
        >>> events = []
        >>> @contextmanager
        ... def track(name):
        ...     events.append(f"open {name}")
        ...     yield name
        ...     events.append(f"close {name}")
        >>>
        >>> with SyncExecution() as execution:
        ...     first = execution.enter_context(track("a"))
        ...     second = execution.enter_context(track("b"))
        ...     (first, second)
        ('a', 'b')
        >>> events
        ['open a', 'open b', 'close b', 'close a']

    """

    __slots__ = ("_portal", "_portal_cm", "_resolved", "_stack")

    def __init__(self, context: Context | None = None) -> None:
        super().__init__(context)
        self._stack = ExitStack()
        self._portal_cm: AbstractContextManager[BlockingPortal] | None = None
        self._portal: BlockingPortal | None = None
        self._resolved: dict[Resource[Any], _Acquired | _FailedAcquisition] = {}

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        self.close()

    @property
    def portal(self) -> BlockingPortal:
        if self._portal is None:
            self._portal_cm = start_blocking_portal()
            self._portal = self._portal_cm.__enter__()  # noqa: PLC2801

        return self._portal

    def enter_context[T](self, cm: AbstractContextManager[T]) -> T:
        """
        Enters ``cm`` on the execution exit stack.

        Args:

            cm: A synchronous context manager to own for the execution.

        Returns:

            The value ``cm`` yields on entry.

        """
        self._require_open("add a resource to")
        return self._stack.enter_context(cm)

    def callback(self, func: Callable[..., object], *args: object) -> None:
        """
        Registers ``func`` to run during exit-stack unwind.

        Args:

            func: A cleanup callable invoked with ``args`` on shutdown.
            args: Positional arguments forwarded to ``func``.

        """
        self._require_open("add a callback to")
        self._stack.callback(func, *args)

    def run_async[T](self, func: Callable[..., Awaitable[T]], *args: object) -> T:
        """
        Runs an async callable to completion through the execution portal.

        Args:

            func: An async callable to await on the portal loop.
            args: Positional arguments forwarded to ``func``.

        Returns:

            The value ``func`` resolves to.

        """
        self._require_open("run work in")
        return self.portal.call(func, *args)

    def spawn(self, func: Callable[..., Awaitable[object]], *args: object) -> None:
        """
        Schedules a background async task on the execution portal.

        Args:

            func: An async callable to run under the portal task group.
            args: Positional arguments forwarded to ``func``.

        """
        self._require_open("spawn a task in")
        self.portal.start_task_soon(func, *args)

    def acquire[T](self, resource: Resource[T]) -> T:
        """
        Acquires ``resource`` for this execution, resolving it at most once.

        A subsequent request for the same resource replays the first outcome:
        the resolved value, or the original failure when acquisition failed.

        Args:

            resource: The resource definition to open.

        Returns:

            The resolved resource value.

        """
        self._require_open("acquire a resource in")

        if resource in self._resolved:
            entry = self._resolved[resource]
        else:
            entry = self._resolve(resource)
            self._resolved[resource] = entry

        if isinstance(entry, _FailedAcquisition):
            raise entry.error

        return cast("T", entry.value)

    def _resolve[T](self, resource: Resource[T]) -> _Acquired | _FailedAcquisition:
        plan = build_resource_plan(resource)

        try:
            value = self._open(plan)
        except Exception as error:  # noqa: BLE001
            entry: _Acquired | _FailedAcquisition = _FailedAcquisition(error)
        else:
            entry = _Acquired(value)

        return entry

    def _open[T](self, plan: _ResourcePlan[T]) -> object:
        if plan.strategy is _ResourceStrategy.EXTERNAL:
            value: object = plan.value
        elif plan.strategy is _ResourceStrategy.OWNED:
            value = plan.value
            self.callback(plan.resource.close, value)
        elif plan.strategy is _ResourceStrategy.VALUE_FACTORY:
            value = self._call_factory(plan)
        else:
            value = self._enter_lifecycle(plan)

        return value

    def _call_factory[T](self, plan: _ResourcePlan[T]) -> object:
        if (factory := plan.factory) is None:
            raise InvalidPipelineError("resource factory is required")
        else:
            raw = factory(*plan.args, **plan.kwargs)
            value = self.run_async(as_awaitable, raw) if isawaitable(raw) else raw

        self._register_cleanup(plan, value)
        return value

    def _register_cleanup[T](self, plan: _ResourcePlan[T], value: object) -> None:
        if not (cleanup := plan.cleanup):
            pass
        elif is_async_callable(cleanup):
            msg = "async resource cleanup requires async execution"
            raise InvalidPipelineError(msg)
        else:
            self.callback(cleanup, value)

    def _enter_lifecycle[T](self, plan: _ResourcePlan[T]) -> object:
        if plan.native_async:
            msg = "async-native resource lifecycle requires async execution"
            raise InvalidPipelineError(msg)

        return self.enter_context(
            cast("AbstractContextManager[object]", plan.context_manager)
        )

    def close(self) -> None:
        """Stops the portal, then unwinds the exit stack, grouping any failures."""
        self._closing = True
        errors: list[Exception] = []

        if self._portal_cm is not None:
            try:
                self._portal_cm.__exit__(None, None, None)
            except Exception as error:  # noqa: BLE001
                errors.append(error)
            finally:
                self._portal = None
                self._portal_cm = None

        try:
            self._stack.close()
        except Exception as error:  # noqa: BLE001
            errors.append(error)

        if errors:
            raise ExceptionGroup("Execution shutdown failed", errors)


class AsyncExecution(_BaseExecution):
    """
    Runs a pipeline definition asynchronously behind one owned exit stack.

    Blocking sync components run on a worker thread through the bridge.
    """

    __slots__ = ("_resolved", "_shutdown_timeout", "_stack", "_task_group")

    def __init__(
        self, context: Context | None = None, *, shutdown_timeout: float | None = None
    ) -> None:
        super().__init__(context)
        self._stack = AsyncExitStack()
        self._task_group: TaskGroup | None = None
        self._shutdown_timeout = shutdown_timeout
        self._resolved: dict[Resource[Any], _Acquired | _FailedAcquisition] = {}

    async def __aenter__(self) -> Self:
        self._task_group = create_task_group()
        await self._task_group.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        await self._shutdown(cancel=exc_type is not None)

    def enter_context[T](self, cm: AbstractContextManager[T]) -> T:
        """
        Enters a synchronous ``cm`` on the execution exit stack.

        Args:

            cm: A synchronous context manager to own for the execution.

        Returns:

            The value ``cm`` yields on entry.

        """
        self._require_open("add a resource to")
        return self._stack.enter_context(cm)

    async def enter_async_context[T](self, cm: AbstractAsyncContextManager[T]) -> T:
        """
        Enters an async ``cm`` on the execution exit stack.

        Args:

            cm: An asynchronous context manager to own for the execution.

        Returns:

            The value ``cm`` yields on entry.

        """
        self._require_open("add an async resource to")
        return await self._stack.enter_async_context(cm)

    def callback(self, func: Callable[..., object], *args: object) -> None:
        """
        Registers a synchronous ``func`` to run during exit-stack unwind.

        Args:

            func: A cleanup callable invoked with ``args`` on shutdown.
            args: Positional arguments forwarded to ``func``.

        """
        self._require_open("add a callback to")
        self._stack.callback(func, *args)

    def push_async_callback(
        self, func: Callable[..., Awaitable[object]], *args: object
    ) -> None:
        """
        Registers an async ``func`` to run during exit-stack unwind.

        Args:

            func: An async cleanup callable invoked with ``args`` on shutdown.
            args: Positional arguments forwarded to ``func``.

        """
        self._require_open("add an async callback to")
        self._stack.push_async_callback(func, *args)

    def spawn(
        self, func: Callable[..., Coroutine[object, object, object]], *args: object
    ) -> None:
        """
        Schedules a background task under the root task group.

        Args:

            func: An async callable to run under the execution task group.
            args: Positional arguments forwarded to ``func``.

        """
        self._require_open("spawn a task in")

        if self._task_group is None:
            raise PipelineStateError("new", "spawn a task in")

        self._task_group.start_soon(func, *args)

    async def run_sync[T](self, func: Callable[..., T], *args: object) -> T:
        """
        Runs a blocking sync callable on a worker thread through the bridge.

        Args:

            func: A synchronous callable to run off the event loop.
            args: Positional arguments forwarded to ``func``.

        Returns:

            The value ``func`` returns.

        """
        self._require_open("run work in")
        return await asyncify(func)(*args)

    async def aacquire[T](self, resource: Resource[T]) -> T:
        """
        Acquires ``resource`` for this execution, resolving it at most once.

        A subsequent request for the same resource replays the first outcome:
        the resolved value, or the original failure when acquisition failed.

        Args:

            resource: The resource definition to open.

        Returns:

            The resolved resource value.

        """
        self._require_open("acquire a resource in")

        if resource in self._resolved:
            entry = self._resolved[resource]
        else:
            entry = await self._aresolve(resource)
            self._resolved[resource] = entry

        if isinstance(entry, _FailedAcquisition):
            raise entry.error

        return cast("T", entry.value)

    async def _aresolve[T](
        self, resource: Resource[T]
    ) -> _Acquired | _FailedAcquisition:
        plan = build_resource_plan(resource)

        try:
            value = await self._aopen(plan)
        except Exception as error:  # noqa: BLE001
            entry: _Acquired | _FailedAcquisition = _FailedAcquisition(error)
        else:
            entry = _Acquired(value)

        return entry

    async def _aopen[T](self, plan: _ResourcePlan[T]) -> object:
        if plan.strategy is _ResourceStrategy.EXTERNAL:
            value: object = plan.value
        elif plan.strategy is _ResourceStrategy.OWNED:
            value = plan.value
            self.push_async_callback(plan.resource.aclose, value)
        elif plan.strategy is _ResourceStrategy.VALUE_FACTORY:
            value = await self._acall_factory(plan)
        else:
            value = await self._aenter_lifecycle(plan)

        return value

    async def _acall_factory[T](self, plan: _ResourcePlan[T]) -> object:
        if (factory := plan.factory) is None:
            raise InvalidPipelineError("resource factory is required")
        else:
            value = await maybe_deferred(factory, *plan.args, **plan.kwargs)

            if cleanup := plan.cleanup:
                self.push_async_callback(maybe_deferred, cleanup, value)

        return value

    async def _aenter_lifecycle[T](self, plan: _ResourcePlan[T]) -> object:
        if plan.native_async:
            cm = cast("AbstractAsyncContextManager[object]", plan.context_manager)
            value: object = await self.enter_async_context(cm)
        else:
            cm = cast("AbstractContextManager[object]", plan.context_manager)
            value = self.enter_context(cm)

        return value

    async def aclose(self) -> None:
        """Joins the task group, then unwinds the exit stack behind a shield."""
        await self._shutdown(cancel=False)

    async def _shutdown(self, *, cancel: bool) -> None:
        self._closing = True
        errors: list[Exception] = []
        await self._join_tasks(cancel=cancel, errors=errors)
        await self._unwind(errors=errors)

        if errors:
            raise ExceptionGroup("Execution shutdown failed", errors)

    async def _join_tasks(self, *, cancel: bool, errors: list[Exception]) -> None:
        if self._task_group is not None:
            if cancel:
                self._task_group.cancel_scope.cancel()

            try:
                await self._task_group.__aexit__(None, None, None)
            except Exception as error:  # noqa: BLE001
                errors.append(error)
            finally:
                self._task_group = None

    async def _unwind(self, *, errors: list[Exception]) -> None:
        bound = (
            fail_after(self._shutdown_timeout)
            if self._shutdown_timeout is not None
            else nullcontext()
        )

        with CancelScope(shield=True), bound:
            try:
                await self._stack.aclose()
            except Exception as error:  # noqa: BLE001
                errors.append(error)


__all__ = ["AsyncExecution", "SyncExecution"]
