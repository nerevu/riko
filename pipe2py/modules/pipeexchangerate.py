# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
pipe2py.modules.pipeexchangerate
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Provides functions for querying currency exchange rates

Examples:
    basic usage::

        >>> from pipe2py import get_url
        >>> from pipe2py.modules.pipeexchangerate import pipe
        >>>
        >>> url = get_url('quote.json')
        >>> pipe({'base': 'GBP'}, conf={'url': url}).next()['content']
        Decimal('1.545801')

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""

from __future__ import (
    absolute_import, division, print_function, unicode_literals)

import requests
import treq

from json import loads
from urllib2 import urlopen
from decimal import Decimal

from twisted.internet.defer import inlineCallbacks, returnValue
from . import processor
from pipe2py.lib import utils
from pipe2py.lib.log import Logger
from pipe2py.twisted import utils as tu

EXCHANGE_API_BASE = 'http://finance.yahoo.com/webservice'
EXCHANGE_API = '%s/v1/symbols/allcurrencies/quote' % EXCHANGE_API_BASE

OPTS = {'emit': True}
DEFAULTS = {
    'currency': 'USD',
    'field': 'base',
    'sleep': 0,
    'memoize': False,
    'precision': 6,
    'url': EXCHANGE_API,
    'params': {'format': 'json'}}

logger = Logger(__name__).logger


def parse_response(json):
    resources = json['list']['resources']
    fields = (r['resource']['fields'] for r in resources)
    return {i['name']: Decimal(i['price']) for i in fields}


def calc_rate(from_cur, to_cur, rates, places=Decimal('0.0001')):
    def get_rate(currency):
        rate = rates.get('USD/%s' % currency, Decimal('nan'))
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


@inlineCallbacks
def asyncParser(base, objconf, skip, **kwargs):
    """ Asynchronously parses the pipe content

    Args:
        base (str): The base currency (exchanging from)
        objconf (obj): The pipe configuration (an Objectify instance)
        skip (bool): Don't parse the content
        kwargs (dict): Keyword argurments

    Kwargs:
        assign (str): Attribute to assign parsed content (default: content)
        feed (dict): The original item

    Returns:
        Deferred: twisted.internet.defer.Deferred Tuple of (item, skip)

    Examples:
        >>> from twisted.internet.task import react
        >>> from pipe2py import get_url
        >>> from pipe2py.lib.utils import Objectify
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(x[0]['content'])
        ...     url = get_url('quote.json')
        ...     conf = {'url': url, 'currency': 'USD', 'sleep': 0, 'precision': 6}
        ...     item = {'base': 'GBP'}
        ...     objconf = Objectify(conf)
        ...     kwargs = {'feed': item, 'assign': 'content'}
        ...     d = asyncParser(item['base'], objconf, False, **kwargs)
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=tu.FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        1.545801
    """
    if skip:
        item = kwargs['feed']
    elif objconf.url.startswith('http'):
        r = yield treq.get(objconf.url, params=objconf.params)
        json = yield treq.json_content(r)
    else:
        abs_url = utils.get_abspath(objconf.url)
        content = yield tu.urlRead(abs_url, delay=objconf.sleep)
        json = loads(content)

    places = Decimal(10) ** -objconf.precision
    rates = parse_response(json)
    rate = calc_rate(base, objconf.currency, rates, places=places)
    item = {kwargs['assign']: rate}
    result = (item, skip)
    returnValue(result)


