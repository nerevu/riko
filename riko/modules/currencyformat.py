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
from logging import Logger
from typing import Any, cast

import pygogo as gogo
from babel.numbers import format_currency

from riko.cast import BasicCastType
from riko.currencies import CURRENCY_CODES
from riko.modules._prepare import require_conf
from riko.types.configs import CurrencyFormatObjconf
from riko.types.general import Defaults, Extraction, Opts

from . import processor

OPTS: Opts = {"ftype": BasicCastType.DECIMAL, "field": "content"}
DEFAULTS: Defaults = {"currency": "USD", "clean": False}
logger: Logger = gogo.Gogo(__name__, monolog=True).logger


def parser(
    amount: Decimal | None,
    extraction: Extraction,
    objconf: CurrencyFormatObjconf,
    **kwargs: object,
) -> str:
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
    if amount is None or amount.is_nan():
        parsed = ""
    else:
        currency: str = require_conf(objconf, "currency", "currencyformat")
        currency_code = CURRENCY_CODES.get(currency, cast(dict[str, str], {}))
        locale = objconf.locale or currency_code.get("locale", "")

        try:
            parsed = format_currency(amount, objconf.currency, locale=locale)
        except ValueError:
            parsed = ""
        else:
            # non-breaking space to space
            parsed = parsed.replace("\xa0", " ") if objconf.clean else parsed

    return parsed


@processor(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args: Any, **kwargs: object) -> str:
    """
    A processor module that asynchronously formats a number to a given
    currency string.

    Args:
        item (dict or Iter[dict]): The entry, or stream of entries, to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. May contain the key 'currency'.

            currency (str): The currency ISO abbreviation (default: USD).

        assign (str): Attribute to assign parsed content (default:
            currencyformat)

        field (str): Item attribute from which to obtain the string to be
            formatted (default: 'content')

    Returns:
        Awaitable: item with formatted currency

    Examples:
        >>> from datetime import date
        >>> from riko import run
        >>>
        >>> async def main():
        ...     result = await async_pipe({'content': '10.33'})
        ...     print(next(result)['currencyformat'])
        >>>
        >>> run(main)
        $10.33

    """
    return parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> str:
    """
    A processor module that formats a number to a given currency string.

    Args:
        item (dict or Iter[dict]): The entry, or stream of entries, to process
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
        >>> next(pipe({"content": "1000.33"}))["currencyformat"]
        '$1,000.33'
        >>> conf = {"currency": "GBP"}
        >>> next(pipe({"content": "1000.33"}, conf=conf))["currencyformat"]
        '£1,000.33'
        >>> conf = {"currency": "EUR", "clean": True}
        >>> next(pipe({"content": "1000.33"}, conf=conf))["currencyformat"]
        '1.000,33 €'
        >>> next(pipe({"content": "bogus"}))["currencyformat"]
        ''
        >>> next(pipe({}))["currencyformat"]
        ''

    """
    return parser(*args, **kwargs)
