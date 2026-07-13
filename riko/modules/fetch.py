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

from riko import Objconf
from riko.bado import coroutine, io, return_value
from riko.parsers import parse_rss
from riko.types.general import BasicArg, BasicMapping, Extraction, ItemArg, Items
from riko.utils import gen_entries

from . import processor

OPTS = {"ftype": "none"}
DEFAULTS = {"delay": 0}
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


@coroutine  # pyright: ignore[reportArgumentType]
def async_parser(
    _: BasicArg, extraction: Extraction, objconf: Objconf, skip=False, **kwargs
):
    """
    Asynchronously parses the pipe content

    Args:
        _ (None): Ignored
        objconf (obj): The pipe configuration (an Objectify instance)
        skip (bool): Don't parse the content
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
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x)['title'])
        ...     objconf = Objectify({'url': get_path('feed.xml'), 'delay': 0})
        ...     d = async_parser(None, None, objconf, stream={})
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        Donations

    """
    if skip:
        stream: Items = kwargs["stream"]
    else:
        content: str = yield io.async_url_read(objconf.url, delay=objconf.delay)  # pyright: ignore[reportCallIssue]
        parsed = parse_rss(content)
        stream = gen_entries(parsed["entries"]) if parsed else iter([])

    return_value(stream)


def parser(
    _: BasicArg, extraction: Extraction, objconf: Objconf, skip=False, **kwargs
) -> ItemArg | Iterator[BasicMapping]:
    """
    Parses the pipe content

    Args:
        _ (None): Ignored
        objconf (obj): The pipe configuration (an Objectify instance)
        skip (bool): Don't parse the content
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
        >>> result = parser(None, None, objconf, stream={})
        >>> next(result)['title']
        'Donations'

    """
    if skip:
        stream = kwargs["stream"]
    else:
        parsed = parse_rss(**{k: objconf[k] for k in objconf})
        stream = gen_entries(parsed["entries"]) if parsed else iter([])

    return stream


@processor(DEFAULTS, isasync=True, **OPTS)  # pyright: ignore[reportArgumentType]
def async_pipe(*args, **kwargs):
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
        >>> def run(reactor):
        ...     callback = lambda x: print(sorted(keys.intersection(next(x))))
        ...     d = async_pipe(conf={'url': get_path('feed.xml')})
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        ['author', 'dc:creator', 'id', 'link', 'pubDate', 'summary', 'title']

    """
    return async_parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs):
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
