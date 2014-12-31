# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipecurrencyformat
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
"""

from functools import partial
from babel.numbers import format_currency
from pipe2py.lib import utils
from pipe2py.lib.dotdict import DotDict


def parse_result(conf, num, _pass):
    return num if _pass else format_currency(num, conf.currency)


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
    test = kwargs.pop('pass_if', None)
    loop_with = kwargs.pop('with', None)
    get_with = lambda i: i.get(loop_with, **kwargs) if loop_with else i
    get_pass = partial(utils.get_pass, test=test)
    get_conf = partial(utils.parse_conf, DotDict(conf), **kwargs)
    funcs = [get_conf, utils.get_num, utils.passthrough]

    splits = utils.broadcast(_INPUT, DotDict, get_with, get_pass)
    parsed = utils.dispatch(splits, *funcs)
    _OUTPUT = utils.gather(parsed, parse_result)
    return _OUTPUT
