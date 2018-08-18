# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.strconcat
~~~~~~~~~~~~~~~~~~~~~~
Provides functions for concatenating strings (aka stringbuilder).

Useful when you need to build a string from multiple substrings, some coded
into the pipe, other parts supplied when the pipe is run.

Examples:
    basic usage::

        >>> from riko.modules.strconcat import pipe
        >>>
        >>> item = {'word': 'hello'}
        >>> part = [{'subkey': 'word'}, {'value': ' world'}]
        >>> next(pipe(item, conf={'part': part}))['strconcat'] == 'hello world'
        True

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

import pygogo as gogo

from builtins import *  # noqa pylint: disable=unused-import
from . import processor

OPTS = {'listize': True, 'extract': 'part'}
logger = gogo.Gogo(__name__, monolog=True).logger


def parser(_, parts, skip=False, **kwargs):
    """ Parses the pipe content

    Args:
        _ (dict): The item (ignored)
        parts (List[str]): The content to concatenate
        skip (bool): Don't parse the content
        kwargs (dict): Keyword arguments

    Kwargs:
        stream (dict): The original item

    Returns:
        str: The concatenated string

    Examples:
        >>> parser(None, ['one', 'two']) == 'onetwo'
        True
    """
    if skip:
        parsed = kwargs['stream']
    else:
        parsed = ''.join(str(p) for p in parts if p)

    return parsed


@processor(isasync=True, **OPTS)
def async_pipe(*args, **kwargs):
    """A processor module that asynchronously concatenates strings.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'part'.

            part (dict): can be either a dict or list of dicts. Must contain
                one of the following keys: 'value', 'subkey', or 'terminal'.

                value (str): The substring value
                subkey (str): The item attribute from which to obtain a
                    substring

                terminal (str): The id of a pipe from which to obtain a
                    substring

        assign (str): Attribute to assign parsed content (default: strconcat)

    Returns:
       Deferred: twisted.internet.defer.Deferred item with concatenated content

    Examples:
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x)['strconcat'])
        ...     item = {'title': 'Hello world'}
        ...     part = [{'subkey': 'title'}, {'value': 's'}]
        ...     d = async_pipe(item, conf={'part': part})
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        Hello worlds
    """
    return parser(*args, **kwargs)


@processor(**OPTS)
def pipe(*args, **kwargs):
    """A processor that concatenates strings.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'part'.

            part (dict): can be either a dict or list of dicts. Must contain
                one of the following keys: 'value', 'subkey', or 'terminal'.

                value (str): The substring value
                subkey (str): The item attribute from which to obtain a
                    substring

                terminal (str): The id of a pipe from which to obtain a
                    substring

        assign (str): Attribute to assign parsed content (default: strconcat)

    Yields:
        dict: an item with concatenated content

    Examples:
        >>> item = {'img': {'src': 'http://www.site.com'}}
        >>> part = [
        ...     {'value': '<img src="'}, {'subkey': 'img.src'}, {'value': '">'}
        ... ]
        >>> conf = {'part': part}
        >>> resp = '<img src="http://www.site.com">'
        >>> next(pipe(item, conf=conf))['strconcat'] == resp
        True
        >>> next(pipe(item, conf=conf, assign='result'))['result'] == resp
        True
    """
    return parser(*args, **kwargs)
