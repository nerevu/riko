# vim: sw=4:ts=4:expandtab
"""Asynchronous delivery for named in-process pub/sub channels."""

from __future__ import annotations

import itertools as it
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from riko.bado._backend import (
    MemoryObjectReceiveStream,
    MemoryObjectSendStream,
    create_memory_object_stream,
    fail_after,
)
from riko.base.exceptions import DuplicateReceiverError, ReceiverUnavailableError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterable

    from riko.types._streams import Record


class SubscriptionState(StrEnum):
    PENDING = "pending"
    SUBSCRIBED = "subscribed"
    CLOSED = "closed"


@dataclass(slots=True)
class _Slot:
    name: str
    generation: int
    send_stream: MemoryObjectSendStream
    receive_stream: MemoryObjectReceiveStream
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

        slot.send_stream.close()
        slot.receive_stream.close()

    async def publish(
        self, targets: Iterable[str], item: Record, *, timeout: float | None = None
    ) -> None:
        for name in targets:
            slot = self._get_or_create(name)

            try:
                with fail_after(timeout):
                    await slot.send_stream.send(item)
            except TimeoutError as e:
                self._discard(name, slot)
                raise ReceiverUnavailableError(name) from e

    async def complete(self, targets: Iterable[str]) -> None:
        for name in targets:
            slot = self._slots.get(name)

            if slot is not None:
                await slot.send_stream.aclose()
                slot.state = SubscriptionState.CLOSED

    @asynccontextmanager
    async def subscribe(self, name: str) -> AsyncIterator[MemoryObjectReceiveStream]:
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
        for slot in self._slots.values():
            slot.send_stream.close()
            slot.receive_stream.close()

        self._slots.clear()
