# vim: sw=4:ts=4:expandtab
"""
Immutable execution settings a pipeline runs with.

Examples:

    Basic usage::

        >>> from attrs import evolve
        >>> from riko import Executor
        >>> from riko.definitions._execution import ExecutionSettings
        >>>
        >>> settings = ExecutionSettings(executor="thread")
        >>> settings.executor is Executor.THREAD, settings.concurrency
        (True, None)
        >>> evolve(settings, concurrency=4).concurrency
        4
        >>> ExecutionSettings(concurrency=0)
        Traceback (most recent call last):
        ValueError: ExecutionSettings 'concurrency' must be at least 1, got 0

"""

from __future__ import annotations

from math import isnan
from typing import TYPE_CHECKING

from attrs import define, field

from riko.types._collections import validator_from_require
from riko.types._enums import Executor

if TYPE_CHECKING:
    from riko.types._events import EventSink

__all__ = ["DEF_EXECUTION_SETTINGS", "ExecutionSettings"]


def _require_concurrency(value: object, what: str | None = "value") -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{what} must be an int or None")
    elif value < 1:
        raise ValueError(f"{what} must be at least 1, got {value}")

    return value


def _require_bool(value: object, what: str | None = "value") -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{what} must be a bool")

    return value


def _require_timeout(value: object, what: str | None = "value") -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{what} must be a number or None")
    elif isnan(value) or value < 0:
        raise ValueError(f"{what} must not be negative or NaN, got {value}")

    return value


_concurrency = validator_from_require(_require_concurrency, optional=True)
_ordered = validator_from_require(_require_bool)
_timeout = validator_from_require(_require_timeout, optional=True)


@define(frozen=True, slots=True)
class ExecutionSettings:
    """
    How a pipeline run executes its per-item work.

    Attributes:

        executor: Where per-item work runs; a string such as ``"thread"`` is
            accepted and an unknown one raises ``ValueError``.

        concurrency: The per-run ceiling on items in flight, or ``None`` to run
            items sequentially.

        ordered: Whether mapped results keep source order.

        event_sink: The sink that receives events emitted during a run, or
            ``None`` to discard them.

        shutdown_timeout: The bound, in seconds, on teardown under asynchronous
            iteration, or ``None`` for no bound.

    Raises:

        ValueError: If ``concurrency`` is below one, ``shutdown_timeout`` is
            negative or NaN, or ``executor`` names no known executor.

        TypeError: If ``concurrency``, ``ordered``, or ``shutdown_timeout`` has
            the wrong type.

    Examples:

        Basic usage::

            >>> from riko.definitions._execution import ExecutionSettings
            >>>
            >>> settings = ExecutionSettings(concurrency=4, ordered=True)
            >>> settings.executor.value, settings.concurrency, settings.ordered
            ('auto', 4, True)

    """

    executor: Executor = field(default=Executor.AUTO, converter=Executor)
    concurrency: int | None = field(default=None, validator=_concurrency)
    ordered: bool = field(default=False, validator=_ordered)
    event_sink: EventSink | None = field(default=None, repr=False)
    shutdown_timeout: float | None = field(default=None, validator=_timeout)


DEF_EXECUTION_SETTINGS = ExecutionSettings()
