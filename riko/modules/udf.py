# vim: sw=4:ts=4:expandtab
"""
riko.modules.udf
~~~~~~~~~~~~~~~~
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

import pygogo as gogo

from riko import Objconf
from riko.types.general import BasicArg, ComplexArg, Extraction

from . import processor

OPTS = {"listize": True, "emit": True}
DEFAULTS = {}
logger = gogo.Gogo(__name__, monolog=True).logger


def parser(
    item: BasicArg, extraction: Extraction, objconf: Objconf, skip=False, **kwargs
) -> ComplexArg:
    """
    Parsers the pipe content

    Args:
        item (obj): The entry to process (a DotDict instance)
        objconf (obj): The pipe configuration (an Objectify instance)
        skip (bool): Don't parse the content
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
    return kwargs["stream"] if skip else kwargs["func"](item)


@processor(DEFAULTS, isasync=True, **OPTS)  # pyright: ignore[reportArgumentType]
def async_pipe(*args, **kwargs):
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
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x))
        ...     func = lambda item: {'y': item['x'] + 3}
        ...     d = async_pipe({'x': 0}, func=func)
        ...     return d.addCallbacks(callback, logger.error)
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
def pipe(*args, **kwargs):
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
