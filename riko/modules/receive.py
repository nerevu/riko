# vim: sw=4:ts=4:expandtab
"""
Receives items pushed by the send module.

Pairs with ``send`` for in-process fan-out: ``receive`` subscribes to a sender as named
``others``.

This is the low-level interface: it must be primed (the first ``next()`` registers the
channel) and it emits a ``StreamState.PENDING`` marker on every poll that finds the queue
empty, so a caller has to filter those out. ``riko.SyncPipe.subscribe`` is the high-level
path — it registers up front and drains without ever emitting a marker.

Examples:
    Basic usage::

        >>> from riko.modules.receive import pipe as receiver
        >>> from riko.modules.send import pipe as sender
        >>>
        >>> conf = {"name": "receiver1", "wait": 0.01, "max_wait": 2}
        >>> target = receiver(conf=conf)
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

from collections.abc import Callable, Iterator, Mapping
from inspect import signature
from logging import Logger
from time import sleep
from typing import Any, cast

import pygogo as gogo
from meza.fntools import dfilter

from riko._pubsub import async_hub, coroutine, sync_hub
from riko._pubsub._types import ReceiveFunc, Receiver
from riko._strutils import gen_name
from riko.bado._backend import fail_after
from riko.cast import BasicCastType
from riko.exceptions import ReceiveTimeoutError
from riko.types._configs import ReceiveObjconf
from riko.types._guards import is_missing_type, is_stateful_item
from riko.types._options import Defaults, Opts
from riko.types._sentinels import MISSING, StreamState
from riko.types._streams import Item, StatefulItem, Stream, StreamOrValueStream
from riko.types._wrappers import PipeTuples

from . import operator

OPTS: Opts = {"ftype": BasicCastType.NONE, "pollable": True}
DEFAULTS: Defaults = {"name": "", "wait": 1, "max_wait": 5, "max_len": 256}
logger: Logger = gogo.Gogo(__name__, monolog=True).logger


def _apply(func: ReceiveFunc, item: Item, **fkwargs: object) -> Item | None:
    try:
        params = signature(func).parameters
    except (TypeError, ValueError):
        kwargs = {}
    else:
        if any(p.kind == p.VAR_KEYWORD for p in params.values()):
            kwargs = fkwargs
        else:
            kwargs = {k: v for k, v in fkwargs.items() if k in params}

    return func(item, **kwargs)


def register_receiver(
    name: str,
    maxlen: int | None = None,
    func: ReceiveFunc | None = None,
    *,
    on_receive: Callable[[Item], object] | None = None,
    on_complete: Callable[[], object] | None = None,
    func_kwargs: Mapping[str, object] | None = None,
) -> None:
    # See https://github.com/ICRAR/ijson#push-interfaces
    if func is not None and on_receive is not None:
        msg = "the 'receive' pipe accepts either 'func' or 'on_receive', not both"
        raise TypeError(msg)

    if name not in sync_hub.receivers:
        fkwargs = dfilter(func_kwargs or {}, ["conf", "assign", "stream"])

        @coroutine(registry_name=name, maxlen=maxlen)
        def receiver() -> Receiver:
            while True:
                item = yield

                if item is not None:
                    state, result = None, MISSING

                    if is_stateful_item(item):
                        state = item["state"]

                        if state is StreamState.DONE and on_complete is not None:
                            on_complete()
                    else:
                        item = cast(Item, item)

                        if on_receive is not None:
                            on_receive(item)
                            continue

                        result = _apply(func, item, **fkwargs) if func else item

                    queue = sync_hub.queues[name]

                    if queue.maxlen is not None and len(queue) >= queue.maxlen:
                        msg = f"Receiver {name!r} queue full (maxlen={queue.maxlen}); "
                        msg += "dropping oldest item."
                        logger.warning(msg)

                    queue.append((state, result))

        receiver()


async def async_parser(
    _: Stream,
    objconf: ReceiveObjconf,
    tuples: PipeTuples,
    func: Callable[[Item], Item] | None = None,
    **kwargs: object,
) -> Stream:
    """
    Asynchronously collects items the sender pushes.

    Each wait for the next item or sender completion is bounded by ``max_wait``.
    Receiving an item starts a fresh idle window, so active long-lived senders are
    not limited by the total receiver lifetime.

    Args:
        _: The source stream. Unused; items arrive from the sender.
        objconf: The pipe configuration, containing `name` and `max_wait`.
        tuples: Iterable of (item, objconf). Unused.

        func: Applied to each received item. It gets the kwargs it names, or
            all of them if it accepts ``**kwargs``. The pipe's own ``conf``,
            ``assign``, and ``stream`` are always withheld (default: None).

    Returns:
        Every item received before the sender finished.

    Raises:
        ReceiveTimeoutError: If no item or sender completion arrives within
            ``max_wait`` seconds.

    """
    name = objconf.name or "".join(gen_name())
    max_wait = objconf.max_wait
    fkwargs = dfilter(kwargs, ["conf", "assign", "stream"])
    results: list[Item] = []

    async with async_hub.subscribe(name) as receive_stream:
        while True:
            try:
                with fail_after(max_wait):
                    item = await anext(receive_stream)
            except StopAsyncIteration:
                break
            except TimeoutError as e:
                raise ReceiveTimeoutError(name, max_wait) from e

            results.append(cast(Item, _apply(func, item, **fkwargs) if func else item))

    return iter(results)


def parser(
    _: Stream,
    objconf: ReceiveObjconf,
    tuples: PipeTuples,
    func: Callable[[Item], Item | None] | None = None,
    **kwargs: object,
) -> StreamOrValueStream | Iterator[StatefulItem]:
    """
    Yields items as the sender pushes them.

    Args:
        _: The source stream. Unused; items arrive from the sender.

        objconf: The pipe configuration, containing `name`, `wait`, `max_wait`
            and `max_len`.

        tuples: Iterable of (item, objconf). Unused.

        func: Applied to each received item. It gets the kwargs it names, or
            all of them if it accepts ``**kwargs``. The pipe's own ``conf``,
            ``assign``, and ``stream`` are always withheld (default: None).

    Yields:
        Each received item, or ``StreamState.PENDING`` while waiting. Stops
        when the sender finishes, or after ``max_wait`` seconds without an
        item.

    Examples:
        >>> from itertools import repeat
        >>> from riko.modules.send import pipe as sender
        >>> from meza.fntools import Objectify
        >>>
        >>> conf = {"wait": 0.01, "max_wait": 2, "name": "receiver2"}
        >>> target = parser(None, Objectify(conf), None)
        >>> next(target)
        {'state': <StreamState.PENDING: 1>}
        >>> stream = ({"x": x} for x in range(5))
        >>> source = sender(stream, others=["receiver2"])
        >>> next(source)
        {'x': 0}
        >>> next(target)
        {'x': 0}

    """
    name = objconf.name or "".join(gen_name())
    wait = objconf.wait
    max_wait = objconf.max_wait
    total_waited = 0
    register_receiver(name, maxlen=objconf.max_len, func=func, func_kwargs=kwargs)

    while True:
        if _buf := sync_hub.queues[name]:
            total_waited = 0
            state, result = _buf.popleft()

            if state is StreamState.DONE:
                sync_hub.close(name)
                break
            elif not is_missing_type(result):
                yield result
        elif total_waited >= max_wait:
            sync_hub.close(name)
            break
        else:
            sleep(wait)
            total_waited += wait
            yield StatefulItem(state=StreamState.PENDING)


@operator(DEFAULTS, isasync=True, **OPTS)
async def async_pipe(*args: Any, **kwargs: object) -> Stream:
    """
    Asynchronously receives items pushed by the send module.

    Collects every item the sender pushes and yields them once the sender finishes.

    Args:
        items (Items): The source stream. Unused.

        conf (dict): The pipe configuration.

            name (str): Receiver identifier the sender targets. A random name
                is generated when unset (default: "").

            max_wait (int | float): Seconds to wait without an item or sender
                completion before raising ``ReceiveTimeoutError`` (default: 5).

        context (Context): the execution context

    Kwargs:
        func (callable): Applied to each received item before it is yielded.
            It gets the kwargs it names, or all of them if it accepts
            ``**kwargs``. The pipe's own ``conf``, ``assign``, and ``stream``
            are always withheld (default: None).

    Yields:
        Every item received before the sender finished.

    Notes:
        ``max_wait`` is an idle timeout and resets after each item. ``wait`` and
        ``max_len`` apply only to the sync pipe.

    """
    return await async_parser(*args, **kwargs)


@operator(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> StreamOrValueStream | Iterator[StatefulItem]:
    """
    Receives items pushed by the send module.

    Yields each item as the sender pushes it and emits a ``StreamState.PENDING`` marker
    while waiting. Stops waiting after ``max_wait`` seconds.

    Args:
        items (Items): The source stream. Unused.

        conf (dict): The pipe configuration.

            name (str): Receiver identifier the sender targets. A random name
                is generated when unset (default: "").

            wait (int | float): Seconds to sleep between polls (default: 1).

            max_wait (int | float): Seconds to wait without an item before
                giving up (default: 5).

            max_len (int): Queue capacity. The oldest item is dropped with a
                warning when full (default: 256).

        context (Context): the execution context

    Kwargs:
        func (callable): Applied to each received item before it is yielded.
            It gets the kwargs it names, or all of them if it accepts
            ``**kwargs``. The pipe's own ``conf``, ``assign``, and ``stream``
            are always withheld (default: None).

    Yields:
        - each received item as the sender pushes it
        - ``{"state": StreamState.PENDING}`` while waiting

    Notes:
        The marker exists so a poll on an empty queue neither blocks nor ends
        the stream. Setting ``max_wait`` to 0 makes the drain non-blocking
        instead, which renders the marker unreachable — that is what
        ``riko.SyncPipe.subscribe`` does.

    Examples:
        >>> from riko.modules.send import pipe as sender
        >>>
        >>> target = pipe(conf={"name": "receiver3", "wait": 0.01, "max_wait": 2})
        >>> next(target)
        {'state': <StreamState.PENDING: 1>}
        >>> source = sender([{"x": 0}], others=["receiver3"])
        >>> next(source)
        {'x': 0}
        >>> next(target)
        {'state': <StreamState.PENDING: 1>}
        >>> next(target)
        {'x': 0}

    """
    return parser(*args, **kwargs)
