# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.hash
~~~~~~~~~~~~~~~~~
Provides functions for hashing text.

Note: If the PYTHONHASHSEED environment variable is set to an integer value,
it is used as a fixed seed for generating the hash. Its purpose is to allow
repeatable hashing across python processes and versions. The integer must be a
decimal number in the range [0, 4294967295].

Specifying the value 0 will disable hash randomization. If this variable is set
to `random`, a random value is used to seed the hashes. Hash randomization is
is enabled by default for Python 3.2.3+, and disabled otherwise.

Examples:
    basic usage::

        >>> from riko.modules.hash import pipe
        >>>
        >>> _hash = ctypes.c_uint(hash('hello world')).value
        >>> next(pipe({'content': 'hello world'}))['hash'] == _hash
        True

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

import ctypes

from builtins import *

from . import processor
import pygogo as gogo

OPTS = {'ftype': 'text', 'ptype': 'none', 'field': 'content'}
DEFAULTS = {}
logger = gogo.Gogo(__name__, monolog=True).logger


def parser(word, _, skip, **kwargs):
    """ Parsers the pipe content

    Args:
        item (obj): The entry to process (a DotDict instance)
        _ (None): Ignored.
        skip (bool): Don't parse the content
        kwargs (dict): Keyword arguments

    Kwargs:
        assign (str): Attribute to assign parsed content (default: exchangerate)
        stream (dict): The original item

    Returns:
        Tuple(dict, bool): Tuple of (item, skip)

    Examples:
        >>> from riko.lib.utils import Objectify
        >>>
        >>> _hash = ctypes.c_uint(hash('hello world')).value
        >>> item = {'content': 'hello world'}
        >>> kwargs = {'stream': item}
        >>> parser(item['content'], None, False, **kwargs)[0] == _hash
        True
    """
    parsed = kwargs['stream'] if skip else ctypes.c_uint(hash(word)).value
    return parsed, skip


@processor(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args, **kwargs):
    """A processor module that asynchronously hashes the field of an item.

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
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> _hash = ctypes.c_uint(hash('hello world')).value
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x)['hash'] == _hash)
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


@processor(**OPTS)
def pipe(*args, **kwargs):
    """A processor that hashes the field of an item.

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
        >>> _hash = ctypes.c_uint(hash('hello world')).value
        >>> next(pipe({'content': 'hello world'}))['hash'] == _hash
        True
        >>> _hash = ctypes.c_uint(hash('greeting')).value
        >>> kwargs = {'field': 'title', 'assign': 'result'}
        >>> next(pipe({'title': 'greeting'}, **kwargs))['result'] == _hash
        True
    """
    return parser(*args, **kwargs)
