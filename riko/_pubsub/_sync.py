# vim: sw=4:ts=4:expandtab
"""
Synchronous pub/sub backend.

A generator-coroutine push adapter: receivers are primed generators (via the
``coroutine`` decorator in ``riko.utils``) whose pushed items land in a bounded
``deque``. This is the right tool for synchronous pipelines and push-based
parsers (e.g. ijson); it has no native awaitable channel, so completion uses a
DONE sentinel and per-receiver identity tokens. The async backend
(``riko._pubsub._async``) does not route through here.
"""

from collections import deque
from collections.abc import Generator, Mapping
from itertools import count

import pygogo as gogo

from riko.types.general import Item
from riko.types.values import StatefulItem, StreamState

logger = gogo.Gogo(__name__, verbose=False, monolog=True).logger


class SyncPubSubHub:
    """
    Owns synchronous pub/sub state: receiver generators, per-name receive
    queues, and minted receiver ids. ``riko.utils`` exposes thin
    ``send``/``close``/``coroutine``/``reset_pubsub`` shims plus
    ``_registry``/``_receive_queue``/``_ids`` aliases over the dicts here;
    ``reset`` clears them in place so those aliases stay valid.
    """

    def __init__(self) -> None:
        self.receivers: dict[str, Generator[None, Item | StatefulItem, None]] = {}
        self.queues: dict[str, deque[tuple[StreamState | None, Item]]] = {}
        self.ids: dict[str, int] = {}
        self._counter = count()

    def seed(
        self, name: str, gen: Generator[None, Item | StatefulItem, None], maxlen: int
    ) -> None:
        self.receivers[name] = gen
        self.queues[name] = deque(maxlen=maxlen)
        self.ids[name] = next(self._counter)

    def send(self, target: str, item: Item | StatefulItem) -> int | None:
        target_id = None
        gen = self.receivers.get(target)

        if gen is None:
            logger.error(f"Attempted to send {item} to non-existent '{target}'")
        else:
            try:
                gen.send(item)
            except StopIteration:
                self.receivers.pop(target, None)
                self.ids.pop(target, None)
            else:
                target_id = self.ids.get(target)

        return target_id

    def notify_complete(self, ids: Mapping[str, int]) -> None:
        targets = [t for t, tid in ids.items() if self.ids.get(t) == tid]

        for target in targets:
            self.send(target, {"state": StreamState.DONE})

    def close(self, name: str) -> None:
        if (gen := self.receivers.pop(name, None)) is not None:
            gen.close()

        self.queues.pop(name, None)
        self.ids.pop(name, None)

    def reset(self) -> None:
        for name in tuple(self.receivers):
            self.close(name)

        self.receivers.clear()
        self.queues.clear()
        self.ids.clear()
