# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.xpathfetchpage
~~~~~~~~~~~~~~~~~~~~~~~~~~~
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
        >>> from riko.modules.xpathfetchpage import pipe
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

import traceback
import pygogo as gogo

from contextlib import closing
from os.path import splitext

from builtins import *
from six.moves.urllib.request import urlopen


from . import processor
from riko.lib import utils
from riko.bado import coroutine, return_value, util, io
from meza._compat import encode

OPTS = {'ftype': 'none'}
logger = gogo.Gogo(__name__, monolog=True).logger


# TODO: convert relative links to absolute
# TODO: remove the closing tag if using an HTML tag stripped of HTML tags
# TODO: clean html with Tidy


@coroutine
def async_parser(_, objconf, skip, **kwargs):
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
        >>> @coroutine
        ... def run(reactor):
        ...     xml_url = get_path('ouseful.xml')
        ...     xml_conf = {'url': xml_url, 'xpath': '/rss/channel/item'}
        ...     xml_objconf = Objectify(xml_conf)
        ...     xml_args = (None, xml_objconf, False)
        ...     html_url = get_path('sciencedaily.html')
        ...     html_conf = {'url': html_url, 'xpath': '/html/head/title'}
        ...     html_objconf = Objectify(html_conf)
        ...     html_args = (None, html_objconf, False)
        ...     kwargs = {'stream': {}}
        ...
        ...     try:
        ...         xml_stream, _ = yield async_parser(*xml_args, **kwargs)
        ...         html_stream, _ = yield async_parser(*html_args, **kwargs)
        ...         print(next(xml_stream)['title'][:44])
        ...         print(next(html_stream))
        ...     except Exception as e:
        ...         logger.error(e)
        ...         logger.error(traceback.format_exc())
        ...
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        Running “Native” Data Wrangling Applications
        Help Page -- ScienceDaily
    """
    if skip:
        stream = kwargs['stream']
    else:
        url = utils.get_abspath(objconf.url)
        ext = splitext(url)[1].lstrip('.')
        xml = (ext == 'xml') or objconf.strict

        try:
            f = yield io.async_url_open(url)
            tree = yield util.xml2etree(f, xml=xml)
        except Exception as e:
            logger.error(e)
            logger.error(traceback.format_exc())

        elements = utils.xpath(tree, objconf.xpath)
        f.close()
        items = map(util.etree2dict, elements)
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
        xml = (ext == 'xml') or objconf.strict

        with closing(urlopen(url)) as f:
            root = utils.xml2etree(f, xml=xml, html5=objconf.html5).getroot()
            elements = utils.xpath(root, objconf.xpath)

        items = map(utils.etree2dict, elements)
        stringified = ({kwargs['assign']: str(i)} for i in items)
        stream = stringified if objconf.stringify else items

    return stream, skip


@processor(isasync=True, **OPTS)
def async_pipe(*args, **kwargs):
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

            strict (bool): Use the strict XML parser (default: False)
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
        >>> @coroutine
        ... def run(reactor):
        ...     xml_url = get_path('ouseful.xml')
        ...     xml_conf = {'url': xml_url, 'xpath': '/rss/channel/item'}
        ...     html_url = get_path('sciencedaily.html')
        ...     html_conf = {'url': html_url, 'xpath': '/html/head/title'}
        ...
        ...     try:
        ...         xml_stream = yield async_pipe(conf=xml_conf)
        ...         html_stream = yield async_pipe(conf=html_conf)
        ...         print(next(xml_stream)['guid']['content'])
        ...         print(next(html_stream))
        ...     except Exception as e:
        ...         logger.error(e)
        ...         logger.error(traceback.format_exc())
        ...
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        http://blog.ouseful.info/?p=12065
        Help Page -- ScienceDaily
    """
    return async_parser(*args, **kwargs)


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

            strict (bool): Use the strict XML parser (default: False)
            html5 (bool): Use the HTML5 parser (default: False)
            stringify (bool): Return the web site as a string (default: False)
            assign (str): Attribute to assign parsed content (default: content)

    Yields:
        dict: item

    Examples:
        >>> from riko import get_path
        >>>
        >>> url = get_path('ouseful.xml')
        >>> conf = {'url': url, 'xpath': '/rss/channel/item'}
        >>> next(pipe(conf=conf))['guid']['content']
        'http://blog.ouseful.info/?p=12065'
        >>> url = get_path('sciencedaily.html')
        >>> conf = {'url': url, 'xpath': '/html/head/title'}
        >>> next(pipe(conf=conf)) == 'Help Page -- ScienceDaily'
        True
    """
    return parser(*args, **kwargs)
