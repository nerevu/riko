# vim: sw=4:ts=4:expandtab
"""
Provides functions for formatting numbers to currency strings.

Examples:
    basic usage::

        >>> from riko.modules.currencyformat import pipe
        >>>
        >>> next(pipe({'content': '100'}))['currencyformat']
        '$100.00'

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options

"""

from decimal import Decimal

import pygogo as gogo
from babel.numbers import format_currency

from riko.cast import BasicCastType
from riko.types.configs import CurrencyFormatObjconf
from riko.types.general import Defaults, Extraction, Opts

from . import processor

OPTS: Opts = {"ftype": BasicCastType.DECIMAL, "field": "content"}
DEFAULTS: Defaults = {"currency": "USD"}
NaN = Decimal("NaN")

logger = gogo.Gogo(__name__, monolog=True).logger


def parser(
    amount, extraction: Extraction, objconf: CurrencyFormatObjconf, **kwargs
) -> str | Decimal:
    """
    Parsers the pipe content

    Args:
        amount (Decimal): The amount to format
        objconf (obj): The pipe configuration (an Objectify instance)

    Returns:
        dict: The formatted item

    Examples:
        >>> from decimal import Decimal
        >>> from meza.fntools import Objectify
        >>>
        >>> objconf = Objectify({'currency': 'USD'})
        >>> parser(Decimal('10.33'), None, objconf)
        '$10.33'

    """
    if amount is None:
        parsed = NaN
    else:
        try:
            parsed = format_currency(amount, objconf.currency, locale="en_US")
        except ValueError:
            parsed = NaN

    return parsed


@processor(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args, **kwargs) -> str | Decimal:
    """
    A processor module that asynchronously formats a number to a given
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
        >>> async def run(reactor):
        ...     result = await async_pipe({'content': '10.33'})
        ...     print(next(result)['currencyformat'])
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
def pipe(*args, **kwargs) -> str | Decimal:
    """
    A processor module that formats a number to a given currency string.

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
        >>> next(pipe({'content': '10.33'}))['currencyformat']
        '$10.33'
        >>> conf = {'currency': 'GBP'}
        >>> result = next(pipe({'content': '100'}, conf=conf))
        >>> result['currencyformat']
        '£100.00'

    """
    return parser(*args, **kwargs)
