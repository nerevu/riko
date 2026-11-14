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
    OPTS: Processor decoration options.
    DEFAULTS: Default processor configuration.

"""

from __future__ import annotations

from contextlib import suppress
from decimal import Decimal, InvalidOperation
from json import load, loads
from os import getenv
from typing import TYPE_CHECKING, Any

from riko.bado._util import async_get, async_json
from riko.base._config import ENCODING, settings
from riko.base._funcutils import map_values
from riko.base._guards import is_mapping
from riko.base._logging import get_logger
from riko.base._paths import is_http_url
from riko.io._async import async_url_read
from riko.io._sync import Fetch
from riko.types._enums import BasicCastType

from ._decorators import processor

if TYPE_CHECKING:
    from collections.abc import Mapping
    from logging import Logger

    from riko.coercion._configs import ExchangeRateObjconf
    from riko.types._options import DecorationOptions, Defaults

logger: Logger = get_logger(__name__)

type _ParsedRate = tuple[Decimal, object]

EXCHANGE_API = settings.exchange_api
PARAMS = {"app_id": getenv("OPEN_EXCHANGE_RATES_ID")}
OPTS: DecorationOptions = {"ftype": BasicCastType.TEXT, "field": "content"}

DEFAULTS: Defaults = {
    "currency": "USD",
    "memoize": True,
    "precision": 6,
    "url": EXCHANGE_API,
    "param": PARAMS,
    "encoding": ENCODING,
    "verbose": False,
}


def _parse_rate(value: object, verbose: bool = False) -> _ParsedRate:
    """Parses a currency rate, a number or numeric string, into a ``Decimal``."""
    rate, msg = Decimal("nan"), f"invalid rate: {value!r}"

    if not isinstance(value, bool):
        with suppress(TypeError, ValueError, InvalidOperation):
            rate = Decimal(value)  # pyright: ignore[reportArgumentType]

    if verbose and rate.is_nan():
        logger.warning(msg)

    return rate, value


def build_rates(*, verbose: bool = False, **rates: object) -> dict[str, _ParsedRate]:
    """
    Builds the parsed rates of a rates response.

    Kwargs:

        verbose: Whether to log a warning for each unparseable rate.
        rates (object): The raw rate of each currency, keyed by currency code.

    Returns:

        Each currency's ``Decimal`` rate (``NaN`` when unparseable) paired with
        its raw value. Excludes ``None`` rates. They read as absent.

    """
    return map_values(_parse_rate, rates, non_null=True, verbose=verbose)


def require_rates(document: object) -> Mapping[str, object]:
    """
    Requires the ``rates`` mapping of a rates response document.

    Args:

        document: The decoded rates response.

    Returns:

        The response's non-empty ``rates`` mapping of currency to raw rate.

    Raises:

        ValueError: If the document has no ``rates`` mapping or an empty one. The
            message carries the response's own error ``description`` (or ``message``)
            when it has one.

    """
    found: Mapping[str, object] = document if is_mapping(document) else {}

    if not (is_mapping(rates := found.get("rates")) and rates):
        detail = found.get("description", found.get("message"))
        reason = "" if detail is None else f": {detail}"
        raise ValueError(f"rates response has no or an empty 'rates' mapping{reason}")

    return rates


def get_rate(currency: str, **rates: _ParsedRate) -> Decimal:
    rate_text = f"USD/{currency} rate"
    rate, raw = rates.get(currency, (None, None))

    if rate is None:
        logger.warning(f"{rate_text} not found in rates")
        rate = Decimal("NaN")
    elif rate.is_nan():
        raise ValueError(f"invalid {rate_text}: {raw!r}")
    elif not rate.is_finite():
        raise ValueError(f"{rate_text} must be finite: got {raw!r}")
    elif rate <= 0:
        raise ValueError(f"{rate_text} must be positive: got {raw!r}")

    return rate


def get_cross_rate(
    from_cur: str,
    to_cur: str,
    places: Decimal = Decimal("0.0001"),
    **rates: _ParsedRate,
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

        objconf: The module configuration: `url`, `param`, `currency`, `precision`,
            `user_agent`, and `verbose`.

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
    _rates, rate = None, Decimal("nan")

    if same_currency:
        rate = Decimal(1)
    elif is_http_url(objconf.url):
        r = await async_get(
            objconf.url, params=objconf.param, user_agent=objconf.user_agent
        )
        _rates = require_rates(await async_json(r))
    else:
        content = await async_url_read(
            objconf.url, encoding=objconf.encoding, user_agent=objconf.user_agent
        )
        _rates = require_rates(loads(content))

    if _rates is not None:
        places = Decimal(10) ** -objconf.precision
        rates = build_rates(verbose=objconf.verbose, **_rates)
        rate = get_cross_rate(base, objconf.currency, places=places, **rates)

    return rate


def parser(
    base: str, extraction: object, objconf: ExchangeRateObjconf, **kwargs: object
) -> Decimal:
    """
    Looks up the rate from ``base`` to the target currency.

    Args:

        base: The currency being exchanged from.

        extraction: The extracted conf value. Unused.

        objconf: The module configuration: `url`, `param`, `currency`, `precision`,
            `user_agent`, and `verbose`.

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
    rate = Decimal("nan")

    if base == objconf.currency:
        rate = Decimal(1)
    else:
        with Fetch(
            objconf.url,
            encoding=objconf.encoding,
            params=objconf.param,
            user_agent=objconf.user_agent,
        ) as f:
            _rates = require_rates(load(f))
            places = Decimal(10) ** -objconf.precision
            rates = build_rates(verbose=objconf.verbose, **_rates)
            rate = get_cross_rate(base, objconf.currency, places=places, **rates)

    return rate


