# vim: sw=4:ts=4:expandtab
"""
Converts a text string into a date.

Accepts commonly formatted date, shorthands (``"today"``/``"tomorrow"``/``"yesterday"``/
``"now"``), offsets (``"3 days"``, ``"-1 month"``, etc.), and word forms
(``"next week"``, ``"last year"``, etc.).

Examples:
    Basic usage::

        >>> from riko.modules.datebuilder import pipe
        >>>
        >>> next(pipe({"content": "12/2/2014"}))["datebuilder"].tm_year
        2014

Attributes:
    OPTS: Processor wrapper options.
    DEFAULTS: Default processor configuration.

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
    Converts ``text`` into a date.

    Args:
        text: The text to convert.
        extraction: The extracted conf value. Unused.
        objconf: The pipe configuration. Unused.

    Returns:
        The date, as a time tuple.

    Raises:
        ValueError: If ``text`` names no date the pipe recognizes.

    Examples:
        >>> item = {"content": "12/2/2014"}
        >>> parser(item["content"], None, None, stream=item).tm_year
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
    Asynchronously converts a text string into a date.

    Both iterator and iterable sources are mapped over. See the FAQ's "How does a
    processor map over items?".

    Args:
        item (Item | Items): The entry, or stream of entries, to process.
        context (Context): the execution context

    Kwargs:
        field (str): Item attribute to convert (default: "content").

        assign (str): Field the date is assigned to. Ignored when ``emit`` is
            True (default: "datebuilder").

        emit (bool): Whether to emit the date in place of the item rather than
            assign it. Overrides ``assign`` (default: False).

    Yields:
        - merged ``{Item, <assign>: <date>}`` when ``emit`` is False and item is
          given (default)
        - ``{<assign>: <date>}`` when ``emit`` is False and no item given
        - ``<date>`` when ``emit`` is True

    Raises:
        ValueError: If the field names no date the pipe recognizes.

    Notes:
        An offset counts a unit from ``seconds`` to ``years``, signed or not.
        Sub-day units offset from the current time, the rest from today, and
        both resolve against the clock at call time.

        A ``date``, ``datetime``, or ``struct_time`` passes through, an ``int``
        reads as epoch seconds, and a partial date such as ``"2014"`` takes its
        missing parts from today.

    Examples:
        >>> from riko import run
        >>>
        >>> async def main():
        ...     result = await async_pipe({"content": "12/2/2014"})
        ...     print(next(result)["datebuilder"].tm_year)
        >>>
        >>> run(main)
        2014

    """
    return parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> struct_time:
    """
    Converts a text string into a date.

    Both iterator and iterable sources are mapped over. See the FAQ's "How does a
    processor map over items?".

    Args:
        item (Item | Items): The entry, or stream of entries, to process.
        context (Context): the execution context

    Kwargs:
        field (str): Item attribute to convert (default: "content").

        assign (str): Field the date is assigned to. Ignored when ``emit`` is
            True (default: "datebuilder").

        emit (bool): Whether to emit the date in place of the item rather than
            assign it. Overrides ``assign`` (default: False).

    Yields:
        - merged ``{Item, <assign>: <date>}`` when ``emit`` is False and item is
          given (default)
        - ``{<assign>: <date>}`` when ``emit`` is False and no item given
        - ``<date>`` when ``emit`` is True

    Raises:
        ValueError: If the field names no date the pipe recognizes.

    Notes:
        An offset counts a unit from ``seconds`` to ``years``, signed or not.
        Sub-day units offset from the current time, the rest from today, and
        both resolve against the clock at call time.

        A ``date``, ``datetime``, or ``struct_time`` passes through, an ``int``
        reads as epoch seconds, and a partial date such as ``"2014"`` takes its
        missing parts from today.

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
