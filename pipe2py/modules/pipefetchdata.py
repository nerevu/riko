# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
pipe2py.modules.pipefetchdata
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Provides functions for fetching XML and JSON data sources.

Accesses and extracts data from XML and JSON data sources on the web. This data
can then be converted into an RSS feed or merged with other data in your Pipe.

Examples:
    basic usage::

        >>> from pipe2py.modules.pipefetchdata import pipe
        >>> conf = {'url': FILES[2], 'path': 'value.items'}
        >>> pipe(conf=conf).next()['title']
        u'Business System Analyst'

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""

from __future__ import (
    absolute_import, division, print_function, with_statement,
    unicode_literals)

from lxml import objectify, html
from lxml.html import html5parser
from lxml.etree import XMLSyntaxError, ParseError
from urllib2 import urlopen
from json import loads
from os.path import splitext
from functools import partial
from twisted.internet.defer import inlineCallbacks, returnValue

from . import processor, FEEDS, FILES
from pipe2py.lib import utils
from pipe2py.lib.log import Logger
from pipe2py.twisted import utils as tu

OPTS = {'emit': True}
reducer = lambda element, i: element.get(i) if element else None
json2dict = lambda f: loads(f.read())
logger = Logger(__name__).logger


def xml2dict(f):
    tree = objectify.parse(f)
    root = tree.getroot()
    return utils.etree_to_dict(root)


def html2dict(f, html5=False):
    tree = html5parser.parse(f) if html5 else html.parse(f)
    root = tree.getroot()
    return utils.etree_to_dict(root)


@inlineCallbacks
def asyncParser(_, objconf, skip, **kwargs):
    """ Asynchronously parses the pipe content

    Args:
        _ (dict): The item (ignored)
        objconf (obj): The pipe configuration (an Objectify instance)
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
        ...     callback = lambda x: print(x[0][0]['title'])
        ...     objconf = Objectify({'url': FILES[2], 'path': 'value.items'})
        ...     kwargs = {'feed': {}}
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
        feed = kwargs['feed']
    else:
        url = utils.get_abspath(objconf.url)
        ext = splitext(url)[1].lstrip('.')
        path = objconf.path.split('.') if objconf.path else []
        f = yield tu.urlOpen(url)

        if ext == 'xml':
            element = xml2dict(f)
        elif ext == 'json':
            element = json2dict(f)
        elif ext == 'html':
            element = html2dict(f, objconf.html5)
        else:
            raise TypeError('Invalid file type %s' % ext)

        feed = yield tu.coopReduce(reducer, path, element)

    result = (feed, skip)
    returnValue(result)


def parser(_, objconf, skip, **kwargs):
    """ Parses the pipe content

    Args:
        _ (dict): The item (ignored)
        objconf (obj): The pipe configuration (an Objectify instance)
        skip (bool): Don't parse the content
        kwargs (dict): Keyword argurments

    Kwargs:
        feed (dict): The original item

    Returns:
        Tuple(Iter[dict], bool): Tuple of (feed, skip)

    Examples:
        >>> from pipe2py.lib.utils import Objectify
        >>> objconf = Objectify({'url': FILES[2], 'path': 'value.items'})
        >>> kwargs = {'feed': {}}
        >>> result, skip = parser(None, objconf, False, **kwargs)
        >>> result[0]['title']
        u'Business System Analyst'
    """
    if skip:
        feed = kwargs['feed']
    else:
        url = utils.get_abspath(objconf.url)
        ext = splitext(url)[1].lstrip('.')
        path = objconf.path.split('.') if objconf.path else []
        f = urlopen(url)

        if ext == 'xml':
            element = xml2dict(f)
        elif ext == 'json':
            element = json2dict(f)
        elif ext == 'html':
            element = html2dict(f, objconf.html5)
        else:
            raise TypeError('Invalid file type %s' % ext)

        feed = reduce(reducer, path, element)

    return feed, skip


@processor(async=True, **OPTS)
def asyncPipe(*args, **kwargs):
    """A source that asynchronously fetches and parses an XML or JSON file to
    return the feed entries.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        context (obj): pipe2py.Context object
        conf (dict): The pipe configuration
            url (str): The web site to fetch
            path (str): The path to extract (default: None, i.e., return entire
                page)

            html5 (bool): Use the HTML5 parser (default: False)
            assign (str): Attribute to assign parsed content (default: content)

        field (str): Item attribute from which to obtain the string to be
            tokenized (default: content)

    Returns:
        Deferred: twisted.internet.defer.Deferred feed of items

    Examples:
        >>> from twisted.internet.task import react
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(x.next()['title'])
        ...     path = 'value.items'
        ...     conf = {'url': {'value': FILES[2]}, 'path': {'value': path}}
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
    return the feed entries.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        context (obj): pipe2py.Context object
        conf (dict): The pipe configuration
            url (str): The web site to fetch
            path (str): The path to extract (default: None, i.e., return entire
                page)

            html5 (bool): Use the HTML5 parser (default: False)
            assign (str): Attribute to assign parsed content (default: content)

        field (str): Item attribute from which to obtain the string to be
            tokenized (default: content)

    Returns:
        dict: an iterator of items

    Examples:
        >>> path = 'value.items'
        >>> conf = {'url': {'value': FILES[2]}, 'path': {'value': path}}
        >>> pipe(conf=conf).next()['title']
        u'Business System Analyst'
        >>> path = 'appointment'
        >>> conf = {'url': {'value': FILES[3]}, 'path': {'value': path}}
        >>> pipe(conf=conf).next()['subject']
        'Bring pizza home'
        >>> conf = {'url': {'value': FILES[3]}, 'path': {'value': ''}}
        >>> pipe(conf=conf).next()['reminder']
        '15'
    """
    return parser(*args, **kwargs)
