# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.fetchpage
~~~~~~~~~~~~~~~~~~~~~~
Provides functions for fetching web pages.

Fetches the source of a given web site as a string. This data can then be
converted into an RSS feed or merged with other data in your Pipe using the
`regex` module.

Examples:
    basic usage::

        >>> from riko.modules.fetchpage import pipe
        >>> from riko import get_path
        >>> from meza._compat import decode
        >>>
        >>> url = get_path('cnn.html')
        >>> conf = {'url': url, 'start': '<title>', 'end': '</title>'}
        >>> resp = next(pipe(conf=conf))['content'][:21]
        >>> decode(resp) == 'CNN.com International'
        True

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

import pygogo as gogo

from contextlib import closing
from codecs import iterdecode

from builtins import *
from six.moves.urllib.request import urlopen
from meza._compat import encode

from . import processor
from riko.lib import utils
from riko.bado import coroutine, return_value, io
from riko.lib.tags import get_text

OPTS = {'ftype': 'none'}
logger = gogo.Gogo(__name__, monolog=True).logger


def get_string(content, start, end):
    # TODO: convert relative links to absolute
    # TODO: remove the closing tag if using an HTML tag stripped of HTML tags
    # TODO: clean html with Tidy
    content = encode(content)
    start_pos = content.find(encode(start)) if start else 0
    right = content[start_pos + (len(start) if start else 0):]
    end_pos = right[1:].find(encode(end)) + 1 if end else len(right)
    return right[:end_pos] if end_pos > 0 else right


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
        >>> from meza._compat import decode
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(decode(next(x[0])['content'][:32]))
        ...     url = get_path('cnn.html')
        ...     conf = {'url': url, 'start': '<title>', 'end': '</title>'}
        ...     objconf = Objectify(conf)
        ...     kwargs = {'stream': {}, 'assign': 'content'}
        ...     d = async_parser(None, objconf, False, **kwargs)
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        CNN.com International - Breaking
    """
    if skip:
        stream = kwargs['stream']
    else:
        url = utils.get_abspath(objconf.url)
        content = yield io.async_url_read(url)
        parsed = get_string(content, objconf.start, objconf.end)
        detagged = get_text(parsed) if objconf.detag else parsed
        splits = detagged.split(objconf.token) if objconf.token else [detagged]
        stream = ({kwargs['assign']: chunk} for chunk in splits)

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
        >>> from meza._compat import decode
        >>>
        >>> url = get_path('cnn.html')
        >>> conf = {'url': url, 'start': '<title>', 'end': '</title>'}
        >>> objconf = Objectify(conf)
        >>> kwargs = {'stream': {}, 'assign': 'content'}
        >>> result, skip = parser(None, objconf, False, **kwargs)
        >>> resp = next(result)['content'][:21]
        >>> decode(resp) == 'CNN.com International'
        True
    """
    if skip:
        stream = kwargs['stream']
    else:
        url = utils.get_abspath(objconf.url)

        with closing(urlopen(url)) as response:
            f = response.fp
            encoding = utils.get_response_encoding(response, 'utf-8')
            decoded = iterdecode(f, encoding)
            sliced = utils.betwix(decoded, objconf.start, objconf.end, True)
            content = '\n'.join(sliced)

        parsed = get_string(content, objconf.start, objconf.end)
        detagged = get_text(parsed) if objconf.detag else parsed
        splits = detagged.split(objconf.token) if objconf.token else [detagged]
        stream = ({kwargs['assign']: chunk} for chunk in splits)

    return stream, skip


@processor(isasync=True, **OPTS)
def async_pipe(*args, **kwargs):
    """A source that asynchronously fetches the content of a given web site as
    a string.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'url'. May
            contain the keys 'start', 'end', 'token', or 'detag'.

            url (str): The web site to fetch
            start (str): The starting string to fetch (exclusive, default:
                None).

            end (str): The ending string to fetch (exclusive, default: None).
            token (str): The tokenizer delimiter string (default: None).
            detag (bool): Remove html tags from content (default: False).

        assign (str): Attribute to assign parsed content (default: content)

    Returns:
        dict: twisted.internet.defer.Deferred item

    Examples:
        >>> from riko import get_path
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>> from meza._compat import decode
        >>>
        >>> resp = 'html PUBLIC "-//W3C//DTD XHTML+RDFa 1.0//EN" "'
        >>> def run(reactor):
        ...     callback = lambda x: print(decode(next(x)['content']) == resp)
        ...     url, path = get_path('bbc.html'), 'value.items'
        ...     conf = {'url': url, 'start': 'DOCTYPE ', 'end': 'http'}
        ...     d = async_pipe(conf=conf)
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        True
    """
    return async_parser(*args, **kwargs)


@processor(**OPTS)
def pipe(*args, **kwargs):
    """A source that fetches the content of a given web site as a string.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'url'. May
            contain the keys 'start', 'end', 'token', or 'detag'.

            url (str): The web site to fetch
            start (str): The starting string to fetch (exclusive, default:
                None).

            end (str): The ending string to fetch (exclusive, default: None).
            token (str): The tokenizer delimiter string (default: None).
            detag (bool): Remove html tags from content (default: False).

        assign (str): Attribute to assign parsed content (default: content)

    Yields:
        dict: item

    Examples:
        >>> from riko import get_path
        >>> from meza._compat import decode
        >>>
        >>> url = get_path('bbc.html')
        >>> conf = {'url': url, 'start': 'DOCTYPE ', 'end': 'http'}
        >>> content = 'html PUBLIC "-//W3C//DTD XHTML+RDFa 1.0//EN" "'
        >>> decode(next(pipe(conf=conf))['content']) == content
        True
    """
    return parser(*args, **kwargs)
