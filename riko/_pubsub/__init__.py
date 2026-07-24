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

from ._async import AsyncPubSubHub, SubscriptionState
from ._sync import SyncPubSubHub

sync_hub = SyncPubSubHub()
async_hub = AsyncPubSubHub()


__all__ = [
    "AsyncPubSubHub",
    "SubscriptionState",
    "SyncPubSubHub",
    "async_hub",
    "reset_pubsub",
    "sync_hub",
]


def reset_pubsub() -> None:
    sync_hub.reset()
    async_hub.reset()
