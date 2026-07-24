# vim: sw=4:ts=4:expandtab
"""
Provides functions for fetching tabular data from csv/tsv, xls(x), mdb, json, geojson,
dbf, yaml, sqlite, fixed width, and html files.


Examples:
    basic usage::

        >>> from riko import get_path
        >>> from riko.modules.fetchtable import pipe
        >>>
        >>> url = get_path('spreadsheet.csv')
        >>> next(pipe(conf={'url': url}))['mileage']
        '7213'

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options

"""

from os import path as p

import pygogo as gogo
from meza.io import read

from riko import ENCODING
from riko.bado import io
from riko.cast import SourceOpts
from riko.types.configs import FetchTableObjconf
from riko.types.general import Defaults, Extraction, Item, Stream
from riko.utils import Fetch, auto_close

from . import processor

OPTS = SourceOpts
DEFAULTS: Defaults = {
    "delimiter": ",",
    "quotechar": '"',
    "encoding": ENCODING,
    "skip_rows": 0,
    "sanitize": True,
    "dedupe": True,
    "col_names": None,
    "has_header": True,
}

logger = gogo.Gogo(__name__, monolog=True).logger


async def async_parser(
    _: Item, extraction: Extraction, objconf: FetchTableObjconf, **kwargs
) -> Stream:
    """
    Asynchronously parses the pipe content

    Args:
        _ (Item): The item (Ignored)
        extraction: Field values extracted from the item (Ignored)
        objconf (obj): The pipe configuration (an Objectify instance)
        kwargs (dict): Keyword arguments

    Kwargs:
        stream (dict): The original item

    Returns:
        Iter[dict]: The stream of items

    Examples:
        >>> from riko import get_path
        >>> from riko.bado import run
        >>> from meza.fntools import Objectify
        >>>
        >>> async def main():
        ...     url = get_path('spreadsheet.csv')
        ...     conf = {
        ...         'url': url, 'sanitize': True, 'skip_rows': 0,
        ...         'encoding': ENCODING}
        ...     objconf = Objectify(conf)
        ...     result = await async_parser(None, None, objconf, stream={})
        ...     print(next(result)['mileage'])
        >>>
        >>> run(main)
        7213

    """
    r = await io.async_url_open(objconf.url, encoding=objconf.encoding)
    first_row, custom_header = objconf.skip_rows, objconf.col_names
    renamed = {"first_row": first_row, "custom_header": custom_header}
    rkwargs = {**objconf, **renamed}
    ext = p.splitext(objconf.url)[1]
    stream = auto_close(read(r, ext, **rkwargs), r)
    return stream


def parser(
    _: Item, extraction: Extraction, objconf: FetchTableObjconf, **kwargs
) -> Stream:
    """
    Parses the pipe content

    Args:
        _ (Item): The item (Ignored)
        extraction: Field values extracted from the item (Ignored)
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
    rkwargs = {**objconf, **renamed}
    ext = p.splitext(objconf.url)[1]
    stream = auto_close(read(f, ext, **rkwargs), f)
    return stream


@processor(DEFAULTS, isasync=True, **OPTS)
async def async_pipe(*args, **kwargs) -> Stream:
    """
    A source that asynchronously fetches a file.

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
        Awaitable: item

    Examples:
        >>> from riko import get_path
        >>> from riko.bado import run
        >>>
        >>> async def main():
        ...     result = await async_pipe(conf={'url': get_path('spreadsheet.csv')})
        ...     print(next(result)['mileage'])
        >>>
        >>> run(main)
        7213

    """
    return await async_parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs) -> Stream:
    """
    A source that fetches and parses a file to yield items.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'url'. May
            contain the keys 'delimiter', 'quotechar', 'encoding', 'skip_rows',
            'sanitize', 'dedupe', 'col_names', or 'has_header'.

            url (str): The file to fetch
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
