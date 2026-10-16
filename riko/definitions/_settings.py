# vim: sw=4:ts=4:expandtab
"""Immutable execution settings a pipeline runs with."""

from __future__ import annotations

from functools import partial
from math import isnan
from typing import TYPE_CHECKING, Literal

from attrs import define, field

from riko.types._collections import (
    def_from_require,
    require_instance,
    validator_from_require,
)
from riko.types._enums import Executor, resolve_enum

if TYPE_CHECKING:
    from riko.types._events import EventSink

__all__ = ["DEF_EXECUTION_SETTINGS", "ExecutionSettings"]


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
        raise TypeError(f"{what} must be a number or None")
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
_is_timeout = validator_from_require(_require_timeout, optional=True)


@define(frozen=True, slots=True)
class ExecutionSettings:
    """
    How a pipeline run executes its per-item work.

    Attributes:

        executor: Where per-item work runs; a string such as ``"thread"`` is
            accepted and an unknown one raises ``ValueError`` listing the known
            executors.

        concurrency: The per-run ceiling on items in flight, ``"auto"`` to size
            it for the machine, or ``None`` to run items sequentially.

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

            >>> from attrs import evolve
            >>> from riko import Executor
            >>> from riko.definitions._settings import ExecutionSettings
            >>>
            >>> settings = ExecutionSettings(concurrency=4, ordered=True)
            >>> settings.executor.value, settings.concurrency, settings.ordered
            ('auto', 4, True)
            >>> threaded = ExecutionSettings(executor="thread")
            >>> threaded.executor is Executor.THREAD, threaded.concurrency
            (True, None)
            >>> evolve(threaded, concurrency="auto").concurrency
            'auto'
            >>> ExecutionSettings(concurrency=0)
            Traceback (most recent call last):
            ValueError: ExecutionSettings 'concurrency' must be at least 1, got 0

    """

    executor: Executor = field(default=Executor.AUTO, converter=_executor)
    concurrency: int | Literal["auto"] | None = field(
        default=None, converter=_concurrency
    )
    ordered: bool = field(default=False, validator=_is_bool)
    event_sink: EventSink | None = field(default=None, repr=False)
    shutdown_timeout: float | None = field(default=None, validator=_is_timeout)


DEF_EXECUTION_SETTINGS = ExecutionSettings()
