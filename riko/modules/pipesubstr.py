# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.pipesubstr
~~~~~~~~~~~~~~~~~~~~~~~
Provides functions for obtaining a portion of a string.

You enter two numbers to tell the module the starting character position and
the length of the resulting substring. If your input string is "ABCDEFG", then
a From value of 2 and length of 4 gives you a resulting string of "CDEF".
Notice that the first character in the original string is 0, not 1.

If you enter too long a length, the module just returns a substring to the end
of the input string, so if you enter a From of 3 and a length of 100, you'll
get a result of "DEFG".
Examples:
    basic usage::

        >>> from riko.modules.pipesubstr import pipe
        >>> conf = {'start': '3', 'length': '4'}
        >>> next(pipe({'content': 'hello world'}, conf=conf))['substr']
        u'lo w'

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from builtins import *

from . import processor
from riko.lib.log import Logger

OPTS = {'ftype': 'text', 'ptype': 'int', 'field': 'content'}
DEFAULTS = {'start': 0, 'length': 0}
logger = Logger(__name__).logger


def parser(word, objconf, skip, **kwargs):
    """ Parses the pipe content

    Args:
        word (str): The string to parse
        objconf (obj): The pipe configuration (an Objectify instance)
        skip (bool): Don't parse the content
        kwargs (dict): Keyword arguments

    Kwargs:
        assign (str): Attribute to assign parsed content (default: strtransform)
        feed (dict): The original item

    Returns:
        Tuple(dict, bool): Tuple of (item, skip)

    Examples:
        >>> from riko.lib.utils import Objectify
        >>>
        >>> item = {'content': 'hello world'}
        >>> conf = {'start': 3, 'length': 4}
        >>> kwargs = {'feed': item, 'conf': conf}
        >>> parser(item['content'], Objectify(conf), False, **kwargs)[0]
        u'lo w'
    """
    end = objconf.start + objconf.length if objconf.length else None
    value = kwargs['feed'] if skip else word[objconf.start:end]
    return value, skip


@processor(DEFAULTS, async=True, **OPTS)
def asyncPipe(*args, **kwargs):
    """A processor module that asynchronously returns a substring of a field
    of a feed item.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. May contain the keys 'start' or
            'length'.

            start (int): starting position (default: 0)
            length (int): count of characters to return (default: 0, i.e., all)

        assign (str): Attribute to assign parsed content (default: substr)
        field (str): Item attribute from which to obtain the first number to
            operate on (default: 'content')

    Returns:
       Deferred: twisted.internet.defer.Deferred item with transformed content

    Examples:
        >>> from twisted.internet.task import react
        >>> from riko.twisted import utils as tu
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x)['substr'])
        ...     conf = {'start': '3', 'length': '4'}
        ...     d = asyncPipe({'content': 'hello world'}, conf=conf)
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=tu.FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        lo w
    """
    return parser(*args, **kwargs)


@processor(**OPTS)
def pipe(*args, **kwargs):
    """A processor that returns a substring of a field of a feed item.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. May contain the keys 'start' or
            'length'.

            start (int): starting position (default: 0)
            length (int): count of characters to return (default: 0, i.e., all)

        assign (str): Attribute to assign parsed content (default: substr)
        field (str): Item attribute from which to obtain the first number to
            operate on (default: 'content')

    Yields:
        dict: an item with the substring

    Examples:
        >>> conf = {'start': '3', 'length': '4'}
        >>> next(pipe({'content': 'hello world'}, conf=conf))['substr']
        u'lo w'
        >>> conf = {'start': '3'}
        >>> kwargs = {'conf': conf, 'field': 'title', 'assign': 'result'}
        >>> next(pipe({'title': 'Greetings'}, **kwargs))['result']
        'etings'
    """
    return parser(*args, **kwargs)