def parser(base, objconf, skip, **kwargs):
    """ Parses the pipe content

    Args:
        base (str): The base currency (exchanging from)
        objconf (obj): The pipe configuration (an Objectify instance)
        skip (bool): Don't parse the content
        kwargs (dict): Keyword argurments

    Kwargs:
        assign (str): Attribute to assign parsed content (default: content)
        feed (dict): The original item

    Returns:
        Tuple(dict, bool): Tuple of (item, skip)

    Examples:
        >>> from pipe2py import get_url
        >>> from pipe2py.lib.utils import Objectify
        >>>
        >>> url = get_url('quote.json')
        >>> conf = {'url': url, 'currency': 'USD', 'sleep': 0, 'precision': 6}
        >>> item = {'base': 'GBP'}
        >>> objconf = Objectify(conf)
        >>> kwargs = {'feed': item, 'assign': 'content'}
        >>> result, skip = parser(item['base'], objconf, False, **kwargs)
        >>> result['content']
        Decimal('1.545801')
    """
    if skip:
        item = kwargs['feed']
    elif objconf.memoize:
        get = utils.memoize(utils.HALF_DAY)(requests.get)
        r = get(objconf.url, params=objconf.params)
        json = r.json()
    elif objconf.url.startswith('http'):
        r = requests.get(objconf.url, params=objconf.params)
        json = r.json()
    else:
        context = utils.SleepyDict(delay=objconf.sleep)
        abs_url = utils.get_abspath(objconf.url)
        content = urlopen(abs_url, context=context).read()
        json = loads(content)

    places = Decimal(10) ** -objconf.precision
    rates = parse_response(json)
    rate = calc_rate(base, objconf.currency, rates, places=places)
    item = {kwargs['assign']: rate}
    return item, skip


@processor(DEFAULTS, async=True, **OPTS)
def asyncPipe(*args, **kwargs):
    """A processor that asynchronously retrieves the current exchange rate
    for a given currency pair.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        context (obj): pipe2py.Context object
        conf (dict): The pipe configuration. May contain the keys 'url',
            'params', 'currency', 'sleep', 'memoize', 'field', or 'assign'.

            url (str): The exchange rate API url (default:
                http://finance.yahoo.com...)

            params (dict): The API url parameters (default: {'format': 'json'})
            currency: The (exchanging to) currency ISO abbreviation (default: USD).
            sleep (flt): Amount of time to sleep (in secs) before fetching the
                url. Useful for simulating network latency. Default: 0.

            memoize: Cache the exchange rate API response (default: False).
            field (str): Item attribute from which to obtain the string to be
                formatted (default: 'content')

            assign (str): Attribute to assign parsed content (default: content)

    Returns:
        dict: twisted.internet.defer.Deferred feed of items

    Examples:
        >>> from twisted.internet.task import react
        >>> from pipe2py import get_url
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(x.next()['content'])
        ...     url = get_url('quote.json')
        ...     d = asyncPipe({'base': 'GBP'}, conf={'url': url})
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=tu.FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        1.545801
    """
    return asyncParser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs):
    """A processor that retrieves the current exchange rate for a given
    currency pair.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        context (obj): pipe2py.Context object
        conf (dict): The pipe configuration. May contain the keys 'url',
            'params', 'currency', 'sleep', 'memoize', 'field', or 'assign'.

            url (str): The exchange rate API url (default:
                http://finance.yahoo.com...)

            params (dict): The API url parameters (default: {'format': 'json'})
            currency: The (exchanging to) currency ISO abbreviation (default: USD).
            sleep (flt): Amount of time to sleep (in secs) before fetching the
                url. Useful for simulating network latency. Default: 0.

            memoize: Cache the exchange rate API response (default: False).
            field (str): Item attribute from which to obtain the string to be
                formatted (default: 'content')

            assign (str): Attribute to assign parsed content (default: content)

    Yields:
        dict: an item of the result

    Examples:
        >>> from pipe2py import get_url
        >>> url = get_url('quote.json')
        >>> rate = pipe({'base': 'GBP'}, conf={'url': url}).next()['content']
        >>> rate
        Decimal('1.545801')
        >>> 'There are %#.2f GBPs per USD' % rate
        u'There are 1.55 GBPs per USD'
        >>> conf = {'url': url, 'currency': 'TZS', 'precision': 3}
        >>> pipe({'base': 'USD'}, conf=conf).next()['content']
        Decimal('1825.850')
        >>> conf = {'url': url, 'currency': 'XYZ'}
        >>> pipe({'base': 'USD'}, conf=conf).next()['content']
        Decimal('NaN')
    """
    return parser(*args, **kwargs)

