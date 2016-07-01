# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.pipexpathfetchpage
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
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

        >>> from riko import get_path
        >>> from riko.modules.pipexpathfetchpage import pipe
        >>>
        >>> url = get_path('ouseful.xml')
        >>> conf = {'url': url, 'xpath': '/rss/channel/item'}
        >>> title = 'Running “Native” Data Wrangling Applications'
        >>> next(pipe(conf=conf))['title'][:44] == title
        True

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

import pygogo as gogo

from contextlib import closing
from os.path import splitext

from builtins import *
from six.moves.urllib.request import urlopen


from . import processor
from riko.lib import utils
from riko.bado import coroutine, return_value, util as tu, io
from meza._compat import encode

OPTS = {'ftype': 'none'}
logger = gogo.Gogo(__name__, monolog=True).logger


# TODO: convert relative links to absolute
# TODO: remove the closing tag if using an HTML tag stripped of HTML tags
# TODO: clean html with Tidy


@coroutine
def asyncParser(_, objconf, skip, **kwargs):
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
        Tuple(Iter[dict], bool): Tuple of (stream, skip)

    Examples:
        >>> from riko import get_path
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>> from riko.lib.utils import Objectify
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x[0])['title'][:44])
        ...     url, path = get_path('ouseful.xml'), '/rss/channel/item'
        ...     objconf = Objectify({'url': url, 'xpath': path})
        ...     d = asyncParser(None, objconf, False, stream={})
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        Running “Native” Data Wrangling Applications
    """
    if skip:
        stream = kwargs['stream']
    else:
        url = utils.get_abspath(objconf.url)
        ext = splitext(url)[1].lstrip('.')
        html = ext == 'html'
        f = yield io.urlOpen(url)
        tree = yield tu.xml2etree(f, html=html)
        elements = utils.xpath(tree, objconf.xpath)
        items = map(tu.etreeToDict, elements)
        stringified = ({kwargs['assign']: encode(i)} for i in items)
        stream = stringified if objconf.stringify else items

    result = (stream, skip)
    return_value(result)


def parser(_, objconf, skip, **kwargs):
    """ Parses the pipe content

    Args:
        _ (None): Ignored
        objconf (obj): The pipe configuration (an Objectify instance)
        skip (bool): Don't parse the content

    Returns:
        Tuple(Iter[dict], bool): Tuple of (stream, skip)

    Examples:
        >>> from riko.lib.utils import Objectify
        >>> from riko import get_path
        >>>
        >>> url = get_path('ouseful.xml')
        >>> objconf = Objectify({'url': url, 'xpath': '/rss/channel/item'})
        >>> result, skip = parser(None, objconf, False, stream={})
        >>> title = 'Running “Native” Data Wrangling Applications'
        >>> next(result)['title'][:44] == title
        True
    """
    if skip:
        stream = kwargs['stream']
    else:
        url = utils.get_abspath(objconf.url)
        ext = splitext(url)[1].lstrip('.')
        xml = ext == 'xml'

        with closing(urlopen(url)) as f:
            root = utils.xml2etree(f, xml=xml, html5=objconf.html5).getroot()
            elements = utils.xpath(root, objconf.xpath)

        items = map(utils.etree2dict, elements)
        stringified = ({kwargs['assign']: str(i)} for i in items)
        stream = stringified if objconf.stringify else items

    return stream, skip


@processor(isasync=True, **OPTS)
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
        dict: twisted.internet.defer.Deferred item

    Examples:
        >>> from riko import get_path
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x)['guid']['content'])
        ...     url = get_path('ouseful.xml')
        ...     conf = {'url': url, 'xpath': '/rss/channel/item'}
        ...     d = asyncPipe(conf=conf)
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
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
        conf (dict): The pipe configuration. Must contain the key 'url'. May
            contain the keys 'xpath', 'html5', 'stringify', or 'assign'.

            url (str): The web site to fetch
            xpath (str): The XPATH to extract (default: None, i.e., return
                entire page)

            html5 (bool): Use the HTML5 parser (default: False)
            stringify (bool): Return the web site as a string (default: False)
            assign (str): Attribute to assign parsed content (default: content)

    Yields:
        dict: item

    Examples:
        >>> from riko import get_path
        >>> url = get_path('ouseful.xml')
        >>> conf = {'url': url, 'xpath': '/rss/channel/item'}
        >>> next(pipe(conf=conf))['guid']['content']
        'http://blog.ouseful.info/?p=12065'
    """
    return parser(*args, **kwargs)