@processor(DEFAULTS, isasync=True, **OPTS)
async def async_pipe(*args: Any, **kwargs: object) -> Decimal:
    """
    Asynchronously retrieves the exchange rate for a currency pair.

    Args:

        item (Item | Items): The entry, or stream of entries, to process.

        conf (dict): The module configuration.

            url (str): The rates endpoint, or a local json file
                (default: the Open Exchange Rates latest.json endpoint).

            param (dict): Query parameters for the endpoint (default: the
                ``OPEN_EXCHANGE_RATES_ID`` app id).

            currency (str): ISO code of the currency being exchanged *to*
                (default: "USD").

            precision (int): Decimal places to round the rate to (default: 6).
            memoize (bool): Whether to cache the API response (default: True).
            encoding (str): Response encoding (default: "utf-8").

            verbose (bool): Whether to log a warning for each rate in the response
                that isn't a number. Any currency's bad rate warns, not just the
                pair's (default: False).

            user_agent (str): HTTP ``User-Agent`` to send. ``UserAgent.DESKTOP``,
                ``MOBILE``, or ``RANDOM`` pick a common browser agent of that kind per
                request (default: "riko/<version>").

        context (Context): the run environment

    Kwargs:

        field (str): Item field holding the ISO code of the currency being
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
        >>> conf = {"url": get_path("quote.json")}
        >>> stream = async_pipe({"content": "GBP"}, conf=conf)
        >>> run(anext, stream)["exchangerate"]
        Decimal('1.275201')

    """
    return await async_parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> Decimal:
    """
    Retrieves the exchange rate for a currency pair.

    Args:

        item (Item | Items): The entry, or stream of entries, to process.

        conf (dict): The module configuration.

            url (str): The rates endpoint, or a local json file
                (default: the Open Exchange Rates latest.json endpoint).

            param (dict): Query parameters for the endpoint (default: the
                ``OPEN_EXCHANGE_RATES_ID`` app id).

            currency (str): ISO code of the currency being exchanged *to*
                (default: "USD").

            precision (int): Decimal places to round the rate to (default: 6).
            memoize (bool): Whether to cache the API response (default: True).
            encoding (str): Response encoding (default: "utf-8").

            verbose (bool): Whether to log a warning for each rate in the response
                that isn't a number. Any currency's bad rate warns, not just the
                pair's (default: False).

            user_agent (str): HTTP ``User-Agent`` to send. ``UserAgent.DESKTOP``,
                ``MOBILE``, or ``RANDOM`` pick a common browser agent of that kind per
                request (default: "riko/<version>").

        context (Context): the run environment

    Kwargs:

        field (str): Item field holding the ISO code of the currency being
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
        >>> next(pipe({"content": "GBP"}, conf=conf))["exchangerate"]
        Decimal('1.275201')
        >>> conf = {"url": url, "currency": "TZS", "precision": 3}
        >>> next(pipe({"content": "USD"}, conf=conf))["exchangerate"]
        Decimal('2282.466')
        >>> conf = {"url": url, "currency": "XYZ"}
        >>> next(pipe({"content": "USD"}, conf=conf))["exchangerate"]
        Decimal('NaN')

    """
    return parser(*args, **kwargs)
