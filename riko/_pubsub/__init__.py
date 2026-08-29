# vim: sw=4:ts=4:expandtab
"""
Internal pub/sub backends.

Delivers items from ``send`` to the named receivers that ``receive`` drains, one
hub per execution model: ``sync_hub`` for synchronous pipelines and
``async_hub`` for asynchronous ones. The two are independent — a sync sender
cannot reach an async receiver.

``reset_pubsub`` exists for test isolation only; runtime correctness does not
depend on it.
"""

from collections.abc import Callable
from functools import wraps
from typing import Any

from ._async import AsyncPubSubHub
from ._sync import SyncPubSubHub
from ._types import Receiver

sync_hub = SyncPubSubHub()
async_hub = AsyncPubSubHub()


__all__ = ["async_hub", "coroutine", "reset_pubsub", "sync_hub"]


def reset_pubsub() -> None:
    """
    Clears both hubs.

    For test isolation only. The conftest fixtures call it around every test. Runtime
    correctness does not depend on it.
    """
    sync_hub.reset()
    async_hub.reset()


def coroutine(
    registry_name: str | None = None, maxlen: int | None = None
) -> Callable[[Callable[..., Receiver]], Callable[..., Receiver]]:
    """
    Returns a decorator that registers a generator as a sync receiver.

    Calling the decorated function primes the generator to its first ``yield`` and
    registers it with ``sync_hub``. It is ready to be pushed to before the caller does
    anything else. The generator itself is returned, not the hub entry.

    Args:
        registry_name: Channel to register under. Defaults to the decorated
            function's name, which is only useful for a module-level receiver.

        maxlen: Queue capacity. ``None`` is unbounded; a full bounded queue
            drops its oldest item.

    Raises:
        ValueError: If ``maxlen`` is set below 1. A ``0``-length queue would
            silently discard every item.

    """
    if maxlen is not None and maxlen < 1:
        raise ValueError("maxlen must be greater than 0")

    def decorator(func: Callable[..., Receiver]) -> Callable[..., Receiver]:
        name = registry_name or func.__name__

        @wraps(func)
        def wrapper(*args: Any, **kwargs: object) -> Receiver:
            gen = func(*args, **kwargs)
            next(gen)
            sync_hub.seed(name, gen, maxlen)
            return gen

        return wrapper

    return decorator
