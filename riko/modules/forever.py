# vim: sw=4:ts=4:expandtab
"""
Provides methods for mocking an input source. This enables other modules,
e.g. date builder, to be called so they can continue to consume values from
indirect terminal inputs. Loopable.

Examples:
    basic usage::

        >>> from riko.modules.forever import pipe
        >>>
        >>> next(pipe())
        {'forever': True}

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options

"""

from collections.abc import Iterator
from itertools import repeat, takewhile

import pygogo as gogo

from riko import Objconf
from riko.cast import BasicCastType
from riko.types.general import Defaults, Extraction, Item, Opts

from . import processor

OPTS: Opts = {"ftype": BasicCastType.NONE}
DEFAULTS: Defaults = {}
logger = gogo.Gogo(__name__, monolog=True).logger


def parser(
    _: Item, extraction: Extraction, objconf: Objconf, **kwargs
) -> Iterator[dict[str, bool]]:
    """
    Parses the pipe content

    Args:
        _ (None): Ignored
        objconf (obj): The pipe configuration (an Objectify instance)
        kwargs (dict): Keyword arguments

    Kwargs:
        stream (dict): The original item
        conf (dict): The pipe configuration

    Returns:
        Iter[dict]: The stream of items

    Examples:
        >>> result = parser(None, None, None)
        >>> next(result)
        {'forever': True}

    """
    return takewhile(bool, repeat({"forever": True}))


@processor(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args, **kwargs) -> Iterator[dict[str, bool]]:
    """
    A source that asynchronously fetches and parses a feed to return the
    entries.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'url'. May
            contain the key 'delay'.

            url (str): The web site to fetch.
            delay (flt): Amount of time to sleep (in secs) before fetching the
                url. Useful for simulating network latency. Default: 0.


    Returns:
        Deferred: twisted.internet.defer.Deferred iterator of items

    Examples:
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> async def run(reactor):
        ...     result = await async_pipe()
        ...     print(next(result))
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        {'forever': True}

    """
    return parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs) -> Iterator[dict[str, bool]]:
    """
    A source that fetches and parses a feed to return the entries.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'url'. May
            contain the key 'delay'.

            url (str): The web site to fetch.
            delay (flt): Amount of time to sleep (in secs) before fetching the
                url. Useful for simulating network latency. Default: 0.

    Returns:
        dict: an iterator of items

    Examples:
        >>> from riko import get_path
        >>>
        >>> next(pipe())
        {'forever': True}

    """
    return parser(*args, **kwargs)
