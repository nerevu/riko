# vim: sw=4:ts=4:expandtab
"""Immutable execution settings a pipeline runs with."""

from __future__ import annotations

from functools import cached_property, partial
from math import isnan
from typing import TYPE_CHECKING, Literal, NamedTuple

from attrs import define, field

from riko.base._config import get_worker_cnt
from riko.base._config import settings as config
from riko.base._exceptions import InvalidPipelineError
from riko.base._require_guards import (
    def_from_require,
    require_instance,
    validator_from_require,
)
from riko.base._typing import resolve_enum
from riko.types._enums import Executor

if TYPE_CHECKING:
    from riko.types._events import EventSink

__all__ = ["DEF_EXECUTION_SETTINGS", "AsyncPolicy", "ExecutionSettings", "SyncPolicy"]


class SyncPolicy(NamedTuple):
    """
    How a synchronous run maps a loopable node's items.

    Attributes:

        executor: The effective executor (never ``AUTO``).
        workers: The pool size, or ``None`` to run items sequentially without a pool.

    """

    executor: Executor
    workers: int | None


class AsyncPolicy(NamedTuple):
    """
    How an asynchronous run maps a loopable node's items.

    Attributes:

        limit: The per-run ceiling on items in flight, or ``None`` to run items
            sequentially.

        inline: Whether a synchronous pipe runs on the event-loop thread instead of a
            worker thread.

    """

    limit: int | None
    inline: bool


def _require_concurrency(
    value: object, what: str | None = "value", **_
) -> int | Literal["auto"]:
    if value == "auto":
        concurrency: int | Literal["auto"] = "auto"
    elif isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{what} must be an int, 'auto', or None")
    elif value < 1:
        raise ValueError(f"{what} must be at least 1, got {value}")
    else:
        concurrency = value

    return concurrency


def _require_timeout(value: object, what: str | None = "value", **_) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{what} must be a number")
    elif isnan(value) or value < 0:
        raise ValueError(f"{what} must not be negative or NaN, got {value}")

    return value


_concurrency = def_from_require(
    _require_concurrency, what="ExecutionSettings 'concurrency'"
)
_executor = partial(
    resolve_enum, Executor, what="ExecutionSettings 'executor'", error=ValueError
)
_is_bool = validator_from_require(require_instance, bool, error=TypeError)
_is_timeout = validator_from_require(_require_timeout)


@define(frozen=True, slots=True)
class ExecutionSettings:
    """
    How a pipeline run executes its per-item work.

    Attributes:

        executor: Where per-item work runs, as an ``Executor`` or its string value.

        concurrency: The per-run ceiling on items in flight, ``"auto"`` to size it for
            the machine, or ``None`` to run items sequentially.

        ordered: Whether mapped results keep source order.

        event_sink: The sink that receives events emitted during a run, or ``None`` to
            discard them.

        shutdown_timeout: The bound, in seconds, on cleanup under asynchronous
            iteration, and on how long stopped worker processes get, together, before
            any still running are killed under synchronous iteration. ``math.inf`` means
            no bound. The default is 30 seconds, or ``RIKO_SHUTDOWN_TIMEOUT`` when set.

    Raises:

        ValueError: If ``concurrency`` is below one, ``shutdown_timeout`` is negative or
            NaN, or ``executor`` names no known executor.

        TypeError: If ``concurrency``, ``ordered``, or ``shutdown_timeout`` has the
            wrong type.

    Examples:

        Basic usage::

            >>> from riko.definitions._settings import ExecutionSettings
            >>>
            >>> settings = ExecutionSettings(executor="thread", concurrency=4)
            >>> settings.executor, settings.concurrency
            (<Executor.THREAD: 'thread'>, 4)

    """

    executor: Executor = field(default=Executor.AUTO, converter=_executor)
    concurrency: int | Literal["auto"] | None = field(
        default=None, converter=_concurrency
    )
    ordered: bool = field(default=False, validator=_is_bool)
    event_sink: EventSink | None = field(default=None, repr=False)
    shutdown_timeout: float = field(
        default=config.shutdown_timeout, validator=_is_timeout
    )

    @cached_property
    def sync_policy(self) -> SyncPolicy:
        """
        Where a synchronous run's per-item work runs and how wide it fans out.

        ``AUTO`` maps across threads only when ``concurrency`` asks for more than
        one item in flight; ``INLINE`` never opens a pool. An explicit thread or
        process executor without a ``concurrency`` runs one item at a time on that
        executor. ``concurrency="auto"`` sizes the pool from the machine's cores.

        Examples:

            >>> from riko.definitions._settings import ExecutionSettings
            >>>
            >>> ExecutionSettings().sync_policy
            SyncPolicy(executor=<Executor.INLINE: 'inline'>, workers=None)
            >>> ExecutionSettings(concurrency=4).sync_policy
            SyncPolicy(executor=<Executor.THREAD: 'thread'>, workers=4)
            >>> ExecutionSettings(concurrency="auto").sync_policy.workers > 1
            True

        """
        executor, concurrency = self.executor, self.concurrency
        is_auto = concurrency == "auto"
        is_wide = is_auto or (isinstance(concurrency, int) and concurrency > 1)

        if executor is Executor.INLINE or (executor is Executor.AUTO and not is_wide):
            policy = SyncPolicy(Executor.INLINE, None)
        else:
            chosen = Executor.THREAD if executor is Executor.AUTO else executor

            if is_auto:
                workers = get_worker_cnt(threads=chosen is Executor.THREAD)
            elif isinstance(concurrency, int):
                workers = concurrency
            else:
                workers = 1

            policy = SyncPolicy(chosen, workers)

        return policy

    @cached_property
    def async_policy(self) -> AsyncPolicy:
        """
        How many items an asynchronous run keeps in flight per run.

        ``AUTO`` stays sequential unless ``concurrency`` is set. An explicit
        ``INLINE`` or ``THREAD`` executor without a ``concurrency`` keeps one item
        in flight on that executor. ``INLINE`` also keeps synchronous pipes on the
        event-loop thread. ``concurrency="auto"`` keeps the default concurrency
        limit in flight.

        Raises:

            InvalidPipelineError: If the settings name the process executor, which
                asynchronous iteration cannot use.

        Examples:

            >>> from riko.definitions._settings import ExecutionSettings
            >>>
            >>> ExecutionSettings(concurrency=4).async_policy
            AsyncPolicy(limit=4, inline=False)
            >>> ExecutionSettings(concurrency="auto").async_policy.limit > 1
            True
            >>> ExecutionSettings(executor="process").async_policy
            Traceback (most recent call last):
            riko.base.exceptions.InvalidPipelineError: ...requires synchronous execution

        """
        executor, concurrency = self.executor, self.concurrency

        if executor is Executor.PROCESS:
            msg = "the process executor requires synchronous execution"
            raise InvalidPipelineError(msg)
        else:
            if concurrency == "auto":
                limit = config.concurrency_limit
            elif isinstance(concurrency, int) or executor is Executor.AUTO:
                limit = concurrency
            else:
                limit = 1

            policy = AsyncPolicy(limit, executor is Executor.INLINE)

        return policy


DEF_EXECUTION_SETTINGS = ExecutionSettings()
