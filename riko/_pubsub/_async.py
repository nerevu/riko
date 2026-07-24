# vim: sw=4:ts=4:expandtab
"""
Asynchronous pub/sub backend.

Each named receiver is a lazily created rendezvous channel (an AnyIO memory
object stream with ``max_buffer_size=0``). ``publish`` and ``subscribe`` both
resolve the same named slot, so concurrent startup converges deterministically
with no sleep, readiness event, or task-order assumption: whichever side
arrives first waits through channel backpressure for the other. Completion is
channel closure (one active publisher per receiver); a publish to a name that is
never subscribed is bounded by a timeout and raises ``ReceiverUnavailableError``
rather than dropping data or hanging.

AnyIO objects are created lazily inside these operations, so the hub instance is
safe to construct at import time even when the async extra is absent.
"""

import itertools as it
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from riko.bado import create_memory_object_stream, fail_after
from riko.exceptions import DuplicateReceiverError, ReceiverUnavailableError
from riko.types.general import Item


class SubscriptionState(StrEnum):
    PENDING = "pending"
    SUBSCRIBED = "subscribed"
    CLOSED = "closed"


@dataclass(slots=True)
class _Slot:
    name: str
    generation: int
    send_stream: Any
    receive_stream: Any
    state: SubscriptionState = field(default=SubscriptionState.PENDING)


class AsyncPubSubHub:
    def __init__(self) -> None:
        self._slots: dict[str, _Slot] = {}
        self._generation = it.count()

    def _get_or_create(self, name: str) -> _Slot:
        slot = self._slots.get(name)

        if slot is None:
            send_stream, receive_stream = create_memory_object_stream(0)
            slot = _Slot(name, next(self._generation), send_stream, receive_stream)
            self._slots[name] = slot

        return slot

    def _discard(self, name: str, slot: _Slot) -> None:
        if self._slots.get(name) is slot:
            del self._slots[name]

    async def publish(
        self, targets: Iterable[str], item: Item, *, timeout: float | None = None
    ) -> None:
        for name in targets:
            slot = self._get_or_create(name)

            try:
                with fail_after(timeout):
                    await slot.send_stream.send(item)
            except TimeoutError as exc:
                self._discard(name, slot)
                raise ReceiverUnavailableError(name) from exc

    async def complete(self, targets: Iterable[str]) -> None:
        for name in targets:
            slot = self._slots.get(name)

            if slot is not None:
                await slot.send_stream.aclose()
                slot.state = SubscriptionState.CLOSED

    @asynccontextmanager
    async def subscribe(self, name: str) -> AsyncIterator[Any]:
        slot = self._get_or_create(name)

        if slot.state is SubscriptionState.SUBSCRIBED:
            raise DuplicateReceiverError(name)

        slot.state = SubscriptionState.SUBSCRIBED

        try:
            yield slot.receive_stream
        finally:
            await slot.receive_stream.aclose()
            self._discard(name, slot)

    def reset(self) -> None:
        self._slots.clear()
