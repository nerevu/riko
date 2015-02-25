# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipeexchangerate
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
"""

import requests
import treq

from os.path import join
from itertools import starmap
from json import loads
from twisted.internet.defer import inlineCallbacks, returnValue
from twisted.internet.threads import deferToThread
from . import (
    get_dispatch_funcs, get_async_dispatch_funcs, get_splits, asyncGetSplits)
from pipe2py.lib import utils
from pipe2py.lib.log import logger
from pipe2py.lib.utils import combine_dicts as cdicts
from pipe2py.twisted.utils import (
    asyncStarMap, asyncDispatch, asyncNone, asyncReturn)

opts = {'listize': False}

FIELDS = [
    {'name': 'USD/USD', 'price': 1},
    {'name': 'USD/EUR', 'price': 0.8234},
    {'name': 'USD/GBP', 'price': 0.6448},
    {'name': 'USD/INR', 'price': 63.6810},
    {'name': 'USD/PLN', 'price': 3.76},
    {'name': 'USD/SGD', 'price': 1.34},
]

EXCHANGE_API_BASE = 'http://finance.yahoo.com/webservice'
EXCHANGE_API = '%s/v1/symbols/allcurrencies/quote' % EXCHANGE_API_BASE
PARAMS = {'format': 'json'}


# Common functions
def get_base(conf, word):
    base = word or conf.default

    try:
        offline = conf.offline
    except AttributeError:
        offline = False

    return (base, offline)


def calc_rate(from_cur, to_cur, rates):
    if from_cur == to_cur:
        rate = 1
    elif to_cur == 'USD':
        try:
            rate = rates['USD/%s' % from_cur]
        except KeyError:
            logger.warning('rate USD/%s not found in rates' % from_cur)
            rate = 1
    else:
        usd_to_given = rates['USD/%s' % from_cur]
        usd_to_default = rates['USD/%s' % to_cur]
        rate = usd_to_given * (1 / usd_to_default)

    return 1 / float(rate)


def parse_request(data, offline):
    if offline:
        fields = FIELDS
    else:
        resources = data['list']['resources']
        fields = (r['resource']['fields'] for r in resources)

    return {i['name']: i['price'] for i in fields}


@utils.memoize(utils.timeout)
def get_rate_data():
    r = requests.get(EXCHANGE_API, params=PARAMS)
    return r.json()


@inlineCallbacks
def asyncGetDefaultRateData(_):
    logger.error('failed to load exchange rate data from %s' % EXCHANGE_API)
    path = join('..', 'data', 'quote.json')
    url = utils.get_abspath(path)
    resp = yield deferToThread(urlopen, url)
    json = loads(resp.read())
    returnValue(json)


@utils.memoize(utils.timeout)
def asyncGetRateData():
    resp = treq.get(EXCHANGE_API, params=PARAMS)
    resp.addCallbacks(treq.json_content, asyncGetDefaultRateData)
    return resp


# Async functions
@inlineCallbacks
def asyncParseResult(conf, word, _pass):
    base, offline = get_base(conf, word)
    data = yield asyncNone if offline else asyncGetRateData()
    rates = parse_request(data, offline)
    result = base if _pass else calc_rate(base, conf.quote, rates)
    returnValue(result)


@inlineCallbacks
def asyncPipeExchangerate(context=None, _INPUT=None, conf=None, **kwargs):
    """A string module that asynchronously retrieves the current exchange rate
    for a given currency pair. Loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : twisted Deferred iterable of items or strings (base currency)
    conf : {
        'quote': {'value': <'USD'>},
        'default': {'value': <'USD'>},
        'offline': {'type': 'bool', 'value': '0'},
    }

    Returns
    -------
    _OUTPUT : twisted.internet.defer.Deferred generator of hashed strings
    """
    splits = yield asyncGetSplits(_INPUT, conf, **cdicts(opts, kwargs))
    parsed = yield asyncDispatch(splits, *get_async_dispatch_funcs())
    _OUTPUT = yield asyncStarMap(asyncParseResult, parsed)
    returnValue(iter(_OUTPUT))


# Synchronous functions
def parse_result(conf, word, _pass):
    base, offline = get_base(conf, word)
    data = None if offline else get_rate_data()
    rates = parse_request(data, offline)
    result = base if _pass else calc_rate(base, conf.quote, rates)
    return result


def pipe_exchangerate(context=None, _INPUT=None, conf=None, **kwargs):
    """A string module that retrieves the current exchange rate for a given
    currency pair. Loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : iterable of items or strings (base currency)
    conf : {
        'quote': {'value': <'USD'>},
        'default': {'value': <'USD'>},
        'offline': {'type': 'bool', 'value': '0'},
    }

    Returns
    -------
    _OUTPUT : generator of hashed strings
    """
    splits = get_splits(_INPUT, conf, **cdicts(opts, kwargs))
    parsed = utils.dispatch(splits, *get_dispatch_funcs())
    _OUTPUT = starmap(parse_result, parsed)
    return _OUTPUT
