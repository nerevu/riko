# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.pipeyql
~~~~~~~~~~~~~~~~~~~~
Provides functions for fetching the result of a
[YQL](http://developer.yahoo.com/yql) query.

YQL exposes a SQL-like SELECT syntax that is both familiar to developers and
expressive enough for getting the right data. To use YQL, simply enter a YQL
statement, e.g., `select * from feed where url='http://digg.com/rss/index.xml'`.
To drill down further into the result set you can use either the sub-element
module or projection in a YQL statement. For example:
`select title from feed where url='http://digg.com/rss/index.xml'` returns only
the titles from the Digg RSS feed.

The YQL module has 2 viewing modes: Results only or Diagnostics and results.
Diagnostics provides additional data such as: count, language type and more.
A more complex query that finds Flickr photos tagged "fog" in San Francisco:

    select * from flickr.photos.info where photo_id in (
        select id from flickr.photos.search where woe_id in (
            select woeid from geo.places where text="san francisco, ca")
        and tags = "fog")

Examples:
    basic usage::

        >>> from . import FEEDS, FILES
        >>> from riko.modules.pipeyql import pipe
        >>> from urllib2 import urlopen
        >>>
        >>> conf = {'query': "select * from feed where url='%s'" % FEEDS[0]}
        >>> next(pipe(conf=conf, response=urlopen(FILES[7])))['title']
        'Bring pizza home'

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

import requests
import treq

from builtins import *
from lxml.etree import parse
from twisted.web import microdom
from twisted.internet.defer import inlineCallbacks, returnValue

from . import processor
from riko.lib import utils
from riko.lib.log import Logger
from riko.twisted import utils as tu

OPTS = {'ftype': 'none'}

# we use the default format of xml since json loses some structure
DEFAULTS = {'url': 'http://query.yahooapis.com/v1/public/yql', 'debug': False}
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
        assign (str): Attribute to assign parsed content (default: content)
        feed (dict): The original item

    Returns:
        Deferred: twisted.internet.defer.Deferred Tuple of (feed, skip)

    Examples:
        >>> from twisted.internet.task import react
        >>> from . import processor, FEEDS, FILES
        >>> from riko.lib.utils import Objectify
        >>> from urllib2 import urlopen
        >>>
        >>> url = 'http://query.yahooapis.com/v1/public/yql'
        >>> query = "select * from feed where url='%s'" % FEEDS[0]
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x[0])['title'])
        ...     conf = {'query': query, 'url': url, 'debug': False}
        ...     objconf = Objectify(conf)
        ...     kwargs = {'feed': {}, 'response': urlopen(FILES[7])}
        ...     d = asyncParser(None, objconf, False, **kwargs)
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=tu.FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        Bring pizza home
    """
    if skip:
        feed = kwargs['feed']
    else:
        f = kwargs.get('response')

        if f:
            root = yield microdom.parse(f)
        else:
            params = {'q': objconf.query, 'diagnostics': objconf.debug}
            r = yield treq.get(objconf.url, params=params)
            content = yield treq.content(r)
            root = yield microdom.parseString(content)

        results = root.getElementsByTagName('results')[0]
        feed = map(tu.elementToDict, results.childNodes)

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
        assign (str): Attribute to assign parsed content (default: content)
        feed (dict): The original item

    Returns:
        Tuple(Iter[dict], bool): Tuple of (feed, skip)

    Examples:
        >>> from urllib2 import urlopen
        >>> from . import processor, FEEDS, FILES
        >>> from riko.lib.utils import Objectify
        >>>
        >>> url = 'http://query.yahooapis.com/v1/public/yql'
        >>> query = "select * from feed where url='%s'" % FEEDS[0]
        >>> conf = {'query': query, 'url': url, 'debug': False}
        >>> objconf = Objectify(conf)
        >>> kwargs = {'feed': {}, 'response': urlopen(FILES[7])}
        >>> result, skip = parser(None, objconf, False, **kwargs)
        >>> next(result)['title']
        'Bring pizza home'
    """
    if skip:
        feed = kwargs['feed']
    else:
        f = kwargs.get('response')

        if not f:
            params = {'q': objconf.query, 'diagnostics': objconf.debug}
            r = requests.get(objconf.url, params=params, stream=True)
            f = r.raw

        # todo: consider paging for large result sets
        tree = parse(f)
        root = tree.getroot()
        results = root.find('results')
        feed = map(utils.etree_to_dict, results.getchildren())

    return feed, skip


@processor(DEFAULTS, async=True, **OPTS)
def asyncPipe(*args, **kwargs):
    """A source that asynchronously fetches the content of a given website as
    DOM nodes or a string.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'url'. May
            contain the keys 'xpath', 'html5', 'stringify', or 'assign'.

            url (str): The web site to fetch
            xpath (str): The XPATH to extract (default: None, i.e., return
                entire page)

            html5 (bool): Use the HTML5 parser (default: False)
            stringify (bool): Return the web site as a string (default: False)
            assign (str): Attribute to assign parsed content (default: content)

    Returns:
        dict: twisted.internet.defer.Deferred feed of items

    Examples:
        >>> from urllib2 import urlopen
        >>> from . import processor, FEEDS, FILES
        >>> from twisted.internet.task import react
        >>>
        >>> url = 'http://query.yahooapis.com/v1/public/yql'
        >>> query = "select * from feed where url='%s'" % FEEDS[0]
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x)['title'])
        ...     d = asyncPipe(conf={'query': query}, response=urlopen(FILES[7]))
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=tu.FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        Bring pizza home
    """
    return asyncParser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs):
    """A source that fetches the result of a given YQL query.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'query'. May
            contain the keys 'url' or 'debug'.

            url (str): The API to query (default:
                'http://query.yahooapis.com/v1/public/yql')

            query (str): The API query
            debug (bool): Enable diagnostics mode (default: False)

        response (str): The API query response (used for offline testing)

    Yields:
        dict: an item of the result

    Examples:
        >>> from urllib2 import urlopen
        >>> from . import processor, FEEDS, FILES
        >>>
        >>> conf = {'query': "select * from feed where url='%s'" % FEEDS[0]}
        >>> result = next(pipe(conf=conf, response=urlopen(FILES[7])))
        >>> sorted(result.keys())
        ['alarmTime', 'begin', 'duration', 'place', 'title', 'uid']
        >>> result['title']
        'Bring pizza home'
    """
    return parser(*args, **kwargs)
