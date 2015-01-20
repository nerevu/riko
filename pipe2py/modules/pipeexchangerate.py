# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipeexchangerate
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
"""

import requests

from functools import partial
from pipe2py.lib import utils
from pipe2py.lib.dotdict import DotDict

timeout = 60 * 60 * 24  # 24 hours in seconds


@utils.memoize(timeout)
def get_rates(offline=False):
    if offline:
        fields = [
            {'name': 'USD/USD', 'price': 1},
            {'name': 'USD/EUR', 'price': 0.8234},
            {'name': 'USD/GBP', 'price': 0.6448},
            {'name': 'USD/INR', 'price': 63.6810},
        ]
    else:
        EXCHANGE_API_BASE = 'http://finance.yahoo.com/webservice'
        EXCHANGE_API = '%s/v1/symbols/allcurrencies/quote' % EXCHANGE_API_BASE
        r = requests.get(EXCHANGE_API, params={'format': 'json'})
        fields = r.json()['list']['resources']['resource']['fields']

    return {i['name']: i['price'] for i in fields}


def calc_rate(from_cur, to_cur, rates):
    if from_cur == to_cur:
        rate = 1
    elif to_cur == 'USD':
        rate = rates['USD/%s' % from_cur]
    else:
        usd_to_given = rates['USD/%s' % from_cur]
        usd_to_default = rates['USD/%s' % to_cur]
        rate = usd_to_given * (1 / usd_to_default)

    return 1 / float(rate)


def parse_result(conf, base, _pass):
    base = base or conf.default

    try:
        offline = conf.offline
    except AttributeError:
        offline = False

    return base if _pass else calc_rate(base, conf.quote, get_rates(offline))


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

    Yields
    ------
    _OUTPUT : hashed strings
    """
    test = kwargs.pop('pass_if', None)
    loop_with = kwargs.pop('with', None)
    get_with = lambda i: i.get(loop_with, **kwargs) if loop_with else i
    get_pass = partial(utils.get_pass, test=test)
    get_conf = partial(utils.parse_conf, DotDict(conf), **kwargs)
    funcs = [get_conf, utils.get_word, utils.passthrough]

    splits = utils.broadcast(_INPUT, DotDict, get_with, get_pass)
    parsed = utils.dispatch(splits, *funcs)
    _OUTPUT = utils.gather(parsed, parse_result)
    return _OUTPUT
