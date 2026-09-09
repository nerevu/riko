# vim: sw=4:ts=4:expandtab
"""
Fetches an XML or JSON data source and yields records.

Accesses and extracts data from XML and JSON sources on the web, which can then
be converted into an RSS feed or merged with other data in your pipe.

Examples:
    Basic usage::

        >>> from riko import get_path
        >>> from riko.modules.fetchdata import pipe
        >>>
        >>> conf = {"url": get_path("gigs.json"), "path": "value.items"}
        >>> next(pipe(conf=conf))["title"]
        'Business System Analyst'

Attributes:
    OPTS: Processor wrapper options.
    DEFAULTS: Default processor configuration.

"""

from logging import Logger
from os.path import splitext
from typing import Any, cast

import pygogo as gogo

from riko._constants import ENCODING
from riko._io import Fetch, auto_close
from riko._iterutils import listize
from riko.bado.io import async_url_open
from riko.cast import SourceOpts
from riko.modules._prepare import require_conf
from riko.parsers import any2dict
from riko.types._configs import FetchDataObjconf
from riko.types._io import FileLike
from riko.types._options import Defaults, Opts
from riko.types._streams import Item, Stream

from . import processor

OPTS: Opts = SourceOpts
DEFAULTS: Defaults = Defaults({"encoding": ENCODING})
logger: Logger = gogo.Gogo(__name__, monolog=True).logger


async def async_parser(
    _: Item, extraction: object, objconf: FetchDataObjconf, **kwargs: object
) -> Stream:
    """
    Asynchronously reads the data source into a stream of records.

    The format is taken from the url's extension, falling back to the fetched
    file's detected type when the url has none.

    Args:
        _: The item. Unused.
        extraction: The extracted conf value. Unused.
        objconf: The pipe configuration, containing `url`, `path` and `html5`.

    Returns:
        Records at ``path``, or the whole document when ``path`` is empty.

    Raises:
        TypeError: If ``conf`` has no ``url`` key.

    Examples:
        >>> from riko import get_path, run
        >>> from meza.fntools import Objectify
        >>>
        >>> async def main():
        ...     url = get_path("gigs.json")
        ...     objconf = Objectify({"url": url, "path": "value.items"})
        ...     result = await async_parser(None, None, objconf)
        ...     print(next(result)["title"])
        >>>
        >>> run(main)
        Business System Analyst

    """
    url: str = require_conf(objconf, "url", "fetchdata")
    ext = splitext(url)[1].lstrip(".")
    path = objconf.path if isinstance(objconf.path, str) else ".".join(objconf.path)
    # TODO: Figure out if html/xml files should be parsed as binary too.
    binary = ext == "json"
    f = await async_url_open(url, encoding=objconf.encoding, binary=binary)
    ext = ext or getattr(f, "ext", None) or ""
    content = any2dict(f, ext, objconf.html5, path=path)
    return auto_close(content, f)


def parser(
    _: Item, extraction: object, objconf: FetchDataObjconf, **kwargs: object
) -> Stream:
    """
    Reads the data source into a stream of records.

    The format is taken from the url's extension, falling back to the fetched
    file's detected type when the url has none.

    Args:
        _: The item. Unused.
        extraction: The extracted conf value. Unused.
        objconf: The pipe configuration, containing `url`, `path` and `html5`.

    Returns:
        Records at ``path``, or the whole document when ``path`` is empty.

    Raises:
        TypeError: If ``conf`` has no ``url`` key.

    Examples:
        >>> from riko import get_path
        >>> from meza.fntools import Objectify
        >>>
        >>> url = get_path("gigs.json")
        >>> objconf = Objectify({"url": url, "path": "value.items"})
        >>> result = parser(None, None, objconf)
        >>> next(result)["title"]
        'Business System Analyst'

    """
    url: str = require_conf(objconf, "url", "fetchdata")
    ext = splitext(url)[1].lstrip(".")
    paths = cast(list[str], listize(objconf.path))
    path = ".".join(paths)

    with Fetch(url, encoding=objconf.encoding, binary=(ext == "json")) as f:
        ext = ext or f.ext
        content = cast(FileLike, f)
        yield from any2dict(content, ext, objconf.html5, path=path)


@processor(DEFAULTS, isasync=True, **OPTS)
async def async_pipe(*args: Any, **kwargs: object) -> Stream:
    """
    Asynchronously fetches an XML or JSON source and yields its records.

    Args:
        item (Item | Items): The entry, or stream of entries. Unused.

        conf (dict): The pipe configuration.

            url (str): The file to fetch, local or remote. Its extension selects
                the parser. Required.

            path (str | list[str]): Dot separated path to the records, e.g.
                ``"value.items"``. The whole document is returned when empty
                (default: None).

            html5 (bool): Whether to use the HTML5 parser (default: False).

            encoding (str): File encoding (default: "utf-8").

        context (Context): the execution context

    Kwargs:
        assign (str): Field each record is nested under. Ignored when ``emit`` is
            True (default: "content").

        emit (bool): Whether to emit each record directly rather than assign it.
            Overrides ``assign`` (default: True).

    Yields:
        - ``<record>`` when ``emit`` is True (default)
        - ``{<assign>: <record>}`` when ``emit`` is False and no item given
        - one merged ``{Item, <assign>: [<record>, ...]}`` when ``emit`` is False
          and item is given

    Raises:
        TypeError: If ``conf`` has no ``url`` key.

    Examples:
        >>> from riko import get_path, run
        >>>
        >>> async def main():
        ...     path = "value.items"
        ...     conf = {"url": get_path("gigs.json"), "path": path}
        ...     result = await async_pipe(conf=conf)
        ...     print(next(result)["title"])
        >>>
        >>> run(main)
        Business System Analyst

    """
    return await async_parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> Stream:
    """
    Fetches an XML or JSON source and yields its records.

    Args:
        item (Item | Items): The entry, or stream of entries. Unused.

        conf (dict): The pipe configuration.

            url (str): The file to fetch, local or remote. Its extension selects
                the parser. Required.

            path (str | list[str]): Dot separated path to the records, e.g.
                ``"value.items"``. The whole document is returned when empty
                (default: None).

            html5 (bool): Whether to use the HTML5 parser (default: False).

            encoding (str): File encoding (default: "utf-8").

        context (Context): the execution context

    Kwargs:
        assign (str): Field each record is nested under. Ignored when ``emit`` is
            True (default: "content").

        emit (bool): Whether to emit each record directly rather than assign it.
            Overrides ``assign`` (default: True).

    Yields:
        - ``<record>`` when ``emit`` is True (default)
        - ``{<assign>: <record>}`` when ``emit`` is False and no item given
        - one merged ``{Item, <assign>: [<record>, ...]}`` when ``emit`` is False
          and item is given

    Raises:
        TypeError: If ``conf`` has no ``url`` key.

    Examples:
        >>> from riko import get_path
        >>>
        >>> conf = {"url": get_path("gigs.json"), "path": "value.items"}
        >>> next(pipe(conf=conf))["title"]
        'Business System Analyst'
        >>> path = "appointment"
        >>> conf = {"url": get_path("places.xml"), "path": path}
        >>> next(pipe(conf=conf))["subject"]
        'Bring pizza home'
        >>> conf = {"url": get_path("places.xml"), "path": ""}
        >>> next(pipe(conf=conf))["reminder"]
        '15'
        >>> conf = {"url": get_path("schools.xml"), "path": "data.row"}
        >>> next(pipe(conf=conf))["district_name"]
        'Turkana'

    """
    return parser(*args, **kwargs)
