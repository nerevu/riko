# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.exchangerate
~~~~~~~~~~~~~~~~~~~~~~~~~
Provides functions for querying currency exchange rates

Examples:
    basic usage::

        >>> from riko import get_path
        >>> from riko.modules.exchangerate import pipe
        >>>
        >>> url = get_path('quote.json')
        >>> next(pipe({'content': 'GBP'}, conf={'url': url}))['exchangerate']
        Decimal('1.545801')

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

import pygogo as gogo

from json import loads
from decimal import Decimal

from builtins import *  # noqa pylint: disable=unused-import
from ijson import items
from meza.compat import decode

from . import processor
from riko.bado import coroutine, return_value, requests as treq, io
from riko.utils import fetch, get_abspath

EXCHANGE_API_BASE = 'http://finance.yahoo.com/webservice'
EXCHANGE_API = '%s/v1/symbols/allcurrencies/quote' % EXCHANGE_API_BASE
# EXCHANGE_API = 'https://openexchangerates.org/api/latest.json'
# PARAMS = {'app_id': OPEN_EXCHANGE_RATES_APP_ID}

OPTS = {'field': 'content', 'ftype': 'text'}
DEFAULTS = {
    'currency': 'USD',
    'delay': 0,
    'memoize': False,
    'precision': 6,
    'url': EXCHANGE_API,
    'params': {'format': 'json'}}

logger = gogo.Gogo(__name__, monolog=True).logger


def parse_response(json):
    resources = json['list']['resources']
    fields = (r['resource']['fields'] for r in resources)
    return {i['symbol']: Decimal(i['price']) for i in fields if 'price' in i}


def calc_rate(from_cur, to_cur, rates, places=Decimal('0.0001')):
    def get_rate(currency):
        rate = rates.get('%s=X' % currency, Decimal('nan'))

        if not rate:
            logger.warning('rate USD/%s not found in rates' % currency)

        return rate

    if from_cur == to_cur:
        rate = Decimal(1)
    elif to_cur == 'USD':
        rate = get_rate(from_cur)
    else:
        usd_to_given = get_rate(from_cur)
        usd_to_default = get_rate(to_cur)
        rate = usd_to_given / usd_to_default

    return (Decimal(1) / rate).quantize(places)


@coroutine
def async_parser(base, objconf, skip=False, **kwargs):
    """ Asynchronously parses the pipe content

    Args:
        base (str): The base currency (exchanging from)
        objconf (obj): The pipe configuration (an Objectify instance)
        skip (bool): Don't parse the content
        kwargs (dict): Keyword arguments

    Kwargs:
        assign (str): Attribute to assign parsed content (default: exchangerate)
        stream (dict): The original item

    Returns:
        Deferred: twisted.internet.defer.Deferred item

    Examples:
        >>> from riko import get_path
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>> from meza.fntools import Objectify
        >>>
        >>> def run(reactor):
        ...     url = get_path('quote.json')
        ...     conf = {
        ...         'url': url, 'currency': 'USD', 'delay': 0, 'precision': 6}
        ...     item = {'content': 'GBP'}
        ...     objconf = Objectify(conf)
        ...     kwargs = {'stream': item, 'assign': 'content'}
        ...     d = async_parser(item['content'], objconf, **kwargs)
        ...     return d.addCallbacks(print, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        1.545801
    """
    same_currency = base == objconf.currency

    if skip:
        rate = kwargs['stream']
    elif same_currency:
        rate = Decimal(1)
    elif objconf.url.startswith('http'):
        r = yield treq.get(objconf.url, params=objconf.params)
        json = yield treq.json(r)
    else:
        url = get_abspath(objconf.url)
        content = yield io.async_url_read(url, delay=objconf.delay)
        json = loads(decode(content))

    if not (skip or same_currency):
        places = Decimal(10) ** -objconf.precision
        rates = parse_response(json)
        rate = calc_rate(base, objconf.currency, rates, places=places)

    return_value(rate)


def parser(base, objconf, skip=False, **kwargs):
    """ Parses the pipe content

    Args:
        base (str): The base currency (exchanging from)
        objconf (obj): The pipe configuration (an Objectify instance)
        skip (bool): Don't parse the content
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
        >>> parser(item['content'], objconf, **kwargs)
        Decimal('1.545801')
    """
    same_currency = base == objconf.currency

    if skip:
        rate = kwargs['stream']
    elif same_currency:
        rate = Decimal(1)
    else:
        decode = objconf.url.startswith('http')

        with fetch(decode=decode, **objconf) as f:
            json = next(items(f, ''))

    if not (skip or same_currency):
        places = Decimal(10) ** -objconf.precision
        rates = parse_response(json)
        rate = calc_rate(base, objconf.currency, rates, places=places)

    return rate


@processor(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args, **kwargs):
    """A processor that asynchronously retrieves the current exchange rate
    for a given currency pair.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. May contain the keys 'url',
            'params', 'currency', 'delay', 'memoize', or 'field'.

            url (str): The exchange rate API url (default:
                http://finance.yahoo.com...)

            params (dict): The API url parameters (default: {'format': 'json'})
            currency: The (exchanging to) currency ISO abbreviation (default:
                USD).

            delay (flt): Amount of time to sleep (in secs) before fetching the
                url. Useful for simulating network latency. Default: 0.

            memoize (bool): Cache the exchange rate API response (default:
                False).

        field (str): Item attribute from which to obtain the string to be
            formatted (default: 'content')

        assign (str): Attribute to assign parsed content (default:
            exchangerate)

    Returns:
        dict: twisted.internet.defer.Deferred stream of items

    Examples:
        >>> from riko import get_path
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x)['exchangerate'])
        ...     url = get_path('quote.json')
        ...     d = async_pipe({'content': 'GBP'}, conf={'url': url})
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        1.545801
    """
    return async_parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs):
    """A processor that retrieves the current exchange rate for a given
    currency pair.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. May contain the keys 'url',
            'params', 'currency', 'delay', 'memoize', or 'field'.

            url (str): The exchange rate API url (default:
                http://finance.yahoo.com...)

            params (dict): The API url parameters (default: {'format': 'json'})
            currency: The (exchanging to) currency ISO abbreviation (default:
                USD).

            delay (flt): Amount of time to sleep (in secs) before fetching the
                url. Useful for simulating network latency. Default: 0.

            memoize (bool): Cache the exchange rate API response (default:
                False).

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
        Decimal('1.545801')
        >>> msg = 'There are 1.55 GBPs per USD'
        >>> 'There are %#.2f GBPs per USD' % rate == msg
        True
        >>> conf = {'url': url, 'currency': 'TZS', 'precision': 3}
        >>> next(pipe({'content': 'USD'}, conf=conf))['exchangerate']
        Decimal('1825.850')
        >>> conf = {'url': url, 'currency': 'XYZ'}
        >>> next(pipe({'content': 'USD'}, conf=conf))['exchangerate']
        Decimal('NaN')
    """
    return parser(*args, **kwargs)
