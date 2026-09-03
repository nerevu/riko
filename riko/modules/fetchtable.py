# vim: sw=4:ts=4:expandtab
"""
Fetches tabular data and yields rows.

Reads csv/tsv, xls(x), mdb, json, geojson, dbf, yaml, sqlite, fixed width, and
html files. The format is taken from the url's extension.

Examples:
    Basic usage::

        >>> from riko import get_path
        >>> from riko.modules.fetchtable import pipe
        >>>
        >>> url = get_path("spreadsheet.csv")
        >>> next(pipe(conf={"url": url}))["mileage"]
        '7213'

Attributes:
    OPTS: Processor wrapper options.
    DEFAULTS: Default processor configuration.

"""

from logging import Logger
from os.path import splitext
from typing import Any

import pygogo as gogo
from meza.io import read

from riko._constants import ENCODING
from riko._io import Fetch, auto_close, seekable
from riko.bado.io import async_url_open
from riko.cast import SourceOpts
from riko.modules._prepare import require_conf
from riko.types._configs import FetchTableObjconf
from riko.types._options import Defaults, Opts
from riko.types._streams import Item, Stream

from . import processor

OPTS: Opts = SourceOpts
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

logger: Logger = gogo.Gogo(__name__, monolog=True).logger


async def async_parser(
    _: Item, extraction: object, objconf: FetchTableObjconf, **kwargs: object
) -> Stream:
    """
    Asynchronously reads the table into a stream of rows.

    Args:
        _: The item. Unused.
        extraction: The extracted conf value. Unused.
        objconf: The pipe configuration, containing `url` and the table options.

    Returns:
        Rows keyed by column name. The source closes when the stream is exhausted.

    Raises:
        TypeError: If ``conf`` has no ``url`` key.

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
        ...     result = await async_parser(None, None, objconf, stream={})
        ...     print(next(result)["mileage"])
        >>>
        >>> run(main)
        7213

    """
    url: str = require_conf(objconf, "url", "fetchtable")
    r = await async_url_open(
        url, encoding=objconf.encoding, user_agent=objconf.user_agent
    )
    first_row, custom_header = objconf.skip_rows, objconf.col_names
    renamed = {"first_row": first_row, "custom_header": custom_header}
    source = r if objconf.has_header else seekable(r, encoding=objconf.encoding)
    rkwargs = {**objconf, **renamed}
    ext = splitext(url)[1]
    return auto_close(read(source, ext, **rkwargs), source, r)


def parser(
    _: Item, extraction: object, objconf: FetchTableObjconf, **kwargs: object
) -> Stream:
    """
    Reads the table into a stream of rows.

    Args:
        _: The item. Unused.
        extraction: The extracted conf value. Unused.
        objconf: The pipe configuration, containing `url` and the table options.

    Returns:
        Rows keyed by column name. The source closes when the stream is exhausted.

    Raises:
        TypeError: If ``conf`` has no ``url`` key.

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
    url: str = require_conf(objconf, "url", "fetchtable")
    first_row, custom_header = objconf.skip_rows, objconf.col_names
    renamed = {"first_row": first_row, "custom_header": custom_header}
    f = Fetch(url, encoding=objconf.encoding, user_agent=objconf.user_agent)
    source = f if objconf.has_header else seekable(f, encoding=objconf.encoding)
    rkwargs = {**objconf, **renamed}
    ext = splitext(url)[1]
    return auto_close(read(source, ext, **rkwargs), source, f)


@processor(DEFAULTS, isasync=True, **OPTS)
async def async_pipe(*args: Any, **kwargs: object) -> Stream:
    """
    Asynchronously fetches tabular data and yields rows.

    Args:
        item (Item | Items): The entry, or stream of entries. Unused.

        conf (dict): The pipe configuration.

            url (str): The file to fetch, local or remote. Its extension selects
                the reader. Required.

            delimiter (str): Field delimiter (default: ",").
            quotechar (str): Quote character (default: '"').
            encoding (str): File encoding (default: "utf-8").
            user_agent (str): HTTP User-Agent override; unset uses riko's default.

            has_header (bool): Whether the first row names the columns. When
                False the source is buffered so it can be read twice
                (default: True).

            skip_rows (int): Number of rows to drop before the header, zero
                based (default: 0).

            sanitize (bool): Whether to underscorify and lowercase the column
                names (default: True).

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
        - one merged ``{Item, <assign>: [<row>, ...]}`` when ``emit`` is False and
          item is given

    Raises:
        TypeError: If ``conf`` has no ``url`` key.

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
    Fetches tabular data and yields rows.

    Args:
        item (Item | Items): The entry, or stream of entries. Unused.

        conf (dict): The pipe configuration.

            url (str): The file to fetch, local or remote. Its extension selects
                the reader. Required.

            delimiter (str): Field delimiter (default: ",").
            quotechar (str): Quote character (default: '"').
            encoding (str): File encoding (default: "utf-8").
            user_agent (str): HTTP User-Agent override; unset uses riko's default.

            has_header (bool): Whether the first row names the columns. When
                False the source is buffered so it can be read twice
                (default: True).

            skip_rows (int): Number of rows to drop before the header, zero
                based (default: 0).

            sanitize (bool): Whether to underscorify and lowercase the column
                names (default: True).

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
        - one merged ``{Item, <assign>: [<row>, ...]}`` when ``emit`` is False and
          item is given

    Raises:
        TypeError: If ``conf`` has no ``url`` key.

    Examples:
        >>> from riko import get_path
        >>>
        >>> url = get_path("spreadsheet.csv")
        >>> next(pipe(conf={"url": url}))["mileage"]
        '7213'

    """
    return parser(*args, **kwargs)
