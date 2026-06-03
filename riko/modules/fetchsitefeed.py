# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.fetchsitefeed
~~~~~~~~~~~~~~~~~~~~~~~~~~
Provides functions for fetching the first RSS or Atom feed discovered in a web
site.

Uses a web site's auto-discovery information to find an RSS or Atom feed. If
multiple feeds are discovered, only the first one is fetched. If a site changes
their feed URL in the future, this module can discover the new URL for you (as
long as the site updates their auto-discovery links). For sites with only one
stream, this module provides a good alternative to the Fetch Feed module.

Also note that not all sites provide auto-discovery links on their web site's
home page.

This module provides a simpler alternative to the Feed Auto-Discovery Module.
The latter returns a list of information about all the feeds discovered in a
site, but (unlike this module) doesn't fetch the feed data itself.

Examples:
    basic usage::

        >>> from riko import get_path
        >>> from riko.modules.fetchsitefeed import pipe
        >>>
        >>> next(pipe(conf={'url': get_path('bbc.html')}))['title']
        "EU sets out 'phased' Brexit strategy"

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""
from typing import Iterator
import pygogo as gogo

from riko.types.general import BasicMapping, Extraction

from . import processor

from riko import autorss, Objconf
from riko.utils import gen_entries
from riko.parsers import parse_rss
from riko.bado import coroutine, return_value, io

OPTS = {"ftype": "none"}
DEFAULTS = {}
logger = gogo.Gogo(__name__, monolog=True).logger


@coroutine  # pyright: ignore[reportArgumentType]
def async_parser(_: BasicMapping, extraction: Extraction, objconf: Objconf, skip=False, **kwargs):
    """Asynchronously parses the pipe content

    Args:
        _ (None): Ignored
        objconf (obj): The pipe configuration (an Objectify instance)
        skip (bool): Don't parse the content
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
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x)['title'])
        ...     objconf = Objectify({'url': get_path('bbc.html')})
        ...     d = async_parser(None, None, objconf, stream={})
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        Using NFC tags in the car
    """
    if skip:
        stream = kwargs["stream"]
    else:
        rss = yield autorss.async_get_rss(objconf.url)  # pyright: ignore[reportCallIssue]
        link = next(rss)["link"]
        content = yield io.async_url_read(link)  # pyright: ignore[reportCallIssue]
        parsed = parse_rss(content)
        stream = gen_entries(parsed["entries"]) if parsed else iter([])

    return_value(stream)


def parser(_: BasicMapping, extraction: Extraction, objconf: Objconf, skip=False, **kwargs) -> Iterator[BasicMapping]:
    """Parses the pipe content

    Args:
        _ (None): Ignored
        objconf (obj): The pipe configuration (an Objectify instance)
        skip (bool): Don't parse the content
        kwargs (dict): Keyword arguments

    Kwargs:
        stream (dict): The original item

    Returns:
        Iter[dict]: The stream of items

    Examples:
        >>> from riko import get_path
        >>> from meza.fntools import Objectify
        >>>
        >>> objconf = Objectify({'url': get_path('bbc.html')})
        >>> result = parser(None, None, objconf, stream={})
        >>> next(result)['title']
        "EU sets out 'phased' Brexit strategy"
    """
    if skip:
        stream = kwargs["stream"]
    else:
        rss = autorss.get_rss(objconf.url)
        link = next(rss)["link"]
        parsed = parse_rss(link)
        stream = gen_entries(parsed["entries"]) if parsed else iter([])

    return stream


@processor(DEFAULTS, isasync=True, **OPTS)  # pyright: ignore[reportArgumentType]
def async_pipe(*args, **kwargs):
    """A source that fetches and parses the first feed found on a site.

    Args:
        item (dict): The entry to process (not used)
        kwargs (dict): The keyword arguments passed to the wrapper.

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'url'.

            url (str): The web site to fetch

    Returns:
        dict: twisted.internet.defer.Deferred an iterator of items

    Examples:
        >>> from riko import get_path
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x)['title'])
        ...     d = async_pipe(conf={'url': get_path('bbc.html')})
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ...     pass
        ... except SystemExit:
        ...     pass
        ...
        Using NFC tags in the car
    """
    return async_parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs):
    """A source that fetches and parses the first feed found on a site.

    Args:
        item (dict): The entry to process (not used)
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'url'.

            url (str): The web site to fetch

    Yields:
        dict: item

    Examples:
        >>> from riko import get_path
        >>> next(pipe(conf={'url': get_path('bbc.html')}))['title']
        "EU sets out 'phased' Brexit strategy"
    """
    return parser(*args, **kwargs)
