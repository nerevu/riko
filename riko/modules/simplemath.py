# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.simplemath
~~~~~~~~~~~~~~~~~~~~~~~
Provides functions for performing simple mathematical operations, e.g.,
addition, subtraction, multiplication, division, modulo, averages, etc.

Examples:
    basic usage::

        >>> from decimal import Decimal
        >>> from riko.modules.simplemath import pipe
        >>>
        >>> conf = {'op': 'divide', 'other': '5'}
        >>> next(pipe({'content': '10'}, conf=conf))['simplemath']
        Decimal('2')

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

import operator

from builtins import *

from . import processor
import pygogo as gogo

OPTS = {'ftype': 'decimal', 'ptype': 'decimal', 'field': 'content'}
DEFAULTS = {}
logger = gogo.Gogo(__name__, monolog=True).logger


def mean(*nums):
    try:
        return sum(nums) / len(nums)
    except ZeroDivisionError:
        return 0.0

OPS = {
    'add': operator.add,
    'subtract': operator.sub,
    'multiply': operator.mul,
    'mean': mean,
    'divide': operator.truediv,
    'floor': operator.floordiv,
    'modulo': operator.mod,
    'power': operator.pow,
}


def parser(num, objconf, skip, **kwargs):
    """ Parsers the pipe content

    Args:
        num (Decimal): The first number to operate on
        objconf (obj): The pipe configuration (an Objectify instance)
        skip (bool): Don't parse the content

    Returns:
        Tuple(dict, bool): Tuple of (the formatted , skip)

    Examples:
        >>> from riko.lib.utils import Objectify
        >>> conf = {'op': 'divide', 'other': 4}
        >>> objconf = Objectify(conf)
        >>> parser(10, objconf, False, conf=conf)[0]
        2.5
    """
    operation = OPS[kwargs['conf']['op']]
    parsed = kwargs['stream'] if skip else operation(num, objconf.other)
    return parsed, skip


@processor(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args, **kwargs):
    """A processor module that asynchronously performs basic arithmetic, such
    as addition and subtraction.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the keys 'other'
            and 'op'.

            other (number): The second number to operate on.
            op (str): The math operation. Must be one of 'addition',
                'substraction', 'multiplication', 'division', 'modulo',
                'floor', 'power', or 'mean'.

        assign (str): Attribute to assign parsed content (default: simplemath)
        field (str): Item attribute from which to obtain the first number to
            operate on (default: 'content')

    Returns:
        Deferred: twisted.internet.defer.Deferred item with formatted currency

    Examples:
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x)['simplemath'])
        ...     conf = {'op': 'divide', 'other': '5'}
        ...     d = async_pipe({'content': '10'}, conf=conf)
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        2
    """
    return parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs):
    """A processor module that performs basic arithmetic, such as addition and
    subtraction.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the keys 'other'
            and 'op'.

            other (number): The second number to operate on.
            op (str): The math operation. Must be one of 'addition',
                'substraction', 'multiplication', 'division', 'modulo',
                'floor', 'power', or 'mean'.

        assign (str): Attribute to assign parsed content (default: simplemath)
        field (str): Item attribute from which to obtain the first number to
            operate on (default: 'content')

    Returns:
        dict: an item with math result

    Examples:
        >>> from decimal import Decimal
        >>> conf = {'op': 'divide', 'other': '5'}
        >>> next(pipe({'content': '10'}, conf=conf))['simplemath']
        Decimal('2')
        >>> kwargs = {'conf': conf, 'field': 'num', 'assign': 'result'}
        >>> next(pipe({'num': '10'}, **kwargs))['result']
        Decimal('2')
    """
    return parser(*args, **kwargs)
