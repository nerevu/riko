# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipeexchangerate
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
"""

import requests
import treq

from os import path as p
from urllib2 import urlopen
from itertools import starmap
from functools import partial
from json import loads
from twisted.internet.defer import inlineCallbacks, returnValue
from twisted.internet.threads import deferToThread
from . import (
    get_dispatch_funcs, get_async_dispatch_funcs, get_splits, asyncGetSplits)
from pipe2py.lib import utils
from pipe2py.lib.utils import combine_dicts as cdicts
from pipe2py.twisted.utils import (
    asyncStarMap, asyncDispatch, asyncNone, asyncReturn)

opts = {'listize': False}
parent = p.dirname(p.dirname(__file__))
abspath = p.abspath(p.join(parent, 'data', 'quote.json'))
logger = None
LOCAL_RATES_URL = 'file://%s' % abspath

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


def parse_request(json):
    resources = json['list']['resources']
    fields = (r['resource']['fields'] for r in resources)
    return {i['name']: i['price'] for i in fields}


def parse_result(conf, word, _pass, rates=None):
    base = word or conf.default
    return base if _pass else calc_rate(base, conf.quote, rates)


# Async functions
@utils.memoize(utils.half_day)
def asyncGetOfflineRateData(*args, **kwargs):
    logger.debug('loading offline data')

    if kwargs.get('err', True):
        logger.error('Error loading exchange rate data from %s' % EXCHANGE_API)

    resp = deferToThread(urlopen, LOCAL_RATES_URL)
    resp.addCallback(lambda r: loads(r.read()))
    return resp


@utils.memoize(utils.half_day)
def asyncGetRateData():
    logger.debug('asyncGetRateData')
    resp = treq.get(EXCHANGE_API, params=PARAMS)
    resp.addCallbacks(treq.json_content, asyncGetOfflineRateData)
    return resp


def asyncSetup(context=None, conf=None, **kwargs):
    global logger
    logger = utils.get_logger(context)
    offline = conf.get('offline', {}).get('value')
    kw = {'err': False}
    # logger.debug('data type: ' % type(json))
    # logger.debug('data len: ' % len(json))
    return asyncGetOfflineRateData(**kw) if offline else asyncGetRateData()


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
    global logger
    logger = utils.get_logger(context)
    rates = parse_request(kwargs['setup_output'])
    splits = yield asyncGetSplits(_INPUT, conf, **cdicts(opts, kwargs))
    parsed = yield asyncDispatch(splits, *get_async_dispatch_funcs())
    _OUTPUT = starmap(partial(parse_result, rates=rates), parsed)
    returnValue(iter(_OUTPUT))


# Synchronous functions
@utils.memoize(utils.half_day)
def get_offline_rate_data(*args, **kwargs):
    if kwargs.get('err', True):
        logger.error('Error loading exchange rate data from %s' % EXCHANGE_API)
    else:
        logger.warning('Exchange rate data from %s was empty' % EXCHANGE_API)

    return loads(urlopen(LOCAL_RATES_URL).read())


@utils.memoize(utils.half_day)
def get_rate_data():
    r = requests.get(EXCHANGE_API, params=PARAMS)
    return r.json()


def setup(conf=None, **kwargs):
    offline = conf.get('offline', {}).get('value')
    kw = {'err': False}
    return get_offline_rate_data(**kw) if offline else get_rate_data()


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
    rates = parse_request(kwargs['setup_output'])
    splits = get_splits(_INPUT, conf, **cdicts(opts, kwargs))
    parsed = utils.dispatch(splits, *get_dispatch_funcs())
    _OUTPUT = starmap(partial(parse_result, rates=rates), parsed)
    return _OUTPUT
