# vim: sw=4:ts=4:expandtab
"""
riko.modules.datebuilder
~~~~~~~~~~~~~~~~~~~~~~~~
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
from datetime import timedelta

import pygogo as gogo

from riko import Objconf
from riko.dates import parse_date
from riko.types.general import Extraction

from . import processor

# TODO: make these timezone aware and add more options (e.g. 'next week', 'last month',
# etc.)
SWITCH = {
    "today": dt.today(),
    "tomorrow": dt.today() + timedelta(days=1),
    "yesterday": dt.today() + timedelta(days=-1),
    "now": dt.now(),
}

OPTS = {"ptype": "none", "field": "content"}
DEFAULTS = {}
logger = gogo.Gogo(__name__, monolog=True).logger


def parser(text: str, extraction: Extraction, objconf: Objconf, skip=False, **kwargs):
    """
    Parsers the pipe content

    Args:
        text (str): The text to convert
        _ (None): Ignored.
        skip (bool): Don't parse the content
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
    if skip:
        stream = kwargs["stream"]
    else:
        if text.endswith(" day") or text.endswith(" days"):
            count = int(text.split(" ")[0])
            new_date = dt.today() + timedelta(days=count)
        elif text.endswith(" year") or text.endswith(" years"):
            count = int(text.split(" ")[0])
            new_date = dt.today().replace(year=dt.today().year + count)
        else:
            new_date = SWITCH.get(text)

        if not new_date:
            new_date = parse_date(text)

        if not new_date:
            raise Exception("Unrecognized date string: %s" % text)

        stream = new_date.timetuple()

    return stream


@processor(DEFAULTS, isasync=True, **OPTS)  # pyright: ignore[reportArgumentType]
def async_pipe(*args, **kwargs):
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
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x)['datebuilder'].tm_year)
        ...     d = async_pipe({'content': '12/2/2014'})
        ...     return d.addCallbacks(callback, logger.error)
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
def pipe(*args, **kwargs):
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
