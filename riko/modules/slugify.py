# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.slugify
~~~~~~~~~~~~~~~~~~~~
Provides functions for slugifying text.

Examples:
    basic usage::

        >>> from riko.modules.slugify import pipe
        >>>
        >>> next(pipe({'content': 'hello world'}))['slugify'] == 'hello-world'
        True

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

import pygogo as gogo

from builtins import *  # noqa pylint: disable=unused-import
from slugify import slugify
from . import processor

OPTS = {'ftype': 'text', 'extract': 'separator', 'field': 'content'}
DEFAULTS = {'separator': '-'}
logger = gogo.Gogo(__name__, monolog=True).logger


def parser(word, separator, skip=False, **kwargs):
    """ Parsers the pipe content

    Args:
        word (str): The string to transform
        separator (str): The slug separator.
        skip (bool): Don't parse the content
        kwargs (dict): Keyword arguments

    Kwargs:
        assign (str): Attribute to assign parsed content (default: exchangerate)
        stream (dict): The original item

    Returns:
        dict: The item

    Examples:
        >>> from meza.fntools import Objectify
        >>>
        >>> item = {'content': 'hello world'}
        >>> kwargs = {'stream': item}
        >>> parser(item['content'], '-', **kwargs) == 'hello-world'
        True
    """
    if skip:
        parsed = kwargs['stream']
    else:
        parsed = slugify(word.strip(), separator=separator)

    return parsed


@processor(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args, **kwargs):
    """A processor module that asynchronously slugifies the field of an item.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        assign (str): Attribute to assign parsed content (default: slugify)
        field (str): Item attribute to operate on (default: 'content')

    Returns:
       Deferred: twisted.internet.defer.Deferred item with concatenated content

    Examples:
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x)['slugify'] == 'hello-world')
        ...     d = async_pipe({'content': 'hello world'})
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        True
    """
    return parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs):
    """A processor that slugifies the field of an item.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. May contain the key 'separator'.
            separator (str): The slug separator (default: '-')

        assign (str): Attribute to assign parsed content (default: slugify)
        field (str): Item attribute to operate on (default: 'content')

    Yields:
        dict: an item with concatenated content

    Examples:
        >>> next(pipe({'content': 'hello world'}))['slugify'] == 'hello-world'
        True
        >>> slugified = 'hello_world'
        >>> conf = {'separator': '_'}
        >>> item = {'title': 'hello world'}
        >>> kwargs = {'conf': conf, 'field': 'title', 'assign': 'result'}
        >>> next(pipe(item, **kwargs))['result'] == slugified
        True
    """
    return parser(*args, **kwargs)
