# vim: sw=4:ts=4:expandtab
"""
Converts a currency field into an exchange rate.

Looks up the rate from the source currency named in the field to ``currency``,
via the Open Exchange Rates API. Live use needs an app id in the
``OPEN_EXCHANGE_RATES_ID`` environment variable; pointing ``url`` at a local
json file works without one.

Examples:
    Basic usage::

        >>> from riko import get_path
        >>> from riko.modules.exchangerate import pipe
        >>>
        >>> url = get_path("quote.json")
        >>> next(pipe({"content": "GBP"}, conf={"url": url}))["exchangerate"]
        Decimal('1.275201')

Attributes:
    EXCHANGE_API: Default rates endpoint.
    PARAMS: Query parameters carrying the ``OPEN_EXCHANGE_RATES_ID`` app id.
    OPTS: Processor wrapper options.
    DEFAULTS: Default processor configuration.

"""

from collections.abc import Mapping
from decimal import Decimal
from json import load, loads
from logging import Logger
from os import getenv
from typing import Any, TypedDict, cast

import pygogo as gogo

from riko._constants import ENCODING
from riko._io import Fetch
from riko.bado._util import async_json
from riko.bado.io import async_get, async_url_read
from riko.cast import BasicCastType
from riko.types._configs import ExchangeRateObjconf
from riko.types._options import Defaults, Opts

from . import processor

EXCHANGE_API = "https://openexchangerates.org/api/latest.json"
PARAMS = {"app_id": getenv("OPEN_EXCHANGE_RATES_ID")}

OPTS: Opts = {"ftype": BasicCastType.TEXT, "field": "content"}
DEFAULTS: Defaults = {
    "currency": "USD",
    "memoize": True,
    "precision": 6,
    "url": EXCHANGE_API,
    "param": PARAMS,
    "encoding": ENCODING,
}

logger: Logger = gogo.Gogo(__name__, monolog=True).logger


class RatesJson(TypedDict):
    rates: Mapping[str, str]


def parse_response(rates: Mapping[str, str | float]) -> dict[str, Decimal]:
    if rates:
        resp = {k: Decimal(v) for k, v in rates.items() if v}
    else:
        logger.warning("invalid json response:")
        logger.warning(rates)
        resp = {}

    return resp


def get_rate(currency: str, **rates: Decimal) -> Decimal:
    rate = rates.get(currency, Decimal("nan"))

    if not rate:
        logger.warning(f"rate USD/{currency} not found in rates")

    return rate


def calc_rate(
    from_cur: str, to_cur: str, places: Decimal = Decimal("0.0001"), **rates: Decimal
) -> Decimal:
    if from_cur == to_cur:
        rate = Decimal(1)
    elif to_cur == "USD":
        rate = get_rate(from_cur, **rates)
    else:
        usd_to_given = get_rate(from_cur, **rates)
        usd_to_default = get_rate(to_cur, **rates)
        rate = usd_to_given / usd_to_default

    return (Decimal(1) / rate).quantize(places)


async def async_parser(
    base: str, extraction: object, objconf: ExchangeRateObjconf, **kwargs: object
) -> Decimal:
    """
    Asynchronously looks up the rate from ``base`` to the target currency.

    Args:
        base: The currency being exchanged from.
        extraction: The extracted conf value. Unused.
        objconf: The pipe configuration, containing `url`, `param`, `currency`
            and `precision`.

    Returns:
        The rate, ``1`` when both currencies match, or ``Decimal("NaN")`` when
        the target is absent from the response.

    Examples:
        >>> from riko import get_path, run
        >>> from meza.fntools import Objectify
        >>>
        >>> async def main():
        ...     url = get_path("quote.json")
        ...     conf = {"url": url, "currency": "USD", "precision": 6}
        ...     item = {"content": "GBP"}
        ...     objconf = Objectify(conf)
        ...     kwargs = {"stream": item, "assign": "content"}
        ...     result = await async_parser(item["content"], None, objconf, **kwargs)
        ...     print(result)
        >>>
        >>> run(main)
        1.275201

    """
    same_currency = base == objconf.currency
    rates = None
    rate = Decimal(0)

    if same_currency:
        rate = Decimal(1)
    elif objconf.url.startswith("http"):
        r = await async_get(objconf.url, params=objconf.param)
        rates = await async_json(r)
    else:
        content = await async_url_read(objconf.url)
        rates = cast(dict[str, Any], loads(content).get("rates", {}))

    if rates and not same_currency:
        places = Decimal(10) ** -objconf.precision
        rates = parse_response(rates)
        rate = calc_rate(base, objconf.currency, places=places, **rates)

    return rate


