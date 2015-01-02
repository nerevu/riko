# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipecurrencyformat
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
"""

from functools import partial
from itertools import imap
from babel.numbers import format_currency
from twisted.internet.defer import inlineCallbacks, returnValue, maybeDeferred
from . import get_broadcast_funcs as get_funcs
from pipe2py.lib import utils
from pipe2py.lib.dotdict import DotDict
from pipe2py.twisted.utils import asyncGather


# Common functions
def get_parsed(_INPUT, conf, **kwargs):
    inputs = imap(DotDict, _INPUT)
    broadcast_funcs = get_funcs(conf, **kwargs)
    dispatch_funcs = [utils.compress_conf, utils.get_num, utils.passthrough]
    splits = utils.broadcast(inputs, *broadcast_funcs)
    return utils.dispatch(splits, *dispatch_funcs)


def parse_result(conf, num, _pass):
    return num if _pass else format_currency(num, conf.currency)


# Async functions
@inlineCallbacks
def asyncPipeCurrencyFormat(context=None, _INPUT=None, conf=None, **kwargs):
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
    _input = yield _INPUT
    parsed = get_parsed(_input, conf, **kwargs)
    _OUTPUT = yield asyncGather(parsed, partial(maybeDeferred, parse_result))
    returnValue(_OUTPUT)


# Synchronous functions
def pipe_currencyformat(context=None, _INPUT=None, conf=None, **kwargs):
    """A number module that formats a number to a given currency string.
    Loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : iterable of items or numbers
    conf : {'currency': {'value': <'USD'>}}

    Yields
    ------
    _OUTPUT : formatted currency
    """
    parsed = get_parsed(_INPUT, conf, **kwargs)
    _OUTPUT = utils.gather(parsed, parse_result)
    return _OUTPUT
