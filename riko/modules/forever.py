# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    riko.modules.forever
    ~~~~~~~~~~~~~~~~~~~~
    Provides methods for mocking an input source. This enables other modules,
    e.g. date builder, to be called so they can continue to consume values from
    indirect terminal inputs. Loopable.

Examples:
    basic usage::

        >>> from riko.modules.forever import pipe
        >>>
        >>> next(pipe())
        True

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""
import pygogo as gogo

from . import processor
from itertools import takewhile, repeat

forever = takewhile(bool, repeat({'forever': True}))

OPTS = {"ftype": "none"}
DEFAULTS = {}
logger = gogo.Gogo(__name__, monolog=True).logger


def parser(_, objconf, skip=False, **kwargs):
    """Parses the pipe content

    Args:
        _ (None): Ignored
        objconf (obj): The pipe configuration (an Objectify instance)
        skip (bool): Don't parse the content
        kwargs (dict): Keyword arguments

    Kwargs:
        stream (dict): The original item
        conf (dict): The pipe configuration

    Returns:
        Iter[dict]: The stream of items

    Examples:
        >>> result = parser(None, None, stream={})
        >>> next(result)
    """
    return kwargs["stream"] if skip else forever


@processor(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args, **kwargs):
    """A source that asynchronously fetches and parses a feed to return the
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
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x))
        ...     d = async_pipe()
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        True
    """
    return parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs):
    """A source that fetches and parses a feed to return the entries.

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
    """
    return parser(*args, **kwargs)