def parser(
    base: str, extraction: object, objconf: ExchangeRateObjconf, **kwargs: object
) -> Decimal:
    """
    Looks up the rate from ``base`` to the target currency.

    Args:
        base: The currency being exchanged from.
        extraction: The extracted conf value. Unused.
        objconf: The pipe configuration, containing `url`, `param`, `currency`
            and `precision`.

    Returns:
        The rate, ``1`` when both currencies match, or ``Decimal("NaN")`` when
        the target is absent from the response.

    Examples:
        >>> from riko import get_path
        >>> from meza.fntools import Objectify
        >>>
        >>> url = get_path("quote.json")
        >>> conf = {"url": url, "currency": "USD", "precision": 6}
        >>> item = {"content": "GBP"}
        >>> objconf = Objectify(conf)
        >>> kwargs = {"stream": item, "assign": "content"}
        >>> parser(item["content"], None, objconf, **kwargs)
        Decimal('1.275201')

    """
    rates = None
    rate = Decimal(0)

    if base == objconf.currency:
        rate = Decimal(1)
    else:
        with Fetch(objconf.url, encoding=objconf.encoding, params=objconf.param) as f:
            json = load(f)

            if rates := json.get("rates", {}):
                places = Decimal(10) ** -objconf.precision
                rates = parse_response(rates)
                rate = calc_rate(base, objconf.currency, places=places, **rates)

    return rate


@processor(DEFAULTS, isasync=True, **OPTS)
async def async_pipe(*args: Any, **kwargs: object) -> Decimal:
    """
    Asynchronously retrieves the exchange rate for a currency pair.

    Args:
        item (Item | Items): The entry, or stream of entries, to process.

        conf (dict): The pipe configuration.

            url (str): The rates endpoint, or a local json file
                (default: the Open Exchange Rates latest.json endpoint).

            param (dict): Query parameters for the endpoint (default: the
                ``OPEN_EXCHANGE_RATES_ID`` app id).

            currency (str): ISO code of the currency being exchanged *to*
                (default: "USD").

            precision (int): Decimal places to round the rate to (default: 6).
            memoize (bool): Whether to cache the API response (default: True).
            encoding (str): Response encoding (default: "utf-8").

        context (Context): the execution context

    Kwargs:
        field (str): Item attribute holding the ISO code of the currency being
            exchanged *from* (default: "content").

        assign (str): Field the rate is assigned to. Ignored when ``emit`` is
            True (default: "exchangerate").

        emit (bool): Whether to emit the rate in place of the item rather than
            assign it. Overrides ``assign`` (default: False).

    Yields:
        - merged ``{Item, <assign>: <rate>}`` when ``emit`` is False and item
          is given (default)
        - ``{<assign>: <rate>}`` when ``emit`` is False and no item given
        - ``<rate>`` when ``emit`` is True

    Notes:
        A currency missing from the response logs a warning and yields
        ``Decimal("NaN")`` rather than raising.

    Examples:
        >>> from riko import get_path, run
        >>>
        >>> async def main():
        ...     url = get_path("quote.json")
        ...     result = await async_pipe({"content": "GBP"}, conf={"url": url})
        ...     print(next(result)["exchangerate"])
        >>>
        >>> run(main)
        1.275201

    """
    return await async_parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> Decimal:
    """
    Retrieves the exchange rate for a currency pair.

    Args:
        item (Item | Items): The entry, or stream of entries, to process.

        conf (dict): The pipe configuration.

            url (str): The rates endpoint, or a local json file
                (default: the Open Exchange Rates latest.json endpoint).

            param (dict): Query parameters for the endpoint (default: the
                ``OPEN_EXCHANGE_RATES_ID`` app id).

            currency (str): ISO code of the currency being exchanged *to*
                (default: "USD").

            precision (int): Decimal places to round the rate to (default: 6).
            memoize (bool): Whether to cache the API response (default: True).
            encoding (str): Response encoding (default: "utf-8").

        context (Context): the execution context

    Kwargs:
        field (str): Item attribute holding the ISO code of the currency being
            exchanged *from* (default: "content").

        assign (str): Field the rate is assigned to. Ignored when ``emit`` is
            True (default: "exchangerate").

        emit (bool): Whether to emit the rate in place of the item rather than
            assign it. Overrides ``assign`` (default: False).

    Yields:
        - merged ``{Item, <assign>: <rate>}`` when ``emit`` is False and item
          is given (default)
        - ``{<assign>: <rate>}`` when ``emit`` is False and no item given
        - ``<rate>`` when ``emit`` is True

    Notes:
        A currency missing from the response logs a warning and yields
        ``Decimal("NaN")`` rather than raising.

    Examples:
        >>> from riko import get_path
        >>>
        >>> url = get_path("quote.json")
        >>> conf = {"url": url}
        >>> rate = next(pipe({"content": "GBP"}, conf=conf))["exchangerate"]
        >>> rate
        Decimal('1.275201')
        >>> f"There are {rate:#.2f} GBPs per USD"
        'There are 1.28 GBPs per USD'
        >>> conf = {"url": url, "currency": "TZS", "precision": 3}
        >>> next(pipe({"content": "USD"}, conf=conf))["exchangerate"]
        Decimal('2282.466')
        >>> conf = {"url": url, "currency": "XYZ"}
        >>> next(pipe({"content": "USD"}, conf=conf))["exchangerate"]
        Decimal('NaN')

    """
    return parser(*args, **kwargs)
