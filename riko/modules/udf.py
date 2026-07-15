# vim: sw=4:ts=4:expandtab
"""
Provides functions for performing an arbitrary (user-defined) function on an
item.

Examples:
    basic usage::

        >>> from riko.modules.udf import pipe
        >>>
        >>> func = lambda item: {'y': item['x'] + 3}
        >>> next(pipe({'x': 0}, func=func))
        {'y': 3}

"""

from collections.abc import Callable
from typing import cast

import pygogo as gogo

from riko import Objconf
from riko.types.general import Defaults, Extraction, Item, Opts

from . import processor

OPTS: Opts = {"listize": True, "emit": True}
DEFAULTS: Defaults = {}
logger = gogo.Gogo(__name__, monolog=True).logger


def parser(item: Item, extraction: Extraction, objconf: Objconf, **kwargs) -> Item:
    """
    Parsers the pipe content

    Args:
        item (obj): The entry to process (a DotDict instance)
        objconf (obj): The pipe configuration (an Objectify instance)
        kwargs (dict): Keyword arguments

    Kwargs:
        stream (dict): The original item

    Returns:
        dict: The item

    Examples:
        >>> from riko.dotdict import DotDict
        >>> from itertools import repeat
        >>>
        >>> func = lambda item: {'y': item['x'] + 3}
        >>> item = DotDict({'x': 0})
        >>> parser(item, None, None, stream=item, func=func)
        {'y': 3}

    """
    func = cast(Callable[[Item], Item], kwargs["func"])
    return func(item)


# TODO: add support for async functions
@processor(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args, **kwargs) -> Item:
    """
    A processor that asynchronously performs an arbitrary (user-defined)
    function on an item.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        func (callable): User defined function to apply to each stream item.

    Returns:
        Deferred: twisted.internet.defer.Deferred truncated stream

    Examples:
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> async def run(reactor):
        ...     func = lambda item: {'y': item['x'] + 3}
        ...     result = await async_pipe({'x': 0}, func=func)
        ...     print(next(result))
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        {'y': 3}

    """
    return parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs) -> Item:
    """
    A processor that performs an arbitrary (user-defined) function
    on an item.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        func (callable): User defined function to apply to each stream item.

    Yields:
        dict: an item

    Examples:
        >>> func = lambda item: {'y': item['x'] + 3}
        >>> next(pipe({'x': 0}, func=func))
        {'y': 3}

    """
    return parser(*args, **kwargs)
