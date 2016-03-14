# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
pipe2py.modules.pipecurrencyformat
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Provides functions for formatting numbers to currency strings.

Examples:
    basic usage::

        >>> from pipe2py.modules.pipecurrencyformat import pipe
        >>> pipe({'content': '100'}).next()['content']
        u'$100.00'

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""

from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from babel.numbers import format_currency
from . import processor
from pipe2py.lib.log import Logger

OPTS = {'ftype': 'decimal'}
DEFAULTS = {'currency': 'USD', 'field': 'content'}
logger = Logger(__name__).logger


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
        >>> from pipe2py.lib.utils import Objectify
        >>>
        >>> amount = Decimal('10.33')
        >>> objconf = Objectify({'currency': 'USD'})
        >>> parser(amount, objconf, False)[0]
        u'$10.33'
    """
    if skip:
        parsed = kwargs['feed']
    else:
        parsed = format_currency(amount, objconf.currency)

    return parsed, skip


@processor(DEFAULTS, async=True, **OPTS)
def asyncPipe(*args, **kwargs):
    """A processor module that asynchronously formats a number to a given
    currency string.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. May contain the keys 'currency',
            'assign', or 'field'.

            currency (str): The currency ISO abbreviation (default: USD).
            assign (str): Attribute to assign parsed content (default: content)
            field (str): Item attribute from which to obtain the string to be
                formatted (default: 'content')

    Returns:
        Deferred: twisted.internet.defer.Deferred item with formatted currency

    Examples:
        >>> from datetime import date
        >>> from twisted.internet.task import react
        >>> from pipe2py.twisted import utils as tu
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(x.next()['content'])
        ...     d = asyncPipe({'content': '10.33'})
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=tu.FakeReactor())
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
        conf (dict): The pipe configuration. May contain the keys 'currency',
            'assign', or 'field'.

            currency (str): The currency ISO abbreviation (default: USD).
            assign (str): Attribute to assign parsed content (default: content)
            field (str): Item attribute from which to obtain the string to be
                formatted (default: 'content')

    Returns:
        dict: an item with formatted date string

    Examples:
        >>> pipe({'content': '10.33'}).next()['content']
        u'$10.33'
        >>> conf = {'currency': 'GBP'}
        >>> pipe({'content': '100'}, conf=conf).next()['content'] == '£100.00'
        True
    """
    return parser(*args, **kwargs)

