# vim: sw=4:ts=4:expandtab
"""
Provides functions for converting a text string into a datetime. Loopable.

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

from datetime import datetime as dt
from datetime import timedelta, timezone
from time import struct_time

import dateutil
import pygogo as gogo

from riko import Objconf
from riko.cast import BasicCastType
from riko.dates import NOW, TODAY, TZINFOS
from riko.types.general import Defaults, Extraction, Opts

from . import processor

# TODO: Make timezone settable and add more options (e.g. 'next week', 'last month',
# etc.)
SWITCH = {
    "today": TODAY,
    "tomorrow": TODAY + timedelta(days=1),
    "yesterday": TODAY + timedelta(days=-1),
    "now": NOW,
}

OPTS: Opts = {"ptype": BasicCastType.NONE, "field": "content"}
DEFAULTS: Defaults = {}
logger = gogo.Gogo(__name__, monolog=True).logger


def parser(
    text: str, extraction: Extraction, objconf: Objconf, **kwargs
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
    today = dt.now(timezone.utc).date()

    if text.endswith((" day", " days")):
        count = int(text.split(" ")[0])
        new_date = today + timedelta(days=count)
    elif text.endswith((" year", " years")):
        count = int(text.split(" ")[0])
        new_date = today.replace(year=today.year + count)
    else:
        new_date = SWITCH.get(text)

    if not new_date:
        new_date = dateutil.parser.parse(text, tzinfos=TZINFOS)

    if not new_date:
        raise ValueError(f"Unrecognized date string: {text}")

    stream = new_date.timetuple()
    return stream


@processor(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args, **kwargs) -> struct_time:
    """
    A processor module that asynchronously converts a text string into a datetime.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        assign (str): Attribute to assign parsed content (default: datebuilder)
        field (str): Item attribute to operate on (default: 'content')

    Returns:
       Deferred: twisted.internet.defer.Deferred item with date timetuples

    Examples:
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> async def run(reactor):
        ...     result = await async_pipe({'content': '12/2/2014'})
        ...     print(next(result)['datebuilder'].tm_year)
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        2014

    """
    return parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs) -> struct_time:
    """
    A processor that converts a text string into a datetime.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        assign (str): Attribute to assign parsed content (default: datebuilder)
        field (str): Item attribute to operate on (default: 'content')

    Yields:
        dict: an item with date timetuples

    Examples:
        >>> next(pipe({'content': '12/2/2014'}))['datebuilder'].tm_year
        2014

    """
    return parser(*args, **kwargs)
