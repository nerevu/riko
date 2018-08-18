# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.yql
~~~~~~~~~~~~~~~~
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

        >>> from riko import get_path
        >>> from riko.utils import fetch, get_abspath
        >>> from riko.modules.yql import pipe
        >>>
        >>> feed = 'http://feeds.feedburner.com/TechCrunch/'
        >>> conf = {'query': "select * from feed where url='%s'" % feed}
        >>> url = get_abspath(get_path('yql.xml'))
        >>>
        >>> with fetch(url) as f:
        ...     next(pipe(conf=conf, response=f))['title']
        'Bring pizza home'

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

import pygogo as gogo

from builtins import *  # noqa pylint: disable=unused-import

from . import processor
from riko.parsers import xml2etree, etree2dict
from riko.utils import fetch
from riko.bado import coroutine, return_value, util, requests as treq

OPTS = {'ftype': 'none'}

# we use the default format of xml since json looses some structure
DEFAULTS = {'url': 'http://query.yahooapis.com/v1/public/yql', 'debug': False}
logger = gogo.Gogo(__name__, monolog=True).logger


@coroutine
def async_parser(_, objconf, skip=False, **kwargs):
    """ Asynchronously parses the pipe content

    Args:
        _ (None): Ignored
        objconf (obj): The pipe configuration (an Objectify instance)
        skip (bool): Don't parse the content
        kwargs (dict): Keyword arguments

    Kwargs:
        assign (str): Attribute to assign parsed content (default: content)
        stream (dict): The original item

    Returns:
        Deferred: twisted.internet.defer.Deferred stream

    Examples:
        >>> from six.moves.urllib.request import urlopen
        >>> from riko import get_path
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>> from riko.utils import get_abspath
        >>> from meza.fntools import Objectify
        >>>
        >>> feed = 'http://feeds.feedburner.com/TechCrunch/'
        >>> url = 'http://query.yahooapis.com/v1/public/yql'
        >>> query = "select * from feed where url='%s'" % feed
        >>> f = urlopen(get_abspath(get_path('yql.xml')))
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x)['title'])
        ...     conf = {'query': query, 'url': url, 'debug': False}
        ...     objconf = Objectify(conf)
        ...     kwargs = {'stream': {}, 'response': f}
        ...     d = async_parser(None, objconf, **kwargs)
        ...     d.addCallbacks(callback, logger.error)
        ...     d.addCallback(lambda _: f.close())
        ...     return d
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ... finally:
        ...     f.close()
        Bring pizza home
    """
    if skip:
        stream = kwargs['stream']
    else:
        f = kwargs.get('response')

        if not f:
            params = {'q': objconf.query, 'diagnostics': objconf.debug}
            r = yield treq.get(objconf.url, params=params)
            f = yield treq.content(r)

        tree = yield util.xml2etree(f)
        results = next(tree.getElementsByTagName('results'))
        stream = map(util.etree2dict, results.childNodes)

    return_value(stream)


def parser(_, objconf, skip=False, **kwargs):
    """ Parses the pipe content

    Args:
        _ (None): Ignored
        objconf (obj): The pipe configuration (an Objectify instance)
        skip (bool): Don't parse the content
        kwargs (dict): Keyword arguments

    Kwargs:
        assign (str): Attribute to assign parsed content (default: content)
        stream (dict): The original item

    Returns:
        Iter[dict]: The stream of items

    Examples:
        >>> from riko import get_path
        >>> from riko.utils import get_abspath
        >>> from meza.fntools import Objectify
        >>>
        >>> feed = 'http://feeds.feedburner.com/TechCrunch/'
        >>> url = 'http://query.yahooapis.com/v1/public/yql'
        >>> query = "select * from feed where url='%s'" % feed
        >>> conf = {'query': query, 'url': url, 'debug': False}
        >>> objconf = Objectify(conf)
        >>> url = get_abspath(get_path('yql.xml'))
        >>>
        >>> with fetch(url) as f:
        ...     kwargs = {'stream': {}, 'response': f}
        ...     result = parser(None, objconf, **kwargs)
        >>>
        >>> next(result)['title']
        'Bring pizza home'
    """
    if skip:
        stream = kwargs['stream']
    else:
        f = kwargs.get('response')

        if not f:
            params = {'q': objconf.query, 'diagnostics': objconf.debug}

            if objconf.memoize and not objconf.cache_type:
                objconf.cache_type = 'auto'

            f = fetch(params=params, **objconf)

        # TODO: consider paging for large result sets
        root = xml2etree(f).getroot()
        results = root.find('results')
        stream = map(etree2dict, results)

    return stream


@processor(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args, **kwargs):
    """A source that asynchronously fetches the content of a given website as
    DOM nodes or a string.

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

        assign (str): Attribute to assign parsed content (default: content)
        response (str): The API query response (used for offline testing)

    Returns:
        dict: twisted.internet.defer.Deferred stream of items

    Examples:
        >>> from six.moves.urllib.request import urlopen
        >>> from riko import get_path
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>> from riko.utils import get_abspath
        >>>
        >>> feed = 'http://feeds.feedburner.com/TechCrunch/'
        >>> query = "select * from feed where url='%s'" % feed
        >>> f = urlopen(get_abspath(get_path('yql.xml')))
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x)['title'])
        ...     d = async_pipe(conf={'query': query}, response=f)
        ...     d.addCallbacks(callback, logger.error)
        ...     d.addCallback(lambda _: f.close())
        ...     return d
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ... finally:
        ...     f.close()
        Bring pizza home
    """
    return async_parser(*args, **kwargs)


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

        assign (str): Attribute to assign parsed content (default: content)
        response (str): The API query response (used for offline testing)

    Yields:
        dict: an item of the result

    Examples:
        >>> from riko import get_path
        >>> from riko.utils import get_abspath
        >>>
        >>> feed = 'http://feeds.feedburner.com/TechCrunch/'
        >>> conf = {'query': "select * from feed where url='%s'" % feed}
        >>> url = get_abspath(get_path('yql.xml'))
        >>>
        >>> with fetch(url) as f:
        ...     result = next(pipe(conf=conf, response=f))
        ...     sorted(result.keys())
        ['alarmTime', 'begin', 'duration', 'place', 'title', 'uid']
        >>> result['title']
        'Bring pizza home'
    """
    return parser(*args, **kwargs)
