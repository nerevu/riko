# vim: sw=4:ts=4:expandtab
"""
Provides functions for fetching csv files.

Examples:
    basic usage::

        >>> from riko import get_path
        >>> from riko.modules.csv import pipe
        >>>
        >>> url = get_path('spreadsheet.csv')
        >>> next(pipe(conf={'url': url}))['mileage']
        '7213'

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options

"""

from collections.abc import Iterator
from typing import cast

import pygogo as gogo
from meza.io import read_csv

from riko import ENCODING, Objconf
from riko.bado import io
from riko.cast import BasicCastType
from riko.types.general import Defaults, Extraction, Item, Opts
from riko.types.values import IntermediateMapping
from riko.utils import Fetch, auto_close

from . import processor

OPTS: Opts = {"ftype": BasicCastType.NONE}
DEFAULTS: Defaults = {
    "delimiter": ",",
    "quotechar": '"',
    "encoding": ENCODING,
    "skip_rows": 0,
    "sanitize": False,
    "dedupe": True,
    "col_names": None,
    "has_header": True,
}

logger = gogo.Gogo(__name__, monolog=True).logger


async def async_parser(
    _: Item, extraction: Extraction, objconf: Objconf, **kwargs
) -> Iterator[IntermediateMapping]:
    """
    Asynchronously parses the pipe content

    Args:
        _ (None): Ignored
        objconf (obj): The pipe configuration (an Objectify instance)
        kwargs (dict): Keyword arguments

    Kwargs:
        stream (dict): The original item

    Returns:
        Iter[dict]: The stream of items

    Examples:
        >>> from riko import get_path
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>> from meza.fntools import Objectify
        >>>
        >>> async def run(reactor):
        ...     url = get_path('spreadsheet.csv')
        ...     conf = {
        ...         'url': url, 'sanitize': True, 'skip_rows': 0,
        ...         'encoding': ENCODING}
        ...     objconf = Objectify(conf)
        ...     result = await async_parser(None, None, objconf)
        ...     print(next(result)['mileage'])
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        7213

    """
    r = await io.async_url_open(objconf.url, encoding=objconf.encoding)
    first_row, custom_header = objconf.skip_rows, objconf.col_names
    renamed = {"first_row": first_row, "custom_header": custom_header}
    rkwargs = {**dict(objconf.iteritems()), **renamed}
    content = cast(Iterator[IntermediateMapping], read_csv(r, **rkwargs))
    stream = auto_close(content, r)
    return stream


def parser(
    _: Item, extraction: Extraction, objconf: Objconf, **kwargs
) -> Iterator[IntermediateMapping]:
    """
    Parses the pipe content

    Args:
        _ (None): Ignored
        objconf (obj): The pipe configuration (an Objectify instance)

    Returns:
        Iter[dict]: The stream of items

    Examples:
        >>> from riko import get_path
        >>> from meza.fntools import Objectify
        >>>
        >>> url = get_path('spreadsheet.csv')
        >>> conf = {
        ...     'url': url, 'sanitize': True, 'skip_rows': 0,
        ...     'encoding': ENCODING}
        >>> objconf = Objectify(conf)
        >>> result = parser(None, None, objconf)
        >>> next(result)['mileage']
        '7213'

    """
    first_row, custom_header = objconf.skip_rows, objconf.col_names
    renamed = {"first_row": first_row, "custom_header": custom_header}

    f = Fetch(objconf.url, encoding=objconf.encoding)
    rkwargs = {**dict(objconf.iteritems()), **renamed}
    content = cast(Iterator[IntermediateMapping], read_csv(f, **rkwargs))
    stream = auto_close(content, f)
    return stream


@processor(DEFAULTS, isasync=True, **OPTS)
async def async_pipe(*args, **kwargs) -> Iterator[IntermediateMapping]:
    """
    A source that asynchronously fetches the content of a given web site as
    a string.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'url'. May
            contain the keys 'delimiter', 'quotechar', 'encoding', 'skip_rows',
            'sanitize', 'dedupe', 'col_names', or 'has_header'.

            url (str): The csv file to fetch
            delimiter (str): Field delimiter (default: ',').
            quotechar (str): Quote character (default: '"').
            encoding (str): File encoding (default: 'utf-8').
            has_header (bool): Has header row (default: True).
            skip_rows (int): Number of initial rows to skip (zero based,
                default: 0).

            sanitize (bool): Underscorify and lowercase field names
                (default: False).

            dedupe (bool): Deduplicate column names (default: False).
            col_names (List[str]): Custom column names (default: None).

    Returns:
        dict: twisted.internet.defer.Deferred item

    Examples:
        >>> from riko import get_path
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> async def run(reactor):
        ...     result = await async_pipe(conf={'url': get_path('spreadsheet.csv')})
        ...     print(next(result)['mileage'])
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        7213

    """
    return await async_parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs) -> Iterator[IntermediateMapping]:
    """
    A source that fetches and parses a csv file to yield items.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'url'. May
            contain the keys 'delimiter', 'quotechar', 'encoding', 'skip_rows',
            'sanitize', 'dedupe', 'col_names', or 'has_header'.

            url (str): The csv file to fetch
            delimiter (str): Field delimiter (default: ',').
            quotechar (str): Quote character (default: '"').
            encoding (str): File encoding (default: 'utf-8').
            has_header (bool): Has header row (default: True).
            skip_rows (int): Number of initial rows to skip (zero based,
                default: 0).

            sanitize (bool): Underscorify and lowercase field names
                (default: False).

            dedupe (bool): Deduplicate column names (default: False).
            col_names (List[str]): Custom column names (default: None).

    Yields:
        dict: item

    Examples:
        >>> from riko import get_path
        >>> url = get_path('spreadsheet.csv')
        >>> next(pipe(conf={'url': url}))['mileage']
        '7213'

    """
    return parser(*args, **kwargs)
