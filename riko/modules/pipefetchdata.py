# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.pipefetchdata
~~~~~~~~~~~~~~~~~~~~~~~~~~
Provides functions for fetching XML and JSON data sources.

Accesses and extracts data from XML and JSON data sources on the web. This data
can then be converted into an RSS feed or merged with other data in your Pipe.

Examples:
    basic usage::

        >>> from riko import get_path
        >>> from riko.modules.pipefetchdata import pipe
        >>>
        >>> conf = {'url': get_path('gigs.json'), 'path': 'value.items'}
        >>> next(pipe(conf=conf))['title']
        u'Business System Analyst'

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from functools import reduce
from os.path import splitext

from builtins import *
from six.moves.urllib.request import urlopen
from twisted.internet.defer import inlineCallbacks, returnValue

from . import processor
from riko.lib import utils
from riko.lib.log import Logger
from riko.twisted import utils as tu

OPTS = {'ftype': 'none'}
reducer = lambda element, i: element.get(i) if element else None
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
        stream (dict): The original item

    Returns:
        Tuple(Iter[dict], bool): Tuple of (stream, skip)

    Examples:
        >>> from twisted.internet.task import react
        >>> from riko import get_path
        >>> from riko.lib.utils import Objectify
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(x[0][0]['title'])
        ...     url = get_path('gigs.json')
        ...     objconf = Objectify({'url': url, 'path': 'value.items'})
        ...     kwargs = {'stream': {}}
        ...     d = asyncParser(None, objconf, False, **kwargs)
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=tu.FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        Business System Analyst
    """
    if skip:
        stream = kwargs['stream']
    else:
        url = utils.get_abspath(objconf.url)
        ext = splitext(url)[1].lstrip('.')
        path = objconf.path.split('.') if objconf.path else []
        f = yield tu.urlOpen(url)
        element = utils.any2dict(f, ext, objconf.html5)
        stream = yield tu.coopReduce(reducer, path, element)

    result = (stream, skip)
    returnValue(result)


def parser(_, objconf, skip, **kwargs):
    """ Parses the pipe content

    Args:
        _ (None): Ignored
        objconf (obj): The pipe configuration (an Objectify instance)
        skip (bool): Don't parse the content
        kwargs (dict): Keyword arguments

    Kwargs:
        stream (dict): The original item

    Returns:
        Tuple(Iter[dict], bool): Tuple of (stream, skip)

    Examples:
        >>> from riko import get_path
        >>> from riko.lib.utils import Objectify
        >>>
        >>> url = get_path('gigs.json')
        >>> objconf = Objectify({'url': url, 'path': 'value.items'})
        >>> kwargs = {'stream': {}}
        >>> result, skip = parser(None, objconf, False, **kwargs)
        >>> result[0]['title']
        u'Business System Analyst'
    """
    if skip:
        stream = kwargs['stream']
    else:
        url = utils.get_abspath(objconf.url)
        ext = splitext(url)[1].lstrip('.')
        path = objconf.path.split('.') if objconf.path else []
        f = urlopen(url)
        element = utils.any2dict(f, ext, objconf.html5)
        stream = reduce(reducer, path, element)

    return stream, skip


@processor(async=True, **OPTS)
def asyncPipe(*args, **kwargs):
    """A source that asynchronously fetches and parses an XML or JSON file to
    return the entries.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'url'. May
            contain the keys 'path' or 'html5'.

            url (str): The web site to fetch
            path (str): The path to extract (default: None, i.e., return entire
                page)

            html5 (bool): Use the HTML5 parser (default: False)

    Returns:
        Deferred: twisted.internet.defer.Deferred stream of items

    Examples:
        >>> from twisted.internet.task import react
        >>> from riko import get_path
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x)['title'])
        ...     path = 'value.items'
        ...     conf = {'url': get_path('gigs.json'), 'path': path}
        ...     d = asyncPipe(conf=conf)
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=tu.FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        Business System Analyst
    """
    return asyncParser(*args, **kwargs)


@processor(**OPTS)
def pipe(*args, **kwargs):
    """A source that fetches and parses an XML or JSON file to
    return the entries.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'url'. May
            contain the keys 'path' or 'html5'.

            url (str): The web site to fetch
            path (str): The path to extract (default: None, i.e., return entire
                page)

            html5 (bool): Use the HTML5 parser (default: False)

    Returns:
        dict: an iterator of items

    Examples:
        >>> from riko import get_path
        >>>
        >>> conf = {'url': get_path('gigs.json'), 'path': 'value.items'}
        >>> next(pipe(conf=conf))['title']
        u'Business System Analyst'
        >>> path = 'appointment'
        >>> conf = {'url': get_path('places.xml'), 'path': path}
        >>> next(pipe(conf=conf))['subject']
        'Bring pizza home'
        >>> conf = {'url': get_path('places.xml'), 'path': ''}
        >>> next(pipe(conf=conf))['reminder']
        '15'
    """
    return parser(*args, **kwargs)
