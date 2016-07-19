# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.currencyformat
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Provides functions for formatting numbers to currency strings.

Examples:
    basic usage::

        >>> from riko.modules.currencyformat import pipe
        >>> next(pipe({'content': '100'}))['currencyformat'] == '$100.00'
        True

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from builtins import *
from babel.numbers import format_currency

from . import processor
import pygogo as gogo

OPTS = {'ftype': 'decimal', 'field': 'content'}
DEFAULTS = {'currency': 'USD'}
logger = gogo.Gogo(__name__, monolog=True).logger


def parser(amount, objconf, skip, **kwargs):
    """ Parsers the pipe content

    Args:
        amount (Decimal): The amount to format
        objconf (obj): The pipe configuration (an Objectify instance)
        skip (bool): Don't parse the content

    Returns:
        Tuple(dict, bool): Tuple of (the formatted , skip)

    Examples:
        >>> from decimal import Decimal
        >>> from riko.lib.utils import Objectify
        >>>
        >>> amount = Decimal('10.33')
        >>> objconf = Objectify({'currency': 'USD'})
        >>> parser(amount, objconf, False)[0] == '$10.33'
        True
    """
    if skip:
        parsed = kwargs['stream']
    else:
        parsed = format_currency(amount, objconf.currency)

    return parsed, skip


@processor(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args, **kwargs):
    """A processor module that asynchronously formats a number to a given
    currency string.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. May contain the key 'currency'.

            currency (str): The currency ISO abbreviation (default: USD).

        assign (str): Attribute to assign parsed content (default:
            currencyformat)

        field (str): Item attribute from which to obtain the string to be
            formatted (default: 'content')

    Returns:
        Deferred: twisted.internet.defer.Deferred item with formatted currency

    Examples:
        >>> from datetime import date
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x)['currencyformat'])
        ...     d = async_pipe({'content': '10.33'})
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        $10.33
    """
    return parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs):
    """A processor module that formats a number to a given currency string.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. May contain the key 'currency'.

            currency (str): The currency ISO abbreviation (default: USD).

        assign (str): Attribute to assign parsed content (default:
            currencyformat)

        field (str): Item attribute from which to obtain the string to be
            formatted (default: 'content')

    Returns:
        dict: an item with formatted date string

    Examples:
        >>> next(pipe({'content': '10.33'}))['currencyformat'] == '$10.33'
        True
        >>> conf = {'currency': 'GBP'}
        >>> result = next(pipe({'content': '100'}, conf=conf))
        >>> result['currencyformat'] == '£100.00'
        True
    """
    return parser(*args, **kwargs)
