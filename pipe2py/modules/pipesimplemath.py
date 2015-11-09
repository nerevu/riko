# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipesimplemath
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=number#SimpleMath
"""

from __future__ import (
    absolute_import, division, print_function, with_statement,
    unicode_literals)

from functools import partial
from itertools import starmap
from math import pow
from twisted.internet.defer import inlineCallbacks, returnValue, maybeDeferred

from . import (
    get_dispatch_funcs, get_async_dispatch_funcs, get_splits, asyncGetSplits)
from pipe2py.lib import utils
from pipe2py.lib.utils import combine_dicts as cdicts
from pipe2py.twisted.utils import asyncStarMap, asyncDispatch

opts = {'listize': False}


def mean(*nums):
    try:
        return sum(nums) / len(nums)
    except ZeroDivisionError:
        return 0.0

OPS = {
    'add': lambda x, y: x + y,
    'subtract': lambda x, y: x - y,
    'multiply': lambda x, y: x * y,
    'mean': mean,
    'divide': lambda x, y: x / y,
    'modulo': lambda x, y: x % y,
    'power': lambda x, y: pow(x, y),
}


# Common functions
def parse_result(conf, num, _pass):
    return num if _pass else OPS[conf.OP](num, conf.OTHER)


# Async functions
@inlineCallbacks
def asyncPipeSimplemath(context=None, _INPUT=None, conf=None, **kwargs):
    """A number module that asynchronously performs basic arithmetic, such as
    addition and subtraction. Loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : twisted Deferred iterable of items or numbers
    conf : {
        'OTHER': {'type': 'number', 'value': <'5'>},
        'OP': {'type': 'text', 'value': <'modulo'>}
    }

    Returns
    -------
    _OUTPUT : twisted.internet.defer.Deferred generator of tokenized floats
    """
    splits = yield asyncGetSplits(_INPUT, conf, **cdicts(opts, kwargs))
    parsed = yield asyncDispatch(splits, *get_async_dispatch_funcs('num'))
    _OUTPUT = yield asyncStarMap(partial(maybeDeferred, parse_result), parsed)
    returnValue(iter(_OUTPUT))


# Synchronous functions
def pipe_simplemath(context=None, _INPUT=None, conf=None, **kwargs):
    """A number module that performs basic arithmetic, such as addition and
    subtraction. Loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : iterable of items or numbers
    kwargs -- other value, if wired in
    conf : {
        'OTHER': {'type': 'number', 'value': <'5'>},
        'OP': {'type': 'text', 'value': <'modulo'>}
    }

    Returns
    -------
    _OUTPUT : generator of tokenized floats
    """
    splits = get_splits(_INPUT, conf, **cdicts(opts, kwargs))
    parsed = utils.dispatch(splits, *get_dispatch_funcs('num'))
    _OUTPUT = starmap(parse_result, parsed)
    return _OUTPUT
