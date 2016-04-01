# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.pipefeedautodiscovery
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Provides functions for finding the all available RSS and Atom feeds in a web
site.

Lets you enter a url and then examines those pages for information (like link
rel tags) about available feeds. If information about more than one feed is
found, then multiple items are returned. Because more than one feed can be
returned, the output from this module is often piped into a Fetch Feed module.

Also note that not all sites provide auto-discovery links on their web site's
home page. For a simpler alternative, try the Fetch Site Feed Module. It
returns the content from the first discovered feed.

Examples:
    basic usage::

        >>> from . import FILES
        >>> from riko.modules.pipefeedautodiscovery import pipe
        >>>
        >>> entry = next(pipe(conf={'url': FILES[4]}))
        >>> sorted(entry.keys()) == ['href', 'hreflang', 'link', 'rel', 'tag']
        True
        >>> entry['link']
        'file://data/www.greenhughes.com_rssfeed.xml'

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from builtins import *
from twisted.internet.defer import inlineCallbacks, returnValue

from . import processor
from riko.lib import utils, autorss
from riko.lib.log import Logger

OPTS = {'ftype': 'none'}
logger = Logger(__name__).logger


@inlineCallbacks
def asyncParser(_, objconf, skip, **kwargs):
    """ Asynchronously parses the pipe content

    Args:
        _ (None): Ignored
        objconf (obj): The pipe configuration (an Objectify instance)
        skip (bool): Don't parse the content
        kwargs (dict): Keyword arguments

    Kwargs:
        feed (dict): The original item

    Returns:
        Tuple(Iter[dict], bool): Deferred Tuple of (feed, skip)

    Examples:
        >>> from twisted.internet.task import react
        >>> from . import FILES
        >>> from riko.twisted import utils as tu
        >>> from riko.lib.utils import Objectify
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x[0])['link'])
        ...     objconf = Objectify({'url': FILES[4]})
        ...     kwargs = {'feed': {}}
        ...     d = asyncParser(None, objconf, False, **kwargs)
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
        url = utils.get_abspath(objconf.url)
        feed = yield autorss.asyncGetRSS(url)

    result = (feed, skip)
    returnValue(result)


def parser(_, objconf, skip, **kwargs):
    """ Parses the pipe content

    Args:
        _ (None): Ignored
        objconf (obj): The pipe configuration (an Objectify instance)
        skip (bool): Don't parse the content
        kwargs (dict): Keyword arguments

    Kwargs:
        feed (dict): The original item

    Returns:
        Tuple(Iter[dict], bool): Tuple of (feed, skip)

    Examples:
        >>> from . import FILES
        >>> from riko.lib.utils import Objectify
        >>>
        >>> objconf = Objectify({'url': FILES[4]})
        >>> kwargs = {'feed': {}}
        >>> result, skip = parser(None, objconf, False, **kwargs)
        >>> next(result)['link']
        'file://data/www.greenhughes.com_rssfeed.xml'
    """
    if skip:
        feed = kwargs['feed']
    else:
        url = utils.get_abspath(objconf.url)
        feed = autorss.get_rss(url)

    return feed, skip


@processor(async=True, **OPTS)
def asyncPipe(*args, **kwargs):
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
        >>> from twisted.internet.task import react
        >>> from . import FILES
        >>> from riko.twisted import utils as tu
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x)['link'])
        ...     d = asyncPipe(conf={'url': FILES[4]})
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
    """A source that fetches and parses the first feed found on a site.

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
        >>> next(pipe(conf={'url': FILES[4]}))['link']
        'file://data/www.greenhughes.com_rssfeed.xml'
    """
    return parser(*args, **kwargs)
