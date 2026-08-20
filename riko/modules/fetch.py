# vim: sw=4:ts=4:expandtab
"""
Provides functions for fetching RSS feeds.

Lets you specify an RSS news feed as input. This module understands feeds in
RSS, Atom, and RDF formats. Feeds contain one or more items.

Examples:
    basic usage::

        >>> from riko import get_path
        >>> from riko.modules.fetch import pipe
        >>>
        >>> url = get_path('feed.xml')
        >>> next(pipe(conf={'url': url}))['title']
        'Donations'

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options

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
from riko.types.configs import FetchObjconf
from riko.types.general import Defaults, Extraction, Item, Opts
from riko.types.values import RSSEntry

from . import processor

OPTS: Opts = SourceOpts
DEFAULTS: Defaults = {"encoding": ENCODING}
logger: Logger = gogo.Gogo(__name__, monolog=True).logger
keys: set[str] = {
    "author",
    "dc:creator",
    "id",
    "link",
    "pubDate",
    "summary",
    "title",
}


async def async_parser(
    _: Item, extraction: Extraction, objconf: FetchObjconf, **kwargs: object
) -> Iterator[RSSEntry]:
    """
    Asynchronously parses the pipe content

    Args:
        _ (Item): The item (Ignored)
        extraction: Field values extracted from the item (Ignored)
        objconf (obj): The pipe configuration (an Objectify instance)
        kwargs (dict): Keyword arguments

    Kwargs:
        stream (dict): The original item
        conf (dict): The pipe configuration

    Returns:
        Awaitable: Iter[dict]

    Raises:
        TypeError: If ``conf`` has no ``url`` key.

    Examples:
        >>> from riko import get_path
        >>> from riko import run
        >>> from meza.fntools import Objectify
        >>>
        >>> async def main():
        ...     objconf = Objectify({"url": get_path("feed.xml")})
        ...     result = await async_parser(None, None, objconf)
        ...     print(next(result)['title'])
        >>>
        >>> run(main)
        Donations

    """
    url: str = require_conf(objconf, "url", "fetch")
    content: str = await io.async_url_read(url, encoding=objconf.encoding)
    return augment_entries(parse_rss(content=content))


def parser(
    _: Item, extraction: Extraction, objconf: FetchObjconf, **kwargs: object
) -> Iterator[RSSEntry]:
    """
    Parses the pipe content

    Args:
        _ (Item): The item (Ignored)
        extraction: Field values extracted from the item (Ignored)
        objconf (obj): The pipe configuration (an Objectify instance)
        kwargs (dict): Keyword arguments

    Kwargs:
        stream (dict): The original item
        conf (dict): The pipe configuration

    Returns:
        Iter[dict]: The stream of items

    Raises:
        TypeError: If ``conf`` has no ``url`` key.

    Examples:
        >>> from riko import get_path
        >>> from meza.fntools import Objectify
        >>>
        >>> objconf = Objectify({"url": get_path("feed.xml")})
        >>> result = parser(None, None, objconf)
        >>> next(result)['title']
        'Donations'

    """
    url: str = require_conf(objconf, "url", "fetch")
    entries = parse_rss(url, encoding=objconf.encoding)
    return augment_entries(entries)


@processor(DEFAULTS, isasync=True, **OPTS)
async def async_pipe(*args: Any, **kwargs: object) -> Iterator[RSSEntry]:
    """
    A source that asynchronously fetches and parses a feed to return the
    entries.

    Args:
        item (dict or Iter[dict]): The entry, or stream of entries, to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'url'. May
            contain the key 'delay'.

            url (str): The web site to fetch.


    Returns:
        Awaitable: iterator of items

    Raises:
        TypeError: If ``conf`` has no ``url`` key.

    Examples:
        >>> from riko import get_path
        >>> from riko import run
        >>>
        >>> async def main():
        ...     result = await async_pipe(conf={'url': get_path('feed.xml')})
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
    A source that fetches and parses a feed to return the entries.

    Args:
        item (dict or Iter[dict]): The entry, or stream of entries, to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'url'. May
            contain the key 'delay'.

            url (str): The web site to fetch.

    Returns:
        dict: an iterator of items

    Raises:
        TypeError: If ``conf`` has no ``url`` key.

    Examples:
        >>> from riko import get_path
        >>>
        >>> url = get_path('feed.xml')
        >>> item = next(pipe(conf={'url': url}))
        >>> sorted(keys.intersection(item))
        ['author', 'dc:creator', 'id', 'link', 'pubDate', 'summary', 'title']
        >>>
        >>> item = next(pipe(conf={'url': url, 'memoize': True}))
        >>> sorted(keys.intersection(item))
        ['author', 'dc:creator', 'id', 'link', 'pubDate', 'summary', 'title']

    """
    return parser(*args, **kwargs)
