# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipecurrencyformat
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
"""

from functools import partial
from itertools import starmap
from babel.numbers import format_currency
from twisted.internet.defer import inlineCallbacks, returnValue, maybeDeferred
from . import (
    get_dispatch_funcs, get_async_dispatch_funcs, get_splits, asyncGetSplits)
from pipe2py.lib import utils
from pipe2py.lib.utils import combine_dicts as cdicts
from pipe2py.twisted.utils import asyncStarMap, asyncDispatch

opts = {'listize': False}


# Common functions
def parse_result(conf, num, _pass):
    return num if _pass else format_currency(num, conf.currency)


# Async functions
@inlineCallbacks
def asyncPipeCurrencyformat(context=None, _INPUT=None, conf=None, **kwargs):
    """A number module that asynchronously formats a number to a given currency
    string. Loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : twisted Deferred iterable of items or numbers
    conf : {'currency': {'value': <'USD'>}}

    Returns
    -------
    _OUTPUT : twisted.internet.defer.Deferred generator of formatted currencies
    """
    splits = yield asyncGetSplits(_INPUT, conf, **cdicts(opts, kwargs))
    parsed = yield asyncDispatch(splits, *get_async_dispatch_funcs('num'))
    _OUTPUT = yield asyncStarMap(partial(maybeDeferred, parse_result), parsed)
    returnValue(iter(_OUTPUT))


# Synchronous functions
def pipe_currencyformat(context=None, _INPUT=None, conf=None, **kwargs):
    """A number module that formats a number to a given currency string.
    Loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : iterable of items or numbers
    conf : {'currency': {'value': <'USD'>}}

    Returns
    -------
    _OUTPUT : generator of formatted currencies
    """
    splits = get_splits(_INPUT, conf, **cdicts(opts, kwargs))
    parsed = utils.dispatch(splits, *get_dispatch_funcs('num'))
    _OUTPUT = starmap(parse_result, parsed)
    return _OUTPUT
