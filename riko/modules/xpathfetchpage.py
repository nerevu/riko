# vim: sw=4:ts=4:expandtab
"""
Fetches a web page and yields the nodes matched by an XPath.

Use ``xpath`` to narrow what you extract; e.g., ``"/a"`` for every link,
``"/img"`` for every image, ``"/rss/channel/item"`` for feed entries. Without
one the whole document is returned as a single nested item. The result can be
converted into an RSS/JSON feed or combined with the regex and string builder
pipes.

The format is taken from the url's extension and defaults to ``html`` for an
extension-less http url. Set ``html5`` to parse with the HTML5 parser instead
of HTML4.

Examples:
    Basic usage::

        >>> from riko import get_path
        >>> from riko.modules.xpathfetchpage import pipe
        >>>
        >>> url = get_path("ouseful.xml")
        >>> conf = {"url": url, "xpath": "/rss/channel/item"}
        >>> next(pipe(conf=conf))["title"][:44]
        'Running “Native” Data Wrangling Applications'

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
from riko.bado.io import async_url_open
from riko.cast import SourceOpts
from riko.modules._prepare import require_conf
from riko.parsers import any2dict
from riko.types._configs import XpathFetchPageObjconf
from riko.types._io import FileLike
from riko.types._options import Defaults
from riko.types._streams import Item, Stream

from . import processor

OPTS = SourceOpts
DEFAULTS = Defaults({"encoding": ENCODING, "html5": False})
logger: Logger = gogo.Gogo(__name__, monolog=True).logger


# TODO: convert relative links to absolute
# TODO: remove the closing tag if using an HTML tag stripped of HTML tags
# TODO: clean html with Tidy


async def async_parser(
    _: Item, extraction: object, objconf: XpathFetchPageObjconf, **kwargs: object
) -> Stream:
    """
    Asynchronously reads the page and returns the nodes at ``xpath``.

    Args:
        _: The item. Unused.
        extraction: The extracted conf value. Unused.
        objconf: The pipe configuration, containing `url`, `xpath` and `html5`.

    Returns:
        One item per matched node, or the whole document when ``xpath`` is unset.

    Raises:
        TypeError: If ``conf`` has no ``url`` key.

    Examples:
        >>> from traceback import format_exc
        >>> from riko import get_path, run
        >>> from meza.fntools import Objectify
        >>>
        >>> async def main():
        ...     xml_url = get_path("ouseful.xml")
        ...     xml_conf = {"url": xml_url, "xpath": "/rss/channel/item"}
        ...     xml_objconf = Objectify(xml_conf)
        ...     xml_args = (None, None, xml_objconf)
        ...     html_url = get_path("sciencedaily.html")
        ...     html_conf = {"url": html_url, "xpath": "/html/head/title"}
        ...     html_objconf = Objectify(html_conf)
        ...     html_args = (None, None, html_objconf)
        ...     kwargs = {"stream": {}}
        ...
        ...     try:
        ...         xml_stream = await async_parser(*xml_args, **kwargs)
        ...         html_stream = await async_parser(*html_args, **kwargs)
        ...         print(next(xml_stream)["title"][:44])
        ...         print(next(html_stream)["content"])
        ...     except Exception as e:
        ...         logger.error(e)
        ...         logger.error(format_exc())
        >>>
        >>> run(main)
        Running “Native” Data Wrangling Applications
        Help Page -- ScienceDaily

    """
    url: str = require_conf(objconf, "url", "xpathfetchpage")
    ext = splitext(url)[1].lstrip(".")

    if url.startswith("http") and not ext:
        ext = "html"

    # TODO: centralize error handling and retry logic
    f = await async_url_open(url, encoding=objconf.encoding)
    content = any2dict(f, ext, objconf.html5, path=objconf.xpath)
    return auto_close(content, f)


def parser(
    _: Item, extraction: object, objconf: XpathFetchPageObjconf, **kwargs: object
) -> Stream:
    """
    Reads the page and returns the nodes at ``xpath``.

    Args:
        _: The item. Unused.
        extraction: The extracted conf value. Unused.
        objconf: The pipe configuration, containing `url`, `xpath` and `html5`.

    Returns:
        One item per matched node, or the whole document when ``xpath`` is unset.

    Raises:
        TypeError: If ``conf`` has no ``url`` key.

    Examples:
        >>> from meza.fntools import Objectify
        >>> from riko import get_path
        >>>
        >>> url = get_path("ouseful.xml")
        >>> objconf = Objectify({"url": url, "xpath": "/rss/channel/item"})
        >>> result = parser(None, None, objconf)
        >>> next(result)["title"][:44]
        'Running “Native” Data Wrangling Applications'
        >>> url = get_path("sciencedaily.html")
        >>> objconf = Objectify({"url": url, "xpath": "/html/head/title"})
        >>> result = parser(None, None, objconf)
        >>> next(result)["content"]
        'Help Page -- ScienceDaily'

    """
    url: str = require_conf(objconf, "url", "xpathfetchpage")
    ext = splitext(url)[1].lstrip(".")

    if url.startswith("http") and not ext:
        ext = "html"

    with Fetch(url, encoding=objconf.encoding) as f:
        content = cast(FileLike, f)
        yield from any2dict(content, ext, objconf.html5, path=objconf.xpath)


@processor(DEFAULTS, isasync=True, **OPTS)
async def async_pipe(*args: Any, **kwargs: object) -> Stream:
    """
    Asynchronously fetches a web page and yields the nodes at an XPath.

    Args:
        item (Item | Items): The entry, or stream of entries. Unused.

        conf (dict): The pipe configuration.

            url (str): The page to fetch, local or remote. Its extension selects
                the parser, defaulting to ``html`` for an extension-less http
                url. Required.

            xpath (str): The XPath to extract, e.g. ``"/rss/channel/item"``. The
                whole document is returned when unset (default: None).

            html5 (bool): Whether to use the HTML5 parser rather than HTML4
                (default: False).

            encoding (str): Page encoding (default: "utf-8").

        context (Context): the execution context

    Kwargs:
        assign (str): Field each node is nested under. Ignored when ``emit`` is
            True (default: "content").

        emit (bool): Whether to emit each node directly rather than assign it.
            Overrides ``assign`` (default: True).

    Yields:
        - ``<node>`` per match when ``emit`` is True (default)
        - ``{<assign>: <node>}`` per match when ``emit`` is False, no item given
        - one merged ``{Item, <assign>: [<node>, ...]}`` when ``emit`` is False and
          item is given

    Raises:
        TypeError: If ``conf`` has no ``url`` key.

    Examples:
        >>> from traceback import format_exc
        >>> from riko import get_path, run
        >>>
        >>> async def main():
        ...     xml_url = get_path("ouseful.xml")
        ...     xml_conf = {"url": xml_url, "xpath": "/rss/channel/item"}
        ...     html_url = get_path("sciencedaily.html")
        ...     html_conf = {"url": html_url, "xpath": "/html/head/title"}
        ...
        ...     try:
        ...         xml_stream = await async_pipe(conf=xml_conf)
        ...         html_stream = await async_pipe(conf=html_conf)
        ...         print(next(xml_stream)["guid"]["content"])
        ...         print(next(html_stream)["content"])
        ...     except Exception as e:
        ...         logger.error(e)
        ...         logger.error(format_exc())
        >>>
        >>> run(main)
        http://blog.ouseful.info/?p=12065
        Help Page -- ScienceDaily

    """
    parsed = await async_parser(*args, **kwargs)
    return parsed


@processor(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> Stream:
    """
    Fetches a web page and yields the nodes at an XPath.

    Args:
        item (Item | Items): The entry, or stream of entries. Unused.

        conf (dict): The pipe configuration.

            url (str): The page to fetch, local or remote. Its extension selects
                the parser, defaulting to ``html`` for an extension-less http
                url. Required.

            xpath (str): The XPath to extract, e.g. ``"/rss/channel/item"``. The
                whole document is returned when unset (default: None).

            html5 (bool): Whether to use the HTML5 parser rather than HTML4
                (default: False).

            encoding (str): Page encoding (default: "utf-8").

        context (Context): the execution context

    Kwargs:
        assign (str): Field each node is nested under. Ignored when ``emit`` is
            True (default: "content").

        emit (bool): Whether to emit each node directly rather than assign it.
            Overrides ``assign`` (default: True).

    Yields:
        - ``<node>`` per match when ``emit`` is True (default)
        - ``{<assign>: <node>}`` per match when ``emit`` is False, no item given
        - one merged ``{Item, <assign>: [<node>, ...]}`` when ``emit`` is False and
          item is given

    Raises:
        TypeError: If ``conf`` has no ``url`` key.

    Examples:
        >>> from riko import get_path
        >>>
        >>> url = get_path("ouseful.xml")
        >>> conf = {"url": url, "xpath": "/rss/channel/item"}
        >>> sorted(next(pipe(conf=conf)))[-3:]
        ['link', 'pubDate', 'title']
        >>> next(pipe(conf=conf)).get("guid")
        {'isPermaLink': 'false', 'content': 'http://blog.ouseful.info/?p=12065'}
        >>> url = get_path("sciencedaily.html")
        >>> conf = {"url": url, "xpath": "/html/head/title"}
        >>> next(pipe(conf=conf))["content"]
        'Help Page -- ScienceDaily'

    """
    return parser(*args, **kwargs)
