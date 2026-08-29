# vim: sw=4:ts=4:expandtab
"""
Fetches an RSS feed and yields feed entries.

Understands RSS, Atom, and RDF. The url may be local or remote.

Examples:
    Basic usage::

        >>> from riko import get_path
        >>> from riko.modules.fetch import pipe
        >>>
        >>> url = get_path("feed.xml")
        >>> next(pipe(conf={"url": url}))["title"]
        'Donations'

Attributes:
    OPTS: Processor wrapper options.
    DEFAULTS: Default processor configuration.
    keys: Entry fields every parsed feed provides.

"""

from collections.abc import Iterator
from logging import Logger
from typing import Any

import pygogo as gogo

from riko import ENCODING
from riko._rssutils import augment_entries
from riko.bado import io
from riko.cast import SourceOpts
from riko.modules._prepare import require_conf
from riko.parsers import parse_rss
from riko.types._configs import FetchObjconf
from riko.types._options import Defaults, Opts
from riko.types._rss import RSSEntry
from riko.types._streams import Item

from . import processor

OPTS: Opts = SourceOpts
DEFAULTS: Defaults = {"encoding": ENCODING}
logger: Logger = gogo.Gogo(__name__, monolog=True).logger
keys: set[str] = {"author", "dc:creator", "id", "link", "pubDate", "summary", "title"}


async def async_parser(
    _: Item, extraction: object, objconf: FetchObjconf, **kwargs: object
) -> Iterator[RSSEntry]:
    """
    Asynchronously fetches the feed and returns its entries.

    ``encoding`` is honored here; ``memoize`` is not.

    Args:
        _: The item. Unused.
        extraction: The extracted conf value. Unused.
        objconf: The pipe configuration, containing `url`.

    Returns:
        Feed entries augmented with the common `keys`.

    Raises:
        TypeError: If ``conf`` has no ``url`` key.

    Examples:
        >>> from riko import get_path, run
        >>> from meza.fntools import Objectify
        >>>
        >>> async def main():
        ...     objconf = Objectify({"url": get_path("feed.xml")})
        ...     result = await async_parser(None, None, objconf)
        ...     print(next(result)["title"])
        >>>
        >>> run(main)
        Donations

    """
    url: str = require_conf(objconf, "url", "fetch")
    content: str = await io.async_url_read(url, encoding=objconf.encoding)
    return augment_entries(parse_rss(content=content))


def parser(
    _: Item, extraction: object, objconf: FetchObjconf, **kwargs: object
) -> Iterator[RSSEntry]:
    """
    Fetches the feed and returns its entries.

    ``encoding`` and ``memoize`` are honored here.

    Args:
        _: The item. Unused.
        extraction: The extracted conf value. Unused.
        objconf: The pipe configuration, containing `url`.

    Returns:
        Feed entries augmented with the common `keys`.

    Raises:
        TypeError: If ``conf`` has no ``url`` key.

    Examples:
        >>> from riko import get_path
        >>> from meza.fntools import Objectify
        >>>
        >>> objconf = Objectify({"url": get_path("feed.xml")})
        >>> result = parser(None, None, objconf)
        >>> next(result)["title"]
        'Donations'

    """
    url: str = require_conf(objconf, "url", "fetch")
    entries = parse_rss(url, encoding=objconf.encoding)
    return augment_entries(entries)


@processor(DEFAULTS, isasync=True, **OPTS)
async def async_pipe(*args: Any, **kwargs: object) -> Iterator[RSSEntry]:
    """
    Asynchronously fetches an RSS feed and yields one feed entries.

    Args:
        item (Item | Items): The entry, or stream of entries. Unused.

        conf (dict): The pipe configuration.

            url (str): The feed to fetch, local or remote. Required.
            encoding (str): Feed encoding (default: "utf-8").

        context (Context): the execution context

    Kwargs:
        assign (str): Field each entry is nested under. Ignored when ``emit`` is
            True (default: "content").

        emit (bool): Whether to emit each entry directly rather than assign it.
            Overrides ``assign`` (default: True).

    Yields:
        - ``<entry>`` when ``emit`` is True (default)
        - ``{<assign>: <entry>}`` when ``emit`` is False and no item given
        - one merged ``{Item, <assign>: [<entry>, ...]}`` when ``emit`` is False and
          item is given

    Raises:
        TypeError: If ``conf`` has no ``url`` key.

    Notes:
        ``memoize`` is ignored on this path.

    Examples:
        >>> from riko import get_path, run
        >>>
        >>> async def main():
        ...     result = await async_pipe(conf={"url": get_path("feed.xml")})
        ...     print(sorted(keys.intersection(next(result))))
        >>>
        >>> run(main)
        ['author', 'dc:creator', 'id', 'link', 'pubDate', 'summary', 'title']

    """
    parsed = await async_parser(*args, **kwargs)
    return parsed


@processor(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> Iterator[RSSEntry]:
    """
    Fetches an RSS feed and yields one feed entries.

    Args:
        item (Item | Items): The entry, or stream of entries. Unused.

        conf (dict): The pipe configuration.

            url (str): The feed to fetch, local or remote. Required.
            encoding (str): Feed encoding (default: "utf-8").
            memoize (bool): Whether to cache the fetched feed (default:
                False).

        context (Context): the execution context

    Kwargs:
        assign (str): Field each entry is nested under. Ignored when ``emit`` is
            True (default: "content").

        emit (bool): Whether to emit each entry directly rather than assign it.
            Overrides ``assign`` (default: True).

    Yields:
        - ``<entry>`` when ``emit`` is True (default)
        - ``{<assign>: <entry>}`` when ``emit`` is False and no item given
        - one merged ``{Item, <assign>: [<entry>, ...]}`` when ``emit`` is False and
          item is given

    Raises:
        TypeError: If ``conf`` has no ``url`` key.

    Examples:
        >>> from riko import get_path
        >>>
        >>> url = get_path("feed.xml")
        >>> item = next(pipe(conf={"url": url}))
        >>> sorted(keys.intersection(item))
        ['author', 'dc:creator', 'id', 'link', 'pubDate', 'summary', 'title']
        >>>
        >>> item = next(pipe(conf={"url": url, "memoize": True}))
        >>> sorted(keys.intersection(item))
        ['author', 'dc:creator', 'id', 'link', 'pubDate', 'summary', 'title']

    """
    return parser(*args, **kwargs)
