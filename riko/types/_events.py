# vim: sw=4:ts=4:expandtab
"""
The event-sink contract a running execution reports to.

A sink receives opaque event values while a pipeline runs; it decides what to
record, forward, or discard.

Examples:

    >>> from riko.types import EventSink
    >>>
    >>> class Recorder:
    ...     def __init__(self) -> None:
    ...         self.events: list[object] = []
    ...
    ...     def emit(self, event: object) -> None:
    ...         self.events.append(event)
    >>>
    >>> sink: EventSink = Recorder()
    >>> sink.emit("started")
    >>> sink.events
    ['started']

"""

from __future__ import annotations

from typing import Protocol

__all__ = ["EventSink"]


class EventSink(Protocol):
    """Receives events emitted by a running execution."""

    def emit(self, event: object) -> None:
        """
        Delivers an emitted execution event.

        Args:

            event: The event value produced during a run.

        """
        ...
