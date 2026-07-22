# vim: sw=4:ts=4:expandtab
"""
Provides functions for querying currency exchange rates

Examples:
    basic usage::

        >>> from riko import get_path
        >>> from riko.modules.exchangerate import pipe
        >>>
        >>> url = get_path('quote.json')
        >>> next(pipe({'content': 'GBP'}, conf={'url': url}))['exchangerate']
        Decimal('1.275201')

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options

"""

from collections.abc import Mapping
from decimal import Decimal
from json import load, loads
from os import getenv
from typing import TypedDict

import pygogo as gogo

from riko import ENCODING
from riko.bado import async_get, async_json, io
from riko.cast import BasicCastType
from riko.types.configs import ExchangeRateObjconf
from riko.types.general import Defaults, Extraction, Opts
from riko.utils import Fetch

from . import processor

EXCHANGE_API = "https://openexchangerates.org/api/latest.json"
PARAMS = {"app_id": getenv("OPEN_EXCHANGE_RATES_ID")}

OPTS: Opts = {"ftype": BasicCastType.TEXT, "field": "content"}
DEFAULTS: Defaults = {
    "currency": "USD",
    "delay": 0,
    "memoize": True,
    "precision": 6,
    "url": EXCHANGE_API,
    "param": PARAMS,
    "encoding": ENCODING,
}

logger = gogo.Gogo(__name__, monolog=True).logger


class RatesJson(TypedDict):
    rates: Mapping[str, str]


def parse_response(rates: Mapping[str, str | float]) -> dict[str, Decimal]:
    if rates:
        resp = {k: Decimal(v) for k, v in rates.items() if v}
    else:
        # TODO: make sure this log shows up in console
        logger.warning("invalid json response:")
        logger.warning(rates)
        resp = {}

    return resp


def get_rate(currency, **rates: Decimal) -> Decimal:
    rate = rates.get(currency, Decimal("nan"))

    if not rate:
        logger.warning(f"rate USD/{currency} not found in rates")

    return rate


def calc_rate(
    from_cur: str, to_cur: str, places=Decimal("0.0001"), **rates: Decimal
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
    base: str, extraction: Extraction, objconf: ExchangeRateObjconf, **kwargs
) -> Decimal:
    """
    Asynchronously parses the pipe content

    Args:
        base (str): The base currency (exchanging from)
        objconf (obj): The pipe configuration (an Objectify instance)
        kwargs (dict): Keyword arguments

    Kwargs:
        assign (str): Attribute to assign parsed content (default: exchangerate)
        stream (dict): The original item

    Returns:
        Awaitable: item

    Examples:
        >>> from riko import get_path
        >>> from riko.bado import run
        >>> from meza.fntools import Objectify
        >>>
        >>> async def main():
        ...     url = get_path('quote.json')
        ...     conf = {'url': url, 'currency': 'USD', 'delay': 0, 'precision': 6}
        ...     item = {'content': 'GBP'}
        ...     objconf = Objectify(conf)
        ...     kwargs = {'stream': item, 'assign': 'content'}
        ...     result = await async_parser(item['content'], None, objconf, **kwargs)
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
        content = await io.async_url_read(objconf.url, delay=objconf.delay)
        rates = loads(content).get("rates", {})

    if rates and not same_currency:
        places = Decimal(10) ** -objconf.precision
        rates = parse_response(rates)
        rate = calc_rate(base, objconf.currency, places=places, **rates)

    return rate


def parser(
    base: str, extraction: Extraction, objconf: ExchangeRateObjconf, **kwargs
) -> Decimal:
    """
    Parses the pipe content

    Args:
        base (str): The base currency (exchanging from)
        objconf (obj): The pipe configuration (an Objectify instance)
        kwargs (dict): Keyword arguments

    Kwargs:
        assign (str): Attribute to assign parsed content (default: exchangerate)
        stream (dict): The original item

    Returns:
        dict: The item

    Examples:
        >>> from riko import get_path
        >>> from meza.fntools import Objectify
        >>>
        >>> url = get_path('quote.json')
        >>> conf = {'url': url, 'currency': 'USD', 'delay': 0, 'precision': 6}
        >>> item = {'content': 'GBP'}
        >>> objconf = Objectify(conf)
        >>> kwargs = {'stream': item, 'assign': 'content'}
        >>> parser(item['content'], None, objconf, **kwargs)
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
async def async_pipe(*args, **kwargs) -> Decimal:
    """
    A processor that asynchronously retrieves the current exchange rate
    for a given currency pair.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. May contain the keys 'url',
            'param', 'currency', 'delay', 'memoize', or 'field'.

            url (str): The exchange rate API url (default:
                http://finance.yahoo.com...)

            param (dict): The API url parameters (default: {'format': 'json'})
            currency: The (exchanging to) currency ISO abbreviation (default:
                USD).

            delay (flt): Amount of time to sleep (in secs) before fetching the
                url. Useful for simulating network latency. Default: 0.

            memoize (bool): Cache the exchange rate API response (default:
                True).

        field (str): Item attribute from which to obtain the string to be
            formatted (default: 'content')

        assign (str): Attribute to assign parsed content (default:
            exchangerate)

    Returns:
        Awaitable: stream of items

    Examples:
        >>> from riko import get_path
        >>> from riko.bado import run
        >>>
        >>> async def main():
        ...     url = get_path('quote.json')
        ...     result = await async_pipe({'content': 'GBP'}, conf={'url': url})
        ...     print(next(result)['exchangerate'])
        >>>
        >>> run(main)
        1.275201

    """
    return await async_parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs) -> Decimal:
    """
    A processor that retrieves the current exchange rate for a given
    currency pair.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. May contain the keys 'url',
            'param', 'currency', 'delay', 'memoize', or 'field'.

            url (str): The exchange rate API url (default:
                http://finance.yahoo.com...)

            param (dict): The API url parameters (default: {'format': 'json'})
            currency: The (exchanging to) currency ISO abbreviation (default:
                USD).

            delay (flt): Amount of time to sleep (in secs) before fetching the
                url. Useful for simulating network latency. Default: 0.

            memoize (bool): Cache the exchange rate API response (default:
                True).

        field (str): Item attribute from which to obtain the string to be
            formatted (default: 'content')

        assign (str): Attribute to assign parsed content (default:
            exchangerate)

    Yields:
        dict: an item of the result

    Examples:
        >>> from riko import get_path
        >>> url = get_path('quote.json')
        >>> conf = {'url': url}
        >>> rate = next(pipe({'content': 'GBP'}, conf=conf))['exchangerate']
        >>> rate
        Decimal('1.275201')
        >>> f'There are {rate:#.2f} GBPs per USD'
        'There are 1.28 GBPs per USD'
        >>> conf = {'url': url, 'currency': 'TZS', 'precision': 3}
        >>> next(pipe({'content': 'USD'}, conf=conf))['exchangerate']
        Decimal('2282.466')
        >>> conf = {'url': url, 'currency': 'XYZ'}
        >>> next(pipe({'content': 'USD'}, conf=conf))['exchangerate']
        Decimal('NaN')

    """
    return parser(*args, **kwargs)
