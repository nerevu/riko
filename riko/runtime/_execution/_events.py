# vim: sw=4:ts=4:expandtab
"""
Execution-owned event transport.

A running execution dispatches events to an ``EventSink``. The transport carries
opaque event values only; later runtime phases define the semantic events and
results they emit. The default sink discards every event.
"""

from __future__ import annotations

from typing import Protocol


class EventSink(Protocol):
    """Receives events emitted by a running execution."""

    def emit(self, event: object) -> None:
        """
        Delivers an emitted execution event.

        Args:

            event: The event value produced during a run.

        """
        ...


class _NullEventSink:
    """Discards every emitted event."""

    __slots__ = ()

    def emit(self, event: object) -> None:
        """
        Discards an emitted execution event.

        Args:

            event: The event value produced during a run.

        """


_NULL_EVENT_SINK = _NullEventSink()


__all__ = ["EventSink"]
