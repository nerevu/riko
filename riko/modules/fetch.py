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

import pygogo as gogo

from riko import ENCODING
from riko.bado import io
from riko.cast import SourceOpts
from riko.parsers import parse_rss
from riko.types.configs import FetchObjconf
from riko.types.general import Defaults, Extraction, Item
from riko.types.values import RSSEntry
from riko.utils import augment_entries

from . import processor

OPTS = SourceOpts
DEFAULTS: Defaults = {"encoding": ENCODING, "delay": 0}
logger = gogo.Gogo(__name__, monolog=True).logger
keys = {
    "author",
    "dc:creator",
    "id",
    "link",
    "pubDate",
    "summary",
    "title",
}


async def async_parser(
    _: Item, extraction: Extraction, objconf: FetchObjconf, **kwargs
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
        Deferred: twisted.internet.defer.Deferred Iter[dict]

    Examples:
        >>> from riko import get_path
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>> from meza.fntools import Objectify
        >>>
        >>> async def run(reactor):
        ...     objconf = Objectify({'url': get_path('feed.xml'), 'delay': 0})
        ...     result = await async_parser(None, None, objconf)
        ...     print(next(result)['title'])
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        Donations

    """
    if objconf.url:
        content: str = await io.async_url_read(objconf.url, delay=objconf.delay)
        result = augment_entries(parse_rss(content))
    else:
        result = iter([])

    return result


def parser(
    _: Item, extraction: Extraction, objconf: FetchObjconf, **kwargs
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

    Examples:
        >>> from riko import get_path
        >>> from meza.fntools import Objectify
        >>>
        >>> objconf = Objectify({'url': get_path('feed.xml'), 'delay': 0})
        >>> result = parser(None, None, objconf)
        >>> next(result)['title']
        'Donations'

    """
    if objconf.url:
        entries = parse_rss(objconf.url, encoding=objconf.encoding)
        stream = augment_entries(entries)
    else:
        stream = iter([])

    return stream


@processor(DEFAULTS, isasync=True, **OPTS)
async def async_pipe(*args, **kwargs) -> Iterator[RSSEntry]:
    """
    A source that asynchronously fetches and parses a feed to return the
    entries.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'url'. May
            contain the key 'delay'.

            url (str): The web site to fetch.
            delay (flt): Amount of time to sleep (in secs) before fetching the
                url. Useful for simulating network latency. Default: 0.


    Returns:
        Deferred: twisted.internet.defer.Deferred iterator of items

    Examples:
        >>> from riko import get_path
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> async def run(reactor):
        ...     result = await async_pipe(conf={'url': get_path('feed.xml')})
        ...     print(sorted(keys.intersection(next(result))))
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        ['author', 'dc:creator', 'id', 'link', 'pubDate', 'summary', 'title']

    """
    parsed = await async_parser(*args, **kwargs)
    return parsed


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs) -> Iterator[RSSEntry]:
    """
    A source that fetches and parses a feed to return the entries.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'url'. May
            contain the key 'delay'.

            url (str): The web site to fetch.
            delay (flt): Amount of time to sleep (in secs) before fetching the
                url. Useful for simulating network latency. Default: 0.

    Returns:
        dict: an iterator of items

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
