# vim: sw=4:ts=4:expandtab
"""
The event-sink contract a running execution reports to.

An event sink receives opaque event values while a pipeline runs; it decides what to
record, forward, or discard.

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
