# vim: sw=4:ts=4:expandtab
"""
Formats a number as a currency string.

The currency's own conventions decide the symbol and the number of decimal
places, so ``100`` is ``$100.00`` in USD but ``¥100`` in JPY.

Examples:
    Basic usage::

        >>> from riko.modules.currencyformat import pipe
        >>>
        >>> next(pipe({"content": "100"}))["currencyformat"]
        '$100.00'

Attributes:
    OPTS: Processor wrapper options.
    DEFAULTS: Default processor configuration.

"""

from decimal import Decimal
from logging import Logger
from typing import Any, cast

import pygogo as gogo
from babel.numbers import format_currency

from riko.cast import BasicCastType
from riko.currencies import CURRENCY_CODES
from riko.modules._prepare import require_conf
from riko.types._configs import CurrencyFormatObjconf
from riko.types._options import Defaults, Opts

from . import processor

OPTS: Opts = {"ftype": BasicCastType.DECIMAL, "field": "content"}
DEFAULTS: Defaults = {"currency": "USD", "clean": False}
logger: Logger = gogo.Gogo(__name__, monolog=True).logger


def parser(
    amount: Decimal | None,
    extraction: object,
    objconf: CurrencyFormatObjconf,
    **kwargs: object,
) -> str:
    """
    Formats ``amount`` in the configured currency.

    Args:
        amount: The amount to format.
        extraction: The extracted conf value. Unused.
        objconf: The pipe configuration, containing `currency`.

    Returns:
        The formatted amount, or ``""`` when there is no amount to format.

    Examples:
        >>> from decimal import Decimal
        >>> from meza.fntools import Objectify
        >>>
        >>> objconf = Objectify({"currency": "USD"})
        >>> parser(Decimal("10.33"), None, objconf)
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
    Asynchronously formats a number as a currency string.

    Both iterator and iterable sources are mapped over. See the FAQ's "How does a
    processor map over items?".

    Args:
        item (Item | Items): The entry, or stream of entries, to process.

        conf (dict): The pipe configuration.

            currency (str): ISO code of the currency to format in (default: "USD").

            locale (str): Currency locale identifier (default: the currency code locale
                as mapped in CURRENCY_CODES, or (if not locale exists) the system
                currency locale).

            clean (bool): Replace the non-breaking space with a space (default: False).

        context (Context): the execution context

    Kwargs:
        field (str): Item attribute to format (default: "content").

        assign (str): Field the text is assigned to. Ignored when ``emit`` is
            True (default: "currencyformat").

        emit (bool): Whether to emit the text in place of the item rather than
            assign it. Overrides ``assign`` (default: False).

    Yields:
        - merged ``{Item, <assign>: <text>}`` when ``emit`` is False and item is
          given (default)
        - ``{<assign>: <text>}`` when ``emit`` is False and no item given
        - ``<text>`` when ``emit`` is True

    Notes:
        A field that is missing or not numeric yields ``""``.

        Amounts are laid out US style whatever the currency, and an unrecognized
        ISO code is used verbatim in place of a symbol.

    Examples:
        >>> from riko import run
        >>>
        >>> async def main():
        ...     result = await async_pipe({"content": "10.33"})
        ...     print(next(result)["currencyformat"])
        >>>
        >>> run(main)
        $10.33

    """
    return parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> str:
    """
    Formats a number as a currency string.

    Both iterator and iterable sources are mapped over. See the FAQ's "How does a
    processor map over items?".

    Args:
        item (Item | Items): The entry, or stream of entries, to process.

        conf (dict): The pipe configuration.

            currency (str): ISO code of the currency to format in (default: "USD").

            locale (str): Currency locale identifier (default: the currency code locale
                as mapped in CURRENCY_CODES, or (if not locale exists) the system
                currency locale).

            clean (bool): Replace the non-breaking space with a space (default: False).

        context (Context): the execution context

    Kwargs:
        field (str): Item attribute to format (default: "content").

        assign (str): Field the text is assigned to. Ignored when ``emit`` is
            True (default: "currencyformat").

        emit (bool): Whether to emit the text in place of the item rather than
            assign it. Overrides ``assign`` (default: False).

    Yields:
        - merged ``{Item, <assign>: <text>}`` when ``emit`` is False and item is
          given (default)
        - ``{<assign>: <text>}`` when ``emit`` is False and no item given
        - ``<text>`` when ``emit`` is True

    Notes:
        A field that is missing or not numeric yields ``""``.

        Amounts are laid out US style whatever the currency, and an unrecognized
        ISO code is used verbatim in place of a symbol.

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
