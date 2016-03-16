# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
pipe2py.modules.pipefetchsitefeed
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
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

        >>> from pipe2py.modules.pipefetchsitefeed import pipe
        >>> pipe(conf={'url': {'value': FILES[4]}}).next()['title']
        u'Using NFC tags in the car'

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""

from __future__ import (
    absolute_import, division, print_function, with_statement,
    unicode_literals)

import speedparser

from urllib2 import urlopen
from itertools import imap
from twisted.internet.defer import inlineCallbacks, returnValue
from twisted.web.client import getPage

from . import processor, FEEDS, FILES
from pipe2py.lib import utils, autorss
from pipe2py.lib.log import Logger
from pipe2py.lib.dotdict import DotDict
from pipe2py.twisted import utils as tu

OPTS = {'listize': True, 'extract': 'url', 'ftype': 'none'}
logger = Logger(__name__).logger


@inlineCallbacks
def asyncParser(_, urls, skip, **kwargs):
    """ Asynchronously parses the pipe content

    Args:
        _ (None): Ignored
        urls (List[str]): The urls to parse
        skip (bool): Don't parse the content
        kwargs (dict): Keyword argurments

    Kwargs:
        assign (str): Attribute to assign parsed content (default: content)
        feed (dict): The original item

    Returns:
        Tuple(Iter[dict], bool): Tuple of (feed, skip)

    Examples:
        >>> from twisted.internet.task import react
        >>> from pipe2py.lib.utils import Objectify
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(x[0].next()['title'])
        ...     kwargs = {'feed': {}}
        ...     d = asyncParser(None, [FILES[4]], False, **kwargs)
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
        abs_urls = imap(utils.get_abspath, urls)
        rss = yield tu.asyncImap(autorss.asyncGetRSS, abs_urls)
        links = (utils.get_abspath(entries.next()['link']) for entries in rss)
        contents = yield tu.asyncImap(tu.urlRead, links)
        parsed = imap(speedparser.parse, contents)
        entries = imap(utils.gen_entries, parsed)
        feed = utils.multiplex(entries)

    result = (feed, skip)
    returnValue(result)


def parser(_, urls, skip, **kwargs):
    """ Parses the pipe content

    Args:
        _ (None): Ignored
        urls (List[str]): The urls to fetch
        skip (bool): Don't parse the content
        kwargs (dict): Keyword argurments

    Kwargs:
        assign (str): Attribute to assign parsed content (default: content)
        feed (dict): The original item

    Returns:
        Tuple(Iter[dict], bool): Tuple of (feed, skip)

    Examples:
        >>> kwargs = {'feed': {}}
        >>> result, skip = parser(None, [FILES[4]], False, **kwargs)
        >>> result.next()['title']
        u'Using NFC tags in the car'
    """
    if skip:
        feed = kwargs['feed']
    else:
        abs_urls = imap(utils.get_abspath, urls)
        rss = imap(autorss.get_rss, abs_urls)
        links = (utils.get_abspath(entries.next()['link']) for entries in rss)
        contents = (urlopen(link).read() for link in links)
        parsed = imap(speedparser.parse, contents)
        entries = imap(utils.gen_entries, parsed)
        feed = utils.multiplex(entries)

    return feed, skip


@processor(async=True, **OPTS)
def asyncPipe(*args, **kwargs):
    """A source that fetches and parses the first feed found on one or more
    sites.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        context (obj): pipe2py.Context object
        conf (dict): The pipe configuration. Must contain the key 'url'. May
            contain the key 'assign'.

            url (str): The web site to fetch
            assign (str): Attribute to assign parsed content (default: content)

        field (str): Item attribute from which to obtain the string to be
            tokenized (default: content)

    Returns:
        dict: twisted.internet.defer.Deferred an iterator of items

    Examples:
        >>> from twisted.internet.task import react
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(x.next()['title'])
        ...     d = asyncPipe(conf={'url': {'value': FILES[4]}})
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
    """A source that fetches and parses the first feed found on one or more
    sites.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        context (obj): pipe2py.Context object
        conf (dict): The pipe configuration. Must contain the key 'url'. May
            contain the key 'assign'.

            url (str): The web site to fetch
            assign (str): Attribute to (default: content)

        field (str): Item attribute from which to obtain the string to be
            tokenized (default: content)

    Yields:
        dict: an item of the feed

    Examples:
        >>> pipe(conf={'url': {'value': FILES[4]}}).next()['title']
        u'Using NFC tags in the car'
    """
    return parser(*args, **kwargs)

