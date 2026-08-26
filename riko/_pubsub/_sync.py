# vim: sw=4:ts=4:expandtab
"""
Synchronous pub/sub backend.

Delivers buffered items to named receivers within a single synchronous run. Backs the
sync half of ``send`` and ``receive``. The async half uses ``riko._pubsub._async``
instead.
"""

from collections import deque
from collections.abc import Mapping
from itertools import count

import pygogo as gogo

from riko.types.general import Item, Receiver
from riko.types.values import MissingType, StatefulItem, StreamState

logger = gogo.Gogo(__name__, verbose=False, monolog=True).logger


class SyncPubSubHub:
    """
    The registry of synchronous receivers and their pending items.

    Instantiated once by ``riko._pubsub`` as ``sync_hub``, which is how callers
    reach it.

    A receiver is a primed generator: ``seed`` registers one under a name
    alongside a queue for its items and a token identifying that particular
    registration. Because a generator has no closable channel, a sender marks
    completion by pushing a ``DONE`` record rather than closing anything. And
    the token is what lets it confirm the receiver it bound to is still the one
    listening.

    Attributes:
        receivers: Live receiver generator per name.
        queues: Items awaiting each receiver, oldest first.
        ids: Registration token per name.

    """

    def __init__(self) -> None:
        self.receivers: dict[str, Receiver] = {}
        self.queues: dict[
            str, deque[tuple[StreamState | None, Item | MissingType | None]]
        ] = {}
        self.ids: dict[str, int] = {}
        self._counter = count()

    def seed(self, name: str, receiver: Receiver, maxlen: int | None) -> None:
        """
        Registers a primed receiver under ``name``, ready to be sent to.

        Args:
            name: Channel senders address.

            receiver: An already-primed receiver generator.

            maxlen: Queue capacity. ``None`` is unbounded; a full queue drops its oldest
                item.

        Notes:
            Re-seeding a live name replaces it and mints a new token, orphaning
            any sender still holding the old one.

        """
        self.receivers[name] = receiver
        self.queues[name] = deque(maxlen=maxlen)
        self.ids[name] = next(self._counter)

    def send(self, target: str, item: Item | StatefulItem) -> int | None:
        """
        Pushes one item to a named receiver.

        Returns:
            The receiver's registration token, or ``None`` when no such receiver
            exists or its generator has already finished.

        Notes:
            An unknown target is logged and skipped rather than raised, so a
            sender outliving its receivers keeps going. The token lets a later
            completion signal verify it is addressing the same receiver instance
            it bound to.

        """
        target_id = None

        if (receiver := self.receivers.get(target)) is None:
            logger.error(f"Attempted to send {item} to non-existent '{target}'")
        else:
            try:
                receiver.send(item)
            except StopIteration:
                self.receivers.pop(target, None)
                self.ids.pop(target, None)
            else:
                target_id = self.ids.get(target)

        return target_id

    def notify_complete(self, ids: Mapping[str, int]) -> None:
        """
        Tells a sender's receivers that no more items are coming.

        Only receivers whose current token still matches the one the sender
        recorded are notified.

        Args:
            ids: The name-to-token map the sender collected as it published.

        Notes:
            A name that was closed and re-registered in the meantime belongs to
            a different receiver, so it is left alone rather than told a sender
            it never heard from is done.

        """
        targets = [t for t, tid in ids.items() if self.ids.get(t) == tid]

        for target in targets:
            self.send(target, {"state": StreamState.DONE})

    def close(self, name: str) -> None:
        """
        Drops a receiver, discarding anything still queued for it.

        Closes the generator and removes the receiver, its queue, and its
        registration token together. This ends the *subscription* rather than
        one pass over it.

        Notes:
            Re-registering the same name afterwards mints a fresh token, which
            invalidates any completion signal a sender had already bound.

        """
        if (receiver := self.receivers.pop(name, None)) is not None:
            receiver.close()

        self.queues.pop(name, None)
        self.ids.pop(name, None)

    def reset(self) -> None:
        """
        Closes every receiver and empties the registry.

        Notes:
            The dicts are mutated rather than rebound, so a caller holding a
            reference to one of them sees the cleared state.

        """
        for name in tuple(self.receivers):
            self.close(name)

        self.receivers.clear()
        self.queues.clear()
        self.ids.clear()
