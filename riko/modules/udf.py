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
from inspect import iscoroutinefunction
from logging import Logger
from typing import Any

import pygogo as gogo

from riko.modules._prepare import require_kwarg
from riko.types.configs import UdfObjconf
from riko.types.general import Defaults, Extraction, Item, Opts

from . import processor

OPTS: Opts = {"listize": True, "emit": True}
DEFAULTS: Defaults = {}

logger: Logger = gogo.Gogo(__name__, monolog=True).logger


async def async_parser(
    item: Item, extraction: Extraction, objconf: UdfObjconf, **kwargs: object
) -> Item:
    """
    Parsers the pipe content asynchronously

    Args:
        item: The entry to process (a DotDict instance)
        objconf: The pipe configuration (an Objectify instance)
        kwargs: Keyword arguments

    Kwargs:
        stream: The original item

    Returns:
        dict: The item

    Raises:
        TypeError: If ``func`` is not given.

    Examples:
        >>> from riko.dotdict import DotDict
        >>> from itertools import repeat
        >>> from riko import run
        >>>
        >>> async def main():
        ...     func = lambda item: {'y': item['x'] + 3}
        ...     item = DotDict({'x': 0})
        ...     print(await async_parser(item, None, None, stream=item, func=func))
        >>>
        >>> run(main)
        {'y': 3}

    """
    func: Callable[[Item], Item] = require_kwarg(kwargs, "func", "udf")
    return await func(item) if iscoroutinefunction(func) else func(item)


def parser(
    item: Item, extraction: Extraction, objconf: UdfObjconf, **kwargs: object
) -> Item:
    """
    Parsers the pipe content

    Args:
        item: The entry to process (a DotDict instance)
        objconf: The pipe configuration (an Objectify instance)
        kwargs: Keyword arguments

    Kwargs:
        stream: The original item

    Returns:
        dict: The item

    Raises:
        TypeError: If ``func`` is not given.

    Examples:
        >>> from riko.dotdict import DotDict
        >>> from itertools import repeat
        >>>
        >>> func = lambda item: {'y': item['x'] + 3}
        >>> item = DotDict({'x': 0})
        >>> parser(item, None, None, stream=item, func=func)
        {'y': 3}

    """
    func: Callable[[Item], Item] = require_kwarg(kwargs, "func", "udf")
    return func(item)


# TODO: add support for async functions
@processor(DEFAULTS, isasync=True, **OPTS)
async def async_pipe(*args: Any, **kwargs: object) -> Item:
    """
    A processor that asynchronously performs an arbitrary (user-defined)
    function on an item.

    Args:
        item (dict or Iter[dict]): The entry, or stream of entries, to process
        kwargs: The keyword arguments passed to the wrapper

    Kwargs:
        func (callable): User defined function to apply to each stream item.

    Returns:
        Awaitable: truncated stream

    Raises:
        TypeError: If ``func`` is not given.

    Examples:
        >>> from riko import run
        >>>
        >>> async def main():
        ...     func = lambda item: {'y': item['x'] + 3}
        ...     result = await async_pipe({'x': 0}, func=func)
        ...     print(next(result))
        >>>
        >>> run(main)
        {'y': 3}

    """
    return await async_parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> Item:
    """
    A processor that performs an arbitrary (user-defined) function
    on an item.

    Args:
        item (dict or Iter[dict]): The entry, or stream of entries, to process
        kwargs: The keyword arguments passed to the wrapper

    Kwargs:
        func (callable): User defined function to apply to each stream item.

    Yields:
        dict: an item

    Raises:
        TypeError: If ``func`` is not given.

    Examples:
        >>> func = lambda item: {'y': item['x'] + 3}
        >>> next(pipe({'x': 0}, func=func))
        {'y': 3}

    """
    return parser(*args, **kwargs)
