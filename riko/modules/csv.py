# vim: sw=4:ts=4:expandtab
"""
Fetches a csv file and yields rows.

The url may be local or remote; rows are read lazily and the source is closed
when the stream is exhausted.

Examples:
    Basic usage::

        >>> from riko import get_path
        >>> from riko.modules.csv import pipe
        >>>
        >>> url = get_path("spreadsheet.csv")
        >>> next(pipe(conf={"url": url}))["mileage"]
        '7213'

Attributes:
    OPTS: Processor wrapper options.
    DEFAULTS: Default processor configuration.

"""

from logging import Logger
from typing import Any, cast

import pygogo as gogo
from meza.io import read_csv

from riko import ENCODING
from riko._io import Fetch, auto_close, seekable
from riko.bado import io
from riko.cast import SourceOpts
from riko.types.configs import CsvObjconf
from riko.types.general import Defaults, Extraction, Item, Opts, Stream

from . import processor

OPTS: Opts = SourceOpts
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

logger: Logger = gogo.Gogo(__name__, monolog=True).logger


async def async_parser(
    _: Item, extraction: Extraction, objconf: CsvObjconf, **kwargs: object
) -> Stream:
    """
    Asynchronously reads the csv file into a stream of rows.

    Args:
        _: The item. Unused.
        extraction: The extracted conf value. Unused.
        objconf: The pipe configuration, containing `url` and the csv options.

    Returns:
        Rows keyed by column name. The source closes when the stream is exhausted.

    Examples:
        >>> from riko import get_path, run
        >>> from meza.fntools import Objectify
        >>>
        >>> async def main():
        ...     url = get_path("spreadsheet.csv")
        ...     conf = {
        ...         "url": url, "sanitize": True, "skip_rows": 0,
        ...         "encoding": ENCODING}
        ...     objconf = Objectify(conf)
        ...     result = await async_parser(None, None, objconf)
        ...     print(next(result)["mileage"])
        >>>
        >>> run(main)
        7213

    """
    r = await io.async_url_open(objconf.url, encoding=objconf.encoding)
    first_row, custom_header = objconf.skip_rows, objconf.col_names
    renamed = {"first_row": first_row, "custom_header": custom_header}
    source = r if objconf.has_header else seekable(r, encoding=objconf.encoding)
    rkwargs = {**objconf, **renamed}
    content = cast(Stream, read_csv(source, **rkwargs))
    return auto_close(content, source)


def parser(
    _: Item, extraction: Extraction, objconf: CsvObjconf, **kwargs: object
) -> Stream:
    """
    Reads the csv file into a stream of rows.

    Args:
        _: The item. Unused.
        extraction: The extracted conf value. Unused.
        objconf: The pipe configuration, containing `url` and the csv options.

    Returns:
        Rows keyed by column name. The source closes when the stream is exhausted.

    Examples:
        >>> from riko import get_path
        >>> from meza.fntools import Objectify
        >>>
        >>> url = get_path("spreadsheet.csv")
        >>> conf = {
        ...     "url": url, "sanitize": True, "skip_rows": 0,
        ...     "encoding": ENCODING}
        >>> objconf = Objectify(conf)
        >>> result = parser(None, None, objconf)
        >>> next(result)["mileage"]
        '7213'

    """
    first_row, custom_header = objconf.skip_rows, objconf.col_names
    renamed = {"first_row": first_row, "custom_header": custom_header}

    f = Fetch(objconf.url, encoding=objconf.encoding)
    source = f if objconf.has_header else seekable(f, encoding=objconf.encoding)
    rkwargs = {**objconf, **renamed}
    content = cast(Stream, read_csv(source, **rkwargs))
    return auto_close(content, source)


@processor(DEFAULTS, isasync=True, **OPTS)
async def async_pipe(*args: Any, **kwargs: object) -> Stream:
    """
    Asynchronously fetches a csv file and yields one item per row.

    Args:
        item (Item | Stream): The entry, or stream of entries. Unused.

        conf (dict): The pipe configuration.

            url (str): The csv file to fetch, local or remote. Required.
            delimiter (str): Field delimiter (default: ",").
            quotechar (str): Quote character (default: '"').
            encoding (str): File encoding (default: "utf-8").

            has_header (bool): Whether the first row names the columns. When
                False the source is buffered so it can be read twice, and
                columns are named ``column_1``, ``column_2``, ... unless
                ``col_names`` is given (default: True).

            skip_rows (int): Number of rows to drop before the header, zero
                based (default: 0).

            sanitize (bool): Whether to underscorify and lowercase the column
                names (default: False).

            dedupe (bool): Whether to deduplicate repeated column names
                (default: True).

            col_names (list): Column names to use in place of the header row
                (default: None).

        context (Context): the execution context

    Kwargs:
        assign (str): Field each row is nested under. Ignored when ``emit`` is
            True (default: "content").

        emit (bool): Whether to emit each row directly rather than assign it.
            Overrides ``assign`` (default: True).

    Yields:
        - ``<row>`` when ``emit`` is True (default)
        - ``{<assign>: <row>}`` when ``emit`` is False and no item given
        - one merged ``{Item, <assign>: [<row>, ...]}`` when ``emit`` is False and item
          is given

    Notes:
        ``has_header=False`` buffers content into memory/disk. Every other option
        streams.

    Examples:
        >>> from riko import get_path, run
        >>>
        >>> async def main():
        ...     result = await async_pipe(conf={"url": get_path("spreadsheet.csv")})
        ...     print(next(result)["mileage"])
        >>>
        >>> run(main)
        7213

    """
    return await async_parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> Stream:
    """
    Fetches a csv file and yields one item per row.

    Args:
        item (Item | Stream): The entry, or stream of entries. Unused.

        conf (dict): The pipe configuration.

            url (str): The csv file to fetch, local or remote. Required.
            delimiter (str): Field delimiter (default: ",").
            quotechar (str): Quote character (default: '"').
            encoding (str): File encoding (default: "utf-8").

            has_header (bool): Whether the first row names the columns. When
                False the source is buffered so it can be read twice, and
                columns are named ``column_1``, ``column_2``, ... unless
                ``col_names`` is given (default: True).

            skip_rows (int): Number of rows to drop before the header, zero
                based (default: 0).

            sanitize (bool): Whether to underscorify and lowercase the column
                names (default: False).

            dedupe (bool): Whether to deduplicate repeated column names
                (default: True).

            col_names (list): Column names to use in place of the header row
                (default: None).

        context (Context): the execution context

    Kwargs:
        assign (str): Field each row is nested under. Ignored when ``emit`` is
            True (default: "content").

        emit (bool): Whether to emit each row directly rather than assign it.
            Overrides ``assign`` (default: True).

    Yields:
        - ``<row>`` when ``emit`` is True (default)
        - ``{<assign>: <row>}`` when ``emit`` is False and no item given
        - one merged ``{Item, <assign>: [<row>, ...]}`` when ``emit`` is False and item
          is given

    Notes:
        ``has_header=False`` buffers content into memory/disk. Every other option
        streams.

    Examples:
        >>> from riko import get_path
        >>>
        >>> url = get_path("spreadsheet.csv")
        >>> next(pipe(conf={"url": url}))["mileage"]
        '7213'

    """
    return parser(*args, **kwargs)
