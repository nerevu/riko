# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.pipehash
~~~~~~~~~~~~~~~~~~~~~~~~~
Provides functions for hashing text.

Examples:
    basic usage::

        >>> from riko.modules.pipehash import pipe
        >>> pipe({'content': 'hello world'}).next()['hash']
        2794220831L

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""

from __future__ import (
    absolute_import, division, print_function, unicode_literals)

import ctypes

from builtins import *

from . import processor
from riko.lib.log import Logger

OPTS = {'ftype': 'text', 'ptype': 'none', 'field': 'content'}
DEFAULTS = {}
logger = Logger(__name__).logger


def parser(word, _, skip, **kwargs):
    """ Parsers the pipe content

    Args:
        item (obj): The entry to process (a DotDict instance)
        _ (None): Ignored.
        skip (bool): Don't parse the content
        kwargs (dict): Keyword arguments

    Kwargs:
        assign (str): Attribute to assign parsed content (default: exchangerate)
        feed (dict): The original item

    Returns:
        Tuple(dict, bool): Tuple of (item, skip)

    Examples:
        >>> from riko.lib.utils import Objectify
        >>>
        >>> item = {'content': 'hello world'}
        >>> kwargs = {'feed': item}
        >>> parser(item['content'], None, False, **kwargs)[0]
        2794220831L
    """
    parsed = kwargs['feed'] if skip else ctypes.c_uint(hash(word)).value
    return parsed, skip


@processor(DEFAULTS, async=True, **OPTS)
def asyncPipe(*args, **kwargs):
    """A processor module that asynchronously hashes the field of a feed item.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        assign (str): Attribute to assign parsed content (default: simplemath)
        field (str): Item attribute from which to obtain the first number to
            operate on (default: 'content')

    Returns:
       Deferred: twisted.internet.defer.Deferred item with concatenated content

    Examples:
        >>> from twisted.internet.task import react
        >>> from riko.twisted import utils as tu
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(x.next()['hash'])
        ...     d = asyncPipe({'content': 'hello world'})
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=tu.FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        2794220831
    """
    return parser(*args, **kwargs)


@processor(**OPTS)
def pipe(*args, **kwargs):
    """A processor that hashes the field of a feed item.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        assign (str): Attribute to assign parsed content (default: hash)
        field (str): Item attribute from which to obtain the first number to
            operate on (default: 'content')

    Yields:
        dict: an item with concatenated content

    Examples:
        >>> pipe({'content': 'hello world'}).next()['hash']
        2794220831L
        >>> kwargs = {'field': 'title', 'assign': 'result'}
        >>> pipe({'title': 'greeting'}, **kwargs).next()['result']
        4090572397L
    """
    return parser(*args, **kwargs)
