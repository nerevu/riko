# vim: sw=4:ts=4:expandtab
"""
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

from collections.abc import Iterator

import pygogo as gogo

from riko import Objconf, autorss
from riko.bado import io
from riko.cast import BasicCastType
from riko.parsers import parse_rss
from riko.types.general import Defaults, Extraction, ItemArg, Opts
from riko.types.values import RSSEntry
from riko.utils import gen_entries

from . import processor

OPTS: Opts = {"ftype": BasicCastType.NONE}
DEFAULTS: Defaults = {}
logger = gogo.Gogo(__name__, monolog=True).logger


async def async_parser(
    _: ItemArg, extraction: Extraction, objconf: Objconf, **kwargs
) -> Iterator[RSSEntry]:
    """
    Asynchronously parses the pipe content

    Args:
        _ (None): Ignored
        objconf (obj): The pipe configuration (an Objectify instance)
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
        >>> async def run(reactor):
        ...     objconf = Objectify({'url': get_path('bbc.html')})
        ...     result = await async_parser(None, None, objconf)
        ...     print(next(result)['title'])
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        EU sets out 'phased' Brexit strategy

    """
    rss = await autorss.async_get_rss(objconf.url)
    link = str(next(rss)["link"])
    content = await io.async_url_read(link)
    parsed = parse_rss(content)
    stream = gen_entries(parsed["entries"])
    return stream


def parser(
    _: ItemArg, extraction: Extraction, objconf: Objconf, **kwargs
) -> Iterator[RSSEntry]:
    """
    Parses the pipe content

    Args:
        _ (None): Ignored
        objconf (obj): The pipe configuration (an Objectify instance)
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
        >>> result = parser(None, None, objconf)
        >>> next(result)['title']
        "EU sets out 'phased' Brexit strategy"

    """
    rss = autorss.get_rss(objconf.url)
    link = str(next(rss)["link"])
    parsed = parse_rss(link)
    stream = gen_entries(parsed["entries"])
    return stream


@processor(DEFAULTS, isasync=True, **OPTS)
async def async_pipe(*args, **kwargs) -> Iterator[RSSEntry]:
    """
    A source that fetches and parses the first feed found on a site.

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
        >>> async def run(reactor):
        ...     result = await async_pipe(conf={'url': get_path('bbc.html')})
        ...     print(next(result)['title'])
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        EU sets out 'phased' Brexit strategy

    """
    return await async_parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs) -> Iterator[RSSEntry]:
    """
    A source that fetches and parses the first feed found on a site.

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
