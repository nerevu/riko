# vim: sw=4:ts=4:expandtab
"""
Pushes items to one or more named receivers.

Pairs with the ``receive`` module for in-process fan-out: ``send`` publishes to the
names listed in ``others`` and passes the items through unchanged.

This is the low-level interface. ``riko.SyncPipe.publish`` is the high-level path, both as
``SyncPipe.publish(items, "alerts")`` and as ``flow.publish("alerts")`` mid-chain.

Examples:
    Basic usage::

        >>> from riko.modules.receive import pipe as receiver
        >>> from riko.modules.send import pipe as sender
        >>>
        >>> target = receiver(conf={"name": "receiver1", "wait": 0.01, "max_wait": 2})
        >>> next(target)
        {'state': <StreamState.PENDING: 1>}
        >>> stream = ({"x": x} for x in range(5))
        >>> source = sender(stream, others=["receiver1"])
        >>> next(source)
        {'x': 0}
        >>> next(target)
        {'state': <StreamState.PENDING: 1>}
        >>> next(target)
        {'x': 0}

Attributes:
    OPTS: Operator wrapper options.
    DEFAULTS: Default operator configuration.

"""

from logging import Logger
from typing import Any

import pygogo as gogo

from riko._pubsub import async_hub, sync_hub
from riko.bado.itertools import as_async
from riko.modules._prepare import require_arg
from riko.types._configs import SendObjconf
from riko.types._options import Defaults, Opts
from riko.types._streams import Feed, Stream
from riko.types._wrappers import PipeTuples

from . import operator

OPTS: Opts = {"pollable": True, "emit": True}
DEFAULTS: Defaults = {"max_wait": 5}
logger: Logger = gogo.Gogo(__name__, monolog=True).logger


async def async_parser(
    stream: Stream | Feed,
    objconf: SendObjconf,
    tuples: PipeTuples,
    *,
    others: list[str] | None = None,
    **kwargs: object,
) -> Stream:
    """
    Asynchronously publishes each item to every target, then returns them.

    Receivers may start before or after the sender, so no startup ordering is
    needed. Targets are completed even when a publish fails, so a healthy receiver isn't
    left waiting.

    Args:
        stream: The source, sync or async. Note: this shares the `tuples`
            iterator, so consuming it will consume `tuples` as well.

        objconf: The pipe configuration, containing `max_wait`.

        tuples: Iterable of (item, objconf). Note: this shares the `stream`
            iterator, so consuming it will consume `stream` as well.

        others: Receivers to push to. Required.

    Returns:
        A sync iterator over each source item, unchanged. Awaiting publishes the
        whole source, so an unbounded one never returns and a finite one is held
        in memory.

    Raises:
        TypeError: If ``others`` is not given.
        ReceiverUnavailableError: If a target never starts within ``max_wait``.

    """
    others = require_arg(others, "others", "send", strict=True)
    timeout = objconf.max_wait
    sent = []

    try:
        async for item in as_async(stream):
            await async_hub.publish(others, item, timeout=timeout)
            sent.append(item)
    finally:
        await async_hub.complete(others)

    return iter(sent)


def parser(
    stream: Stream,
    objconf: SendObjconf,
    tuples: PipeTuples,
    *,
    others: list[str] | None = None,
    ids: dict[str, int] | None = None,
    **kwargs: object,
) -> Stream:
    """
    Publishes each item to every target, then yields it unchanged.

    Args:
        stream: The source. Note: this shares the `tuples` iterator, so
            consuming it will consume `tuples` as well.

        objconf: The pipe configuration. Unused on this path.

        tuples: Iterable of (item, objconf). Note: this shares the `stream`
            iterator, so consuming it will consume `stream` as well.

        others: Receivers to push to. Required.

        ids: Mapping of receiver name to delivery id (default: None).

    Yields:
        Each source item, unchanged.

    Raises:
        TypeError: If ``others`` is not given.

    Examples:
        >>> from itertools import repeat
        >>> from riko.modules.receive import pipe as receiver
        >>>
        >>> target = receiver(conf={"name": "receiver2", "wait": 0.01, "max_wait": 2})
        >>> next(target)
        {'state': <StreamState.PENDING: 1>}
        >>> stream = ({"x": x} for x in range(5))
        >>> tuples = zip(stream, repeat(None))
        >>> source = parser(stream, None, tuples, others=["receiver2"])
        >>> next(source)
        {'x': 0}
        >>> next(target)
        {'state': <StreamState.PENDING: 1>}
        >>> next(target)
        {'x': 0}

    """
    others = require_arg(others, "others", "send", strict=True)

    for item in stream:
        for target in others:
            target_id = sync_hub.send(target, item)

            if ids is not None and target_id is not None:
                ids[target] = target_id

        yield item


@operator(DEFAULTS, isasync=True, **OPTS)
async def async_pipe(*args: Any, **kwargs: object) -> Stream:
    """
    Asynchronously pushes items to named receivers.

    Items pass through unchanged, so this can sit mid-pipeline. Every target is
    completed even when a publish fails, so a receiver on a healthy channel is
    never left waiting on one nobody will close. Unlike the sync `pipe`, the
    source is published in full before the first item is observable downstream.

    Args:
        items (Items | Feed): The source stream, sync or async.

        conf (dict): The pipe configuration.

            max_wait (int | float): Seconds to wait for a target to subscribe
                before raising (default: 5).

        context (Context): the execution context

    Kwargs:
        others (list[str]): Receiver names each item is pushed to. Required.

    Yields:
        Item, unchanged.

    Raises:
        TypeError: If ``others`` is not given.
        ReceiverUnavailableError: If a target never subscribes within ``max_wait``.

    """
    return await async_parser(*args, **kwargs)


@operator(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> Stream:
    """
    Pushes each items to named receivers.

    Items pass through unchanged, so this can sit mid-pipeline.

    Args:
        items (Items): The source stream.
        conf (dict): The pipe configuration. Unused on this path.
        context (Context): the execution context

    Kwargs:
        others (list[str]): Receiver names each item is pushed to. Required.
        ids (dict[str, int]): Mapping of receiver name to delivery id (default: None).

    Yields:
        Item, unchanged.

    Raises:
        TypeError: If ``others`` is not given.

    Examples:
        >>> from riko.modules.receive import pipe as receiver
        >>>
        >>> target = receiver(conf={"name": "receiver3", "wait": 0.01, "max_wait": 2})
        >>> next(target)
        {'state': <StreamState.PENDING: 1>}
        >>> source = pipe([{"x": 0}], others=["receiver3"])
        >>> next(source)
        {'x': 0}
        >>> next(target)
        {'state': <StreamState.PENDING: 1>}
        >>> next(target)
        {'x': 0}

    """
    return parser(*args, **kwargs)
