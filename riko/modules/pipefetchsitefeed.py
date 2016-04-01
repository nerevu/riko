# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.pipefetchsitefeed
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Provides functions for fetching the first RSS or Atom feed discovered in a web
site.

Uses a web site's auto-discovery information to find an RSS or Atom feed. If
multiple feeds are discovered, only the first one is fetched. If a site changes
their feed URL in the future, this module can discover the new URL for you (as
long as the site updates their auto-discovery links). For sites with only one
feed, this module provides a good alternative to the Fetch Feed module.

Also note that not all sites provide auto-discovery links on their web site's
home page.

This module provides a simpler alternative to the Feed Auto-Discovery Module.
The latter returns a list of information about all the feeds discovered in a
site, but (unlike this module) doesn't fetch the feed data itself.

Examples:
    basic usage::

        >>> from . import FILES
        >>> from riko.modules.pipefetchsitefeed import pipe
        >>> next(pipe(conf={'url': FILES[4]}))['title']
        u'Using NFC tags in the car'

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

import speedparser

from builtins import *
from six.moves.urllib.request import urlopen
from twisted.internet.defer import inlineCallbacks, returnValue

from . import processor
from riko.lib import utils, autorss
from riko.lib.log import Logger
from riko.twisted import utils as tu

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
        Tuple(Iter[dict], bool): Tuple of (feed, skip)

    Examples:
        >>> from twisted.internet.task import react
        >>> from . import FILES
        >>> from riko.lib.utils import Objectify
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x[0])['title'])
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
        Using NFC tags in the car
    """
    if skip:
        feed = kwargs['feed']
    else:
        url = utils.get_abspath(objconf.url)
        rss = yield autorss.asyncGetRSS(url)
        link = utils.get_abspath(next(rss)['link'])
        content = yield tu.urlRead(link)
        parsed = speedparser.parse(content)
        feed = utils.gen_entries(parsed)

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
        >>> next(result)['title']
        u'Using NFC tags in the car'
    """
    if skip:
        feed = kwargs['feed']
    else:
        url = utils.get_abspath(objconf.url)
        rss = autorss.get_rss(url)
        link = utils.get_abspath(next(rss)['link'])
        content = urlopen(link).read()
        parsed = speedparser.parse(content)
        feed = utils.gen_entries(parsed)

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
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x)['title'])
        ...     d = asyncPipe(conf={'url': FILES[4]})
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=tu.FakeReactor())
        ...     pass
        ... except SystemExit:
        ...     pass
        ...
        Using NFC tags in the car
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
        >>> next(pipe(conf={'url': FILES[4]}))['title']
        u'Using NFC tags in the car'
    """
    return parser(*args, **kwargs)
