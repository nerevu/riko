# vim: sw=4:ts=4:expandtab
"""
Provides functions for converting a text string into a datetime. Loopable.

Delegates to ``riko.cast.cast_datetime``, so it accepts an absolute date in
most common formats, the shorthands ``"today"``/``"tomorrow"``/``"yesterday"``/
``"now"``, a counted offset such as ``"3 days"`` or ``"-1 month"``, and the word
forms ``"next week"`` and ``"last year"``.

Examples:
    basic usage::

        >>> from riko.modules.datebuilder import pipe
        >>>
        >>> next(pipe({'content': '12/2/2014'}))['datebuilder'].tm_year
        2014

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options

"""

from logging import Logger
from time import struct_time
from typing import Any

import pygogo as gogo

from riko.cast import BasicCastType, cast_datetime
from riko.types.configs import DynamicConf
from riko.types.general import Defaults, Extraction, Opts
from riko.types.values import DateLikeType

from . import processor

OPTS: Opts = {"ptype": BasicCastType.NONE, "field": "content"}
DEFAULTS: Defaults = {}
logger: Logger = gogo.Gogo(__name__, monolog=True).logger


def parser(
    text: str, extraction: Extraction, objconf: DynamicConf, **kwargs: object
) -> struct_time:
    """
    Parsers the pipe content

    Args:
        text (str): The text to convert
        _ (None): Ignored.
        kwargs (dict): Keyword arguments

    Kwargs:
        assign (str): Attribute to assign parsed content (default: datebuilder)
        stream (dict): The original item

    Returns:
        dict: The item

    Examples:
        >>> item = {'content': '12/2/2014'}
        >>> kwargs = {'stream': item}
        >>> parser(item['content'], None, None, stream=item).tm_year
        2014

    """
    try:
        new_date = cast_datetime(text) if isinstance(text, DateLikeType) else None
    except ValueError:
        new_date = None

    if new_date is None:
        raise ValueError(f"the 'datebuilder' pipe got an unrecognized date {text!r}")

    return new_date.timetuple()


@processor(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args: Any, **kwargs: object) -> struct_time:
    """
    A processor module that asynchronously converts a text string into a datetime.

    Args:
        item (dict or Iter[dict]): The entry, or stream of entries, to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        assign (str): Attribute to assign parsed content (default: datebuilder)
        field (str): Item attribute to operate on (default: 'content')

    Returns:
       Awaitable: item with date timetuples

    Examples:
        >>> from riko import run
        >>>
        >>> async def main():
        ...     result = await async_pipe({'content': '12/2/2014'})
        ...     print(next(result)['datebuilder'].tm_year)
        >>>
        >>> run(main)
        2014

    """
    return parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> struct_time:
    """
    A processor that converts a text string into a datetime.

    Args:
        item (dict or Iter[dict]): The entry, or stream of entries, to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        assign (str): Attribute to assign parsed content (default: datebuilder)
        field (str): Item attribute to operate on (default: 'content')

    Yields:
        dict: an item with date timetuples

    Examples:
        >>> next(pipe({"content": "12/2/2014"}))["datebuilder"].tm_year
        2014
        >>> next(pipe({"content": "5/4/82"}, emit=True))[:3]
        (1982, 5, 4)
        >>> next(pipe({"content": "tomorrow"}, emit=True)).tm_hour
        0
        >>> yesterday = next(pipe({"content": "-1 day"}, emit=True))
        >>> yesterday == next(pipe({"content": "yesterday"}, emit=True))
        True
        >>> next(pipe({"content": "bogus"}))
        Traceback (most recent call last):
            ...
        ValueError: the 'datebuilder' pipe got an unrecognized date 'bogus'

    """
    return parser(*args, **kwargs)
