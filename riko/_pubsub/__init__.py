# vim: sw=4:ts=4:expandtab
"""
Private pub/sub backends: a synchronous generator/deque hub and an asynchronous
AnyIO-channel hub, exposed as two module-level instances. Ownership is
process-wide for now (preserving the current receiver-name namespace and
independent-pipe construction); it will migrate to execution-scoped
``Context.resources`` before concurrent independent pipelines share a process.
``reset_pubsub`` exists for test isolation only — runtime correctness does not
depend on it.
"""

from collections.abc import Callable, Generator
from functools import wraps
from typing import Any

from riko.types.general import Item
from riko.types.values import StatefulItem

from ._async import AsyncPubSubHub, SubscriptionState
from ._sync import SyncPubSubHub

sync_hub = SyncPubSubHub()
async_hub = AsyncPubSubHub()


__all__ = [
    "AsyncPubSubHub",
    "SubscriptionState",
    "SyncPubSubHub",
    "async_hub",
    "close",
    "coroutine",
    "reset_pubsub",
    "send",
    "sync_hub",
]


def reset_pubsub() -> None:
    sync_hub.reset()
    async_hub.reset()


def send(target: str, item: Item | StatefulItem) -> int | None:
    return sync_hub.send(target, item)


def close(name: str) -> None:
    sync_hub.close(name)


def coroutine(
    registry_name: str | None = None, maxlen: int = 256
) -> Callable[
    [Callable[..., Generator[None, Item | StatefulItem, None]]],
    Callable[..., Generator[None, Item | StatefulItem, None]],
]:
    """Decorator for generator-based coroutines."""

    def decorator(
        func: Callable[..., Generator[None, Item | StatefulItem, None]],
    ) -> Callable[..., Generator[None, Item | StatefulItem, None]]:
        name = registry_name or func.__name__

        @wraps(func)
        def wrapper(
            *args: Any, **kwargs: object
        ) -> Generator[None, Item | StatefulItem, None]:
            gen = func(*args, **kwargs)
            next(gen)
            sync_hub.seed(name, gen, maxlen)
            return gen

        return wrapper

    return decorator
