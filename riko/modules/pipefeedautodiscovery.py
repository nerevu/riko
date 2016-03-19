# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.pipefeedautodiscovery
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Provides functions for finding the all available RSS and Atom feeds in a web
site.

Lets you enter one or more urls into the module. It then examines those pages
for information (like link rel tags) about available feeds. If information
about more than one feed is found, then multiple items are returned. Because
more than one feed can be returned, the output from this module is often piped
into a Fetch Feed module.

Also note that not all sites provide auto-discovery links on their web site's
home page. For a simpler alternative, try the Fetch Site Feed Module. It
returns the content from the first discovered feed.

Examples:
    basic usage::

        >>> from . import FILES
        >>> from riko.modules.pipefeedautodiscovery import pipe
        >>>
        >>> entry = pipe(conf={'url': {'value': FILES[4]}}).next()
        >>> sorted(entry.keys())
        ['href', 'hreflang', 'link', 'rel', 'tag']
        >>> entry['link']
        'file://data/www.greenhughes.com_rssfeed.xml'

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""

from __future__ import (
    absolute_import, division, print_function, with_statement,
    unicode_literals)

from itertools import imap
from twisted.internet.defer import inlineCallbacks, returnValue

from . import processor
from riko.lib import utils, autorss
from riko.lib.log import Logger
from riko.twisted import utils as tu

OPTS = {'listize': True, 'extract': 'url', 'ftype': 'none'}
logger = Logger(__name__).logger


@inlineCallbacks
def asyncParser(_, urls, skip, **kwargs):
    """ Asynchronously parses the pipe content

    Args:
        _ (None): Ignored
        urls (List[str]): The urls to parse
        skip (bool): Don't parse the content
        kwargs (dict): Keyword arguments

    Kwargs:
        feed (dict): The original item

    Returns:
        Tuple(Iter[dict], bool): Deferred Tuple of (feed, skip)

    Examples:
        >>> from twisted.internet.task import react
        >>> from . import FILES
        >>> from riko.lib.utils import Objectify
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(x[0].next()['link'])
        ...     kwargs = {'feed': {}}
        ...     d = asyncParser(None, [FILES[4]], False, **kwargs)
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=tu.FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        file://data/www.greenhughes.com_rssfeed.xml
    """
    if skip:
        feed = kwargs['feed']
    else:
        abs_urls = imap(utils.get_abspath, urls)
        rss = yield tu.asyncImap(autorss.asyncGetRSS, abs_urls)
        feed = utils.multiplex(rss)

    result = (feed, skip)
    returnValue(result)


def parser(_, urls, skip, **kwargs):
    """ Parses the pipe content

    Args:
        _ (None): Ignored
        urls (List[str]): The urls to fetch
        skip (bool): Don't parse the content
        kwargs (dict): Keyword arguments

    Kwargs:
        feed (dict): The original item

    Returns:
        Tuple(Iter[dict], bool): Tuple of (feed, skip)

    Examples:
        >>> from . import FILES
        >>>
        >>> kwargs = {'feed': {}}
        >>> result, skip = parser(None, [FILES[4]], False, **kwargs)
        >>> result.next()['link']
        'file://data/www.greenhughes.com_rssfeed.xml'
    """
    if skip:
        feed = kwargs['feed']
    else:
        abs_urls = imap(utils.get_abspath, urls)
        rss = imap(autorss.get_rss, abs_urls)
        feed = utils.multiplex(rss)

    return feed, skip


@processor(async=True, **OPTS)
def asyncPipe(*args, **kwargs):
    """A source that fetches and parses the first feed found on one or more
    sites.

    Args:
        item (dict): The entry to process (not used)
        kwargs (dict): The keyword arguments passed to the wrapper.

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'url'.

            url (str): The web site to fetch

    Returns:
        dict: twisted.internet.defer.Deferred an iterator of items

    Examples:
        >>> from twisted.internet.task import react
        >>> from . import FILES
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(x.next()['link'])
        ...     d = asyncPipe(conf={'url': {'value': FILES[4]}})
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=tu.FakeReactor())
        ...     pass
        ... except SystemExit:
        ...     pass
        ...
        file://data/www.greenhughes.com_rssfeed.xml
    """
    return asyncParser(*args, **kwargs)


@processor(**OPTS)
def pipe(*args, **kwargs):
    """A source that fetches and parses the first feed found on one or more
    sites.

    Args:
        item (dict): The entry to process (not used)
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'url'.

            url (str): The web site to fetch

    Yields:
        dict: an item of the feed

    Examples:
        >>> from . import FILES
        >>> pipe(conf={'url': {'value': FILES[4]}}).next()['link']
        'file://data/www.greenhughes.com_rssfeed.xml'
    """
    return parser(*args, **kwargs)
