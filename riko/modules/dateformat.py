# vim: sw=4:ts=4:expandtab
"""
Formats a date field as text.

``format`` is a ``strftime`` format string, so any specifier Python accepts
works: ``"%m-%d-%Y"`` gives ``02-12-2008``, ``"%R"`` gives ``20:45``, and
``"%A, %b %d, %y at %I:%M %p"`` gives ``Tuesday, Feb 12, 08 at 08:45 PM``.

Examples:
    Basic usage::

        >>> from datetime import date
        >>> from riko.modules.dateformat import pipe
        >>>
        >>> next(pipe({"date": date(2015, 5, 4)}))["dateformat"]
        '05/04/2015 00:00:00'

Attributes:
    OPTS: Processor wrapper options.
    DEFAULTS: Default processor configuration.

"""

import datetime
from logging import Logger
from typing import Any

import pygogo as gogo

from riko.cast import BasicCastType
from riko.types._configs import DateFormatObjconf
from riko.types._options import Defaults, Opts

from . import processor

OPTS: Opts = {"field": "date", "ftype": BasicCastType.DATETIME}
DEFAULTS: Defaults = {"format": "%m/%d/%Y %H:%M:%S"}
logger: Logger = gogo.Gogo(__name__, monolog=True).logger


def parser(
    date: datetime.date | None,
    extraction: object,
    objconf: DateFormatObjconf,
    **kwargs: object,
) -> str:
    """
    Formats ``date`` with the configured format string.

    Args:
        date: The date to format, or None when there is none.
        extraction: The extracted conf value. Unused.
        objconf: The pipe configuration, containing `format`.

    Returns:
        The formatted date, or ``""`` when there is no date to format.

    Examples:
        >>> from datetime import date
        >>> from meza.fntools import Objectify
        >>>
        >>> objconf = Objectify({"format": "%m/%d/%Y"})
        >>> parser(date(2015, 5, 4), None, objconf)
        '05/04/2015'

    """
    if date is None:
        formatted = ""
    else:
        formatted = date.strftime(objconf.format)

    return formatted


@processor(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args: Any, **kwargs: object) -> str:
    """
    Asynchronously formats a date field as text.

    Both iterator and iterable sources are mapped over. See the FAQ's "How does a
    processor map over items?".

    Args:
        item (Item | Items): The entry, or stream of entries, to process.

        conf (dict): The pipe configuration.

            format (str): ``strftime`` format string (default:
                "%m/%d/%Y %H:%M:%S", i.e. "02/12/2008 20:45:00").

        context (Context): the execution context

    Kwargs:
        field (str): Item attribute to format (default: "date").

        assign (str): Field the text is assigned to. Ignored when ``emit`` is
            True (default: "dateformat").

        emit (bool): Whether to emit the text in place of the item rather than
            assign it. Overrides ``assign`` (default: False).

    Yields:
        - merged ``{Item, <assign>: <text>}`` when ``emit`` is False and item is
          given (default)
        - ``{<assign>: <text>}`` when ``emit`` is False and no item given
        - ``<text>`` when ``emit`` is True

    Notes:
        The field is cast before formatting, so a ``date``, ``datetime``,
        ``struct_time``, epoch ``int``, or date string all work, and any time of
        day they carry is kept.

        A field that is missing or names no date yields ``""``.

    Examples:
        >>> from datetime import date
        >>> from riko import run
        >>>
        >>> async def main():
        ...     result = await async_pipe({"date": date(2015, 5, 4)})
        ...     print(next(result)["dateformat"])
        >>>
        >>> run(main)
        05/04/2015 00:00:00

    """
    return parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> str:
    """
    Formats a date field as text.

    Both iterator and iterable sources are mapped over. See the FAQ's "How does a
    processor map over items?".

    Args:
        item (Item | Items): The entry, or stream of entries, to process.

        conf (dict): The pipe configuration.

            format (str): ``strftime`` format string (default:
                "%m/%d/%Y %H:%M:%S", i.e. "02/12/2008 20:45:00").

        context (Context): the execution context

    Kwargs:
        field (str): Item attribute to format (default: "date").

        assign (str): Field the text is assigned to. Ignored when ``emit`` is
            True (default: "dateformat").

        emit (bool): Whether to emit the text in place of the item rather than
            assign it. Overrides ``assign`` (default: False).

    Yields:
        - merged ``{Item, <assign>: <text>}`` when ``emit`` is False and item is
          given (default)
        - ``{<assign>: <text>}`` when ``emit`` is False and no item given
        - ``<text>`` when ``emit`` is True

    Notes:
        The field is cast before formatting, so a ``date``, ``datetime``,
        ``struct_time``, epoch ``int``, or date string all work, and any time of
        day they carry is kept.

        A field that is missing or names no date yields ``""``.

    Examples:
        >>> from datetime import date, datetime
        >>>
        >>> item = {"date": date(2015, 5, 4)}
        >>> next(pipe(item))["dateformat"]
        '05/04/2015 00:00:00'
        >>> next(pipe(item, conf={"format": "%Y"}))["dateformat"]
        '2015'
        >>> next(pipe({"date": "05/04/2015"}))["dateformat"]
        '05/04/2015 00:00:00'
        >>> conf = {"format": "%A, %b %d, %y at %I:%M %p"}
        >>> stamp = {"date": datetime(2008, 2, 12, 20, 45)}
        >>> next(pipe(stamp, conf=conf))["dateformat"]
        'Tuesday, Feb 12, 08 at 08:45 PM'
        >>> next(pipe({}, conf=conf))["dateformat"]
        ''
        >>> next(pipe({"date": "bogus"}, conf=conf))["dateformat"]
        ''

    """
    return parser(*args, **kwargs)
