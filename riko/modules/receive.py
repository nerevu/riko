# vim: sw=4:ts=4:expandtab
"""
Provides functions for receiving items of a stream to a function using generator based
coroutines.

Examples:
    basic usage::

        >>> from riko.modules.receive import pipe as receiver
        >>> from riko.modules.send import pipe as sender
        >>> from riko.utils import noop
        >>>
        >>> conf = {'name': 'receiver1', 'wait': 0.01, 'max_wait': 2}
        >>> target = receiver(conf=conf, func=noop)
        >>> next(target)
        {'state': <StreamState.PENDING: 1>}
        >>> stream = ({'x': x} for x in range(5))
        >>> source = sender(stream, others=['receiver1'])
        >>> next(source)
        {'x': 0}
        >>> next(target)
        {'state': <StreamState.PENDING: 1>}
        >>> next(target)
        {'x': 0}


Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options

"""

from collections.abc import Callable, Generator, Iterator
from inspect import signature
from random import choice
from time import sleep

import pygogo as gogo
from meza.fntools import dfilter

from riko._pubsub import async_hub
from riko.cast import BasicCastType
from riko.types.configs import ReceiveObjconf
from riko.types.general import Defaults, Item, Opts, PipeTuples, Stream
from riko.types.guards import is_stateful_item
from riko.types.values import StatefulItem, StreamState
from riko.utils import _receive_queue, _registry, close, coroutine

from . import operator

OPTS: Opts = {"ftype": BasicCastType.NONE, "pollable": True}
DEFAULTS: Defaults = {"name": "", "wait": 1, "max_wait": 5}
logger = gogo.Gogo(__name__, monolog=True).logger

ONSETS = (
    "b",
    "br",
    "cl",
    "cr",
    "d",
    "dr",
    "f",
    "fl",
    "g",
    "gr",
    "k",
    "m",
    "n",
    "p",
    "pl",
    "r",
    "s",
    "sl",
    "st",
    "t",
    "tr",
    "v",
)
VOWELS = "aeiou"
CODAS = ("", "l", "m", "n", "r", "s", "th", "nd", "nt", "ck")

ADJECTIVES = [
    "ancient",
    "autumn",
    "bold",
    "brisk",
    "calm",
    "crimson",
    "gentle",
    "hidden",
    "lucky",
    "misty",
    "rapid",
    "silent",
    "silver",
    "steady",
    "wild",
]


def gen_name(count=2) -> Iterator[str]:
    yield choice(ADJECTIVES)  # noqa: S311
    yield "-"

    for _ in range(count):
        yield "".join(map(choice, [ONSETS, VOWELS, CODAS]))  # noqa: S311


def _apply(func: Callable, item: Item | StatefulItem, **fkwargs) -> Item:
    if not is_stateful_item(item):
        try:
            params = signature(func).parameters
        except (TypeError, ValueError):
            allowed = {}
        else:
            if any(p.kind == p.VAR_KEYWORD for p in params.values()):
                allowed = fkwargs
            else:
                allowed = {k: v for k, v in fkwargs.items() if k in params}

        return func(item, **allowed)


def _register_receiver(name, objconf, func, kwargs) -> None:
    # See https://github.com/ICRAR/ijson#push-interfaces
    if name not in _registry:
        fkwargs = dfilter(kwargs, ["conf", "assign", "stream"])

        @coroutine(registry_name=name, maxlen=objconf.max_len)
        def receiver() -> Generator[None, Item | StatefulItem, None]:
            while True:
                item = yield

                if item is not None:
                    state = item["state"] if is_stateful_item(item) else None
                    result = _apply(func, item, **fkwargs) if func else item
                    queue = _receive_queue[name]

                    if (
                        queue
                        and queue.maxlen is not None
                        and len(queue) >= queue.maxlen
                    ):
                        msg = f"Receiver {name!r} queue full (maxlen={queue.maxlen}); "
                        msg += "dropping oldest item."
                        logger.warning(msg)

                    queue.append((state, result))

        receiver()


