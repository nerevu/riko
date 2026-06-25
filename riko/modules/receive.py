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
        >>> target = receiver(conf={'name': 'receiver1', 'wait': 0.01, 'max_wait': 2}, func=noop)
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

from collections.abc import Callable, Generator, Iterator, Mapping
from time import sleep
from typing import cast

import pygogo as gogo
from meza.fntools import dfilter

from riko import Objconf
from riko.cast import BasicCastType
from riko.types.general import Defaults, Item, Opts, PipeTuples, Stream
from riko.types.values import StatefulItem, StreamState
from riko.utils import _receive_queue, _registry, close, coroutine

from . import operator

OPTS: Opts = {"ftype": BasicCastType.NONE, "pollable": True}
DEFAULTS: Defaults = {"wait": 1, "max_wait": 5}
logger = gogo.Gogo(__name__, monolog=True).logger


def parser(
    _: Stream,
    objconf: Objconf,
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
    name = objconf.name
    wait = objconf.wait
    max_wait = objconf.max_wait
    total_waited = 0

    # See https://github.com/ICRAR/ijson#push-interfaces
    if name not in _registry:
        fkwargs = dfilter(kwargs, ["conf", "assign", "stream"])

        @coroutine(registry_name=name, maxlen=objconf.max_len)
        def receiver() -> Generator[None, Item | StatefulItem, None]:
            while True:
                item = yield

                if item is not None:
                    if isinstance(item, Mapping) and "state" in item:
                        state = cast(StreamState, item["state"])
                    else:
                        state = None

                    try:
                        result = func(item, **fkwargs) if func else item
                    except TypeError:
                        result = func(item)

                    _receive_queue[name].append((state, result))

        receiver()

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
