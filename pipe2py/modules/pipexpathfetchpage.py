# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
pipe2py.modules.pipexpathfetchpage
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Provides functions for fetching the source of a given web site as DOM nodes or a
string.

This module fetches the source of a given web site as DOM nodes or a string.
This data can then be converted into a RSS/JSON feed or merged with other data
in your Pipe using the Regex module, String Builder modules and others that
will help achieve what you want.

By default, the module will output the DOM elements as items. You can
optionally use the "Emit items as string" checkbox if you need the html as a
string.

You can use the "Extract using XPATH" field to fine tune what you need from the
HTML Page. For example, if I want all the links in the page I can simply use
"/a" to grab all links. If I want all the images in the html I can do "/img".
Read more on XPATH. You can also find XPATH statements using firebug to target
data that you want in a HTML page.

You have the option to run the parser using support for HTML4 (by default) or
checking the "Use HTML5 parser" checkbox to use the HTML5 parser.

Examples:
    basic usage::

        >>> from pipe2py.modules.pipexpathfetchpage import pipe
        >>> conf = {'url': FILES[1], 'xpath': '/rss/channel/item'}
        >>> title = 'Running “Native” Data Wrangling Applications in the Browser'
        >>> pipe(conf=conf).next()['title'][:59] == title
        True

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""

from __future__ import (
    absolute_import, division, print_function, with_statement,
    unicode_literals)

from urllib2 import urlopen
from os.path import splitext
from itertools import imap

from lxml import objectify, html
from lxml.html import html5parser
from twisted.internet.defer import inlineCallbacks, returnValue
from twisted.web.client import getPage
from twisted.web import microdom

from . import processor, FEEDS, FILES
from pipe2py.lib import utils
from pipe2py.lib.log import Logger
from pipe2py.twisted import utils as tu

OPTS = {'emit': True}
logger = Logger(__name__).logger


# TODO: convert relative links to absolute
# TODO: remove the closing tag if using an HTML tag stripped of HTML tags
# TODO: clean html with Tidy
def genXPATH(tree, xpath, pos=0):
    tags = xpath.split('/')[1:] if xpath else []
    elements = tree.getElementsByTagName(tags[pos]) if tags else [tree]

    if len(tags or [1]) - pos == 1:
        for element in elements:
            yield element
    else:
        for element in elements:
            for e in genXPATH(element, xpath, pos + 1):
                yield e


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
        ...     callback = lambda x: print(x[0].next()['title'][:59])
        ...     objconf = Objectify({'url': FILES[1], 'xpath': '/rss/channel/item'})
        ...     kwargs = {'feed': {}}
        ...     d = asyncParser(None, objconf, False, **kwargs)
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=tu.FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        Running “Native” Data Wrangling Applications in the Browser
    """
    if skip:
        feed = kwargs['feed']
    else:
        url = utils.get_abspath(objconf.url)
        ext = splitext(url)[1].lstrip('.')
        f = yield tu.urlOpen(url)

        if ext == 'xml':
            tree = yield microdom.parse(f)
            elements = genXPATH(tree, objconf.xpath)
            items = imap(tu.elementToDict, elements)
        elif ext == 'html':
            tree = html5parser.parse(f) if objconf.html5 else html.parse(f)
            root = tree.getroot()
            elements = root.xpath(objconf.xpath)
            items = imap(utils.etree_to_dict, elements)
        else:
            raise TypeError('Invalid file type %s' % ext)

        feed = ({kwargs['assign']: unicode(i)} for i in items) if objconf.stringify else items

    result = (feed, skip)
    returnValue(result)


def parser(_, objconf, skip, **kwargs):
    """ Parses the pipe content

    Args:
        _ (dict): The item (ignored)
        objconf (obj): The pipe configuration (an Objectify instance)
        skip (bool): Don't parse the content

    Returns:
        Tuple(Iter[dict], bool): Tuple of (feed, skip)

    Examples:
        >>> from pipe2py.lib.utils import Objectify
        >>> objconf = Objectify({'url': FILES[1], 'xpath': '/rss/channel/item'})
        >>> kwargs = {'feed': {}}
        >>> result, skip = parser(None, objconf, False, **kwargs)
        >>> title = 'Running “Native” Data Wrangling Applications in the Browser'
        >>> result.next()['title'][:59] == title
        True
    """
    if skip:
        feed = kwargs['feed']
    else:
        url = utils.get_abspath(objconf.url)
        ext = splitext(url)[1].lstrip('.')
        f = urlopen(url)

        if ext == 'xml':
            tree = objectify.parse(f)
        elif ext == 'html':
            tree = html5parser.parse(f) if objconf.html5 else html.parse(f)

        root = tree.getroot()
        elements = root.xpath(objconf.xpath)
        items = imap(utils.etree_to_dict, elements)
        feed = ({kwargs['assign']: unicode(i)} for i in items) if objconf.stringify else items

    return feed, skip


@processor(async=True, **OPTS)
def asyncPipe(*args, **kwargs):
    """A source that asynchronously fetches the content of a given website as
    DOM nodes or a string.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        context (obj): pipe2py.Context object
        conf (dict): The pipe configuration. Must contain the key 'url'. May
            contain the keys 'xpath', 'html5', 'stringify', or 'assign'.

            url (str): The web site to fetch
            xpath (str): The XPATH to extract (default: None, i.e., return
                entire page)

            html5 (bool): Use the HTML5 parser (default: False)
            stringify (bool): Return the web site as a string (default: False)
            assign (str): Attribute to assign parsed content (default: content)

        field (str): Item attribute from which to obtain the string to be
            tokenized (default: content)

    Returns:
        dict: twisted.internet.defer.Deferred item with feeds

    Examples:
        >>> from twisted.internet.task import react
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(x.next()['guid']['content'])
        ...     path = 'value.items'
        ...     conf = {'url': FILES[1], 'xpath': '/rss/channel/item'}
        ...     d = asyncPipe(conf=conf)
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=tu.FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        http://blog.ouseful.info/?p=12065
    """
    return asyncParser(*args, **kwargs)


@processor(**OPTS)
def pipe(*args, **kwargs):
    """A source that fetches the content of a given website as DOM nodes or a
    string.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        context (obj): pipe2py.Context object
        conf (dict): The pipe configuration. Must contain the key 'url'. May
            contain the keys 'xpath', 'html5', 'stringify', or 'assign'.

            url (str): The web site to fetch
            xpath (str): The XPATH to extract (default: None, i.e., return
                entire page)

            html5 (bool): Use the HTML5 parser (default: False)
            stringify (bool): Return the web site as a string (default: False)
            assign (str): Attribute to assign parsed content (default: content)

        field (str): Item attribute from which to obtain the string to be
            tokenized (default: content)

    Yields:
        dict: an item of the feed

    Examples:
        >>> conf = {'url': FILES[1], 'xpath': '/rss/channel/item'}
        >>> pipe(conf=conf).next()['guid']['content']
        'http://blog.ouseful.info/?p=12065'
    """
    return parser(*args, **kwargs)
