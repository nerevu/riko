# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.pipefetch
~~~~~~~~~~~~~~~~~~~~~~
Provides functions for fetching RSS feeds.

Lets you specify one or more RSS news feeds as input to your Pipe. The module
understands feeds in RSS, Atom, and RDF formats. Feeds contain one or more
items. When you add more feed URLs, you get a single feed combining all the
items from the individual feeds.

Examples:
    basic usage::

        >>> from . import FILES
        >>> from riko.modules.pipefetch import pipe
        >>> pipe(conf={'url': {'value': FILES[0]}}).next()['title']
        u'Donations'

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""

from __future__ import (
    absolute_import, division, print_function, unicode_literals)

import speedparser

from functools import partial
from itertools import imap
from urllib2 import urlopen

from builtins import *
from twisted.internet.defer import inlineCallbacks, returnValue

from . import processor
from riko.lib import utils
from riko.twisted import utils as tu
from riko.lib.log import Logger

OPTS = {'listize': True, 'extract': 'url', 'ftype': 'none'}
DEFAULTS = {'sleep': 0}
logger = Logger(__name__).logger


@inlineCallbacks
def asyncParser(_, urls, skip, **kwargs):
    """ Asynchronously parses the pipe content

    Args:
        _ (None): Ignored
        urls (List[str]): The urls to fetch
        skip (bool): Don't parse the content
        kwargs (dict): Keyword arguments

    Kwargs:
        feed (dict): The original item
        conf (dict): The pipe configuration

    Returns:
        Deferred: twisted.internet.defer.Deferred Tuple(Iter[dict], bool)

    Examples:
        >>> from twisted.internet.task import react
        >>> from . import FILES
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(x[0].next()['title'])
        ...     conf = {'url': FILES}
        ...     kwargs = {'feed': {}, 'conf': conf}
        ...     d = asyncParser(None, conf['url'], False, **kwargs)
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=tu.FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        Donations
    """
    if skip:
        feed = kwargs['feed']
    else:
        sleep = kwargs['conf'].get('sleep', 0)
        read = partial(tu.urlRead, delay=sleep)
        abs_urls = imap(utils.get_abspath, urls)
        contents = yield tu.asyncImap(read, abs_urls)
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
        kwargs (dict): Keyword arguments

    Kwargs:
        feed (dict): The original item
        conf (dict): The pipe configuration

    Returns:
        Tuple(Iter[dict], bool): Tuple of (feed, skip)

    Examples:
        >>> from . import FILES
        >>>
        >>> conf = {'url': FILES}
        >>> kwargs = {'feed': {}, 'conf': conf}
        >>> result, skip = parser(None, conf['url'], False, **kwargs)
        >>> result.next()['title']
        u'Donations'
    """
    if skip:
        feed = kwargs['feed']
    else:
        sleep = kwargs['conf'].get('sleep', 0)
        context = utils.SleepyDict(delay=sleep)
        abs_urls = imap(utils.get_abspath, urls)
        contents = (urlopen(url, context=context).read() for url in abs_urls)
        parsed = imap(speedparser.parse, contents)
        entries = imap(utils.gen_entries, parsed)
        feed = utils.multiplex(entries)

    return feed, skip


@processor(DEFAULTS, async=True, **OPTS)
def asyncPipe(*args, **kwargs):
    """A source that asynchronously fetches and parses one or more feeds to
    return the feed entries.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'url'. May
            contain the key 'sleep'.

            url (str): The web site to fetch. Can be either a dict or list of
                dicts. Must contain one of the following keys: 'value',
                'subkey', or 'terminal'.

                value (str): The url value
                subkey (str): An item attribute from which to obtain the value
                terminal (str): The id of a pipe from which to obtain the value

            sleep (flt): Amount of time to sleep (in secs) before fetching the
                url. Useful for simulating network latency. Default: 0.


    Returns:
        Deferred: twisted.internet.defer.Deferred iterator of items

    Examples:
        >>> from twisted.internet.task import react
        >>> from . import FILES
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(x.next().keys())
        ...     urls = [{'value': FILES[0]}, {'value': FILES[1]}]
        ...     d = asyncPipe(conf={'url': urls})
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=tu.FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        ['updated', 'updated_parsed', u'pubDate', 'author', u'y:published', \
'title', 'comments', 'summary', 'content', 'link', u'y:title', u'dc:creator', \
u'author.uri', u'author.name', 'id', u'y:id']
    """
    return asyncParser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs):
    """A source that fetches and parses one or more feeds to return the
    entries.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'url'. May
            contain the key 'sleep'.

            url (str): The web site to fetch. Can be either a dict or list of
                dicts. Must contain one of the following keys: 'value',
                'subkey', or 'terminal'.

                value (str): The url value
                subkey (str): An item attribute from which to obtain the value
                terminal (str): The id of a pipe from which to obtain the value

            sleep (flt): Amount of time to sleep (in secs) before fetching the
                url. Useful for simulating network latency. Default: 0.

    Returns:
        dict: an iterator of items

    Examples:
        >>> from . import FILES
        >>>
        >>> url = [{'value': FILES[0]}, {'value': FILES[1]}]
        >>> keys = [
        ...     'updated', 'updated_parsed', u'pubDate', 'author',
        ...     u'y:published', 'title', 'comments', 'summary', 'content',
        ...     'link', u'y:title', u'dc:creator', u'author.uri',
        ...     u'author.name', 'id', u'y:id']
        >>> pipe(conf={'url': url}).next().keys() == keys
        True
        >>> result = pipe({'url': FILES[0]}, conf={'url': {'subkey': 'url'}})
        >>> result.next().keys() == keys
        True
    """
    return parser(*args, **kwargs)
