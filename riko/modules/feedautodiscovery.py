# vim: sw=4:ts=4:expandtab
"""
Discovers RSS/Atom feed links on a page.

Lets you enter a url and then examines that page for information (like link
rel tags) about available feeds. If information about more than one feed is
found, then multiple items are returned. This module discovers the feed links
(href, rel, type, etc.); its output is typically piped into ``fetch`` to
retrieve and parse the feeds themselves.

Also note that not all sites provide auto-discovery links on their web site's
home page. For a simpler alternative, try the Fetch Site Feed Module. It
returns the content from the first discovered feed.

Examples:
    basic usage::

        >>> from riko import get_path
        >>> from riko.modules.feedautodiscovery import pipe
        >>>
        >>> url = get_path('bbc.html')
        >>> entry = next(pipe(conf={'url': url}))
        >>> entry['link']
        'file://riko/data/bbci.co.uk.xml'
        >>> sorted(entry)
        ['href', 'link', 'rel', 'tag', 'title', 'type']
        >>> entry['type']
        'application/rss+xml'
        >>> entry = next(pipe(conf={'url': url, 'strict': False}))
        >>> entry['link']
        'greenhughes.xml'
        >>> sorted(entry)
        ['href', 'hreflang', 'link', 'rel', 'tag']
        >>> next(pipe(conf={'url': url, 'strict': False, 'sort': True}))['link']
        'file://riko/data/bbci.co.uk.xml'

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options

"""

from logging import Logger
from typing import Any

import pygogo as gogo

from riko import autorss
from riko.cast import SourceOpts
from riko.types.configs import FeedAutoDiscoveryObjconf
from riko.types.general import Defaults, Extraction, Item, Opts, Stream

from . import processor

OPTS: Opts = SourceOpts
DEFAULTS: Defaults = {"strict": True}
logger: Logger = gogo.Gogo(__name__, monolog=True).logger


async def async_parser(
    _: Item, extraction: Extraction, objconf: FeedAutoDiscoveryObjconf, **kwargs: object
) -> Stream:
    """
    Asynchronously parses the pipe content

    Args:
        _ (Item): The item (Ignored)
        extraction: Field values extracted from the item (Ignored)
        objconf (obj): The pipe configuration (an Objectify instance)
        kwargs (dict): Keyword arguments

    Kwargs:
        stream (dict): The original item

    Returns:
        Iter[dict]: Deferred stream

    Examples:
        >>> from riko import get_path
        >>> from riko import run
        >>> from meza.fntools import Objectify
        >>>
        >>> async def main():
        ...     objconf = Objectify({'url': get_path('bbc.html'), 'strict': True})
        ...     result = await async_parser(None, None, objconf)
        ...     print(next(result)['link'])
        >>>
        >>> run(main)
        file://riko/data/bbci.co.uk.xml

    """
    rkwargs = {"auto_sort": objconf.sort, "strict": objconf.strict}
    stream = await autorss.async_get_rss(objconf.url, link_type=None, **rkwargs)
    return stream


def parser(
    _: Item, extraction: Extraction, objconf: FeedAutoDiscoveryObjconf, **kwargs: object
) -> Stream:
    """
    Parses the pipe content

    Args:
        _ (Item): The item (Ignored)
        extraction: Field values extracted from the item (Ignored)
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
        >>> url = get_path('bbc.html')
        >>> objconf = Objectify({'url': url, 'strict': True})
        >>> next(parser(None, None, objconf))['link']
        'file://riko/data/bbci.co.uk.xml'
        >>> objconf = Objectify({'url': url, 'strict': False})
        >>> next(parser(None, None, objconf))['link']
        'greenhughes.xml'
        >>> objconf = Objectify({'url': url, 'strict': False, 'sort': True})
        >>> next(parser(None, None, objconf))['link']
        'file://riko/data/bbci.co.uk.xml'

    """
    rkwargs = {"auto_sort": objconf.sort, "strict": objconf.strict}
    stream = autorss.get_rss(objconf.url, link_type=None, **rkwargs)
    return stream


@processor(DEFAULTS, isasync=True, **OPTS)
async def async_pipe(*args: Any, **kwargs: object) -> Stream:
    """
    A source that discovers RSS/Atom feed links on a page.

    Args:
        item (dict): The entry to process (not used)
        kwargs (dict): The keyword arguments passed to the wrapper.

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'url'.

            url (str): The web site to fetch]

    Returns:
        Awaitable: an iterator of items

    Examples:
        >>> from riko import get_path
        >>> from riko import run
        >>>
        >>> async def main():
        ...     result = await async_pipe(conf={'url': get_path('bbc.html')})
        ...     print(next(result)['link'])
        >>>
        >>> run(main)
        file://riko/data/bbci.co.uk.xml

    """
    return await async_parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> Stream:
    """
    A source that discovers RSS/Atom feed links on a page.

    Args:
        item (dict): The entry to process (not used)
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'url'.

            url (str): The web site to fetch
            strict (bool): Only return feeds with a declared types (default: True)
            sort (bool): Sort links according to likelyhood of being an rss feed (default: False)

    Yields:
        dict: item

    Examples:
        >>> from riko import get_path
        >>> conf = {'url': get_path('bbc.html')}
        >>> next(pipe(conf=conf))['link']
        'file://riko/data/bbci.co.uk.xml'

    """
    return parser(*args, **kwargs)