def parser(
    _: Stream,
    objconf: ReceiveObjconf,
    tuples: PipeTuples,
    func: Callable[[Item | StatefulItem], Item] | None = None,
    **kwargs,
) -> Stream | Iterator[StatefulItem]:
    """
    Parses the pipe content
    Args:
        objconf (obj): the item independent configuration (an Objectify
            instance).

        tuples (Iter[(dict, obj)]): Iterable of tuples of (item, objconf)
            `item` is an element in the source stream and `objconf` is the item
            configuration (an Objectify instance). Note: this shares the
            `stream` iterator, so consuming it will consume `stream` as well.

    Kwargs:
        func

    Returns:
        Iter[dict]: The stream of items

    Examples:
        >>> from itertools import repeat
        >>> from riko.modules.send import pipe as sender
        >>> from riko.utils import noop
        >>> from meza.fntools import Objectify
        >>>
        >>> conf = {'wait': 0.01, 'max_wait': 2, 'name': 'receiver2'}
        >>> target = parser(None, Objectify(conf), None, func=noop)
        >>> next(target)
        {'state': <StreamState.PENDING: 1>}
        >>> stream = ({'x': x} for x in range(5))
        >>> source = sender(stream, others=['receiver2'])
        >>> next(source)
        {'x': 0}
        >>> next(target)
        {'x': 0}

    """
    name = objconf.name or "".join(gen_name())
    wait = objconf.wait
    max_wait = objconf.max_wait
    total_waited = 0
    _register_receiver(name, objconf, func, kwargs)

    while True:
        if _buf := _receive_queue[name]:
            total_waited = 0
            state, result = _buf.popleft()

            if state is StreamState.DONE:
                close(name)
                break
            else:
                yield result
        elif total_waited >= max_wait:
            close(name)
            break
        else:
            sleep(wait)
            total_waited += wait
            yield StatefulItem(state=StreamState.PENDING)


async def async_parser(
    _: Stream,
    objconf: ReceiveObjconf,
    tuples: PipeTuples,
    func: Callable[[Item | StatefulItem], Item] | None = None,
    **kwargs,
) -> Stream:
    """
    Asynchronously receives pushed items (materialized).

    Subscribes to the named AnyIO channel and collects items until the sender
    completes (channel closure). Registration *is* readiness, so no polling,
    sleep, or DONE sentinel is involved. Note: this is *materialized* — results
    are returned only once the channel closes; incremental (yield-as-received)
    delivery awaits P7.3.
    """
    name = objconf.name or "".join(gen_name())
    fkwargs = dfilter(kwargs, ["conf", "assign", "stream"])
    results: list[Item] = []

    async with async_hub.subscribe(name) as receive_stream:
        async for item in receive_stream:
            results.append(_apply(func, item, **fkwargs) if func else item)

    return iter(results)


@operator(DEFAULTS, **OPTS)
def pipe(*args, **kwargs) -> Stream | Iterator[StatefulItem]:
    """
    A source that fetches and parses the first feed found on a site.

    Args:
        item (dict): The entry to process (not used)
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        func (callable): The user defined function to apply to each stream item
        conf (dict): The pipe configuration. Must contain the key 'name'.

            name (str): The receiver identifier

    Yields:
        dict: item

    Examples:
        >>> from riko.modules.send import pipe as sender
        >>> from riko.utils import noop
        >>>
        >>> target = pipe(conf={'name': 'receiver3', 'wait': 0.01, 'max_wait': 2}, func=noop)
        >>> next(target)
        {'state': <StreamState.PENDING: 1>}
        >>> source = sender([{'x': 0}], others=['receiver3'])
        >>> next(source)
        {'x': 0}
        >>> next(target)
        {'state': <StreamState.PENDING: 1>}
        >>> next(target)
        {'x': 0}

    """
    return parser(*args, **kwargs)


@operator(DEFAULTS, isasync=True, **OPTS)
async def async_pipe(*args, **kwargs) -> Stream:
    """An async operator that receives pushed stream items (materialized)."""
    return await async_parser(*args, **kwargs)
