# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipesimplemath
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=number#SimpleMath
"""

from functools import partial
from itertools import imap
from math import pow
from twisted.internet.defer import inlineCallbacks, returnValue, maybeDeferred
from . import get_broadcast_funcs as get_funcs
from pipe2py.lib import utils
from pipe2py.lib.dotdict import DotDict
from pipe2py.twisted.utils import asyncGather

OPS = {
    'add': lambda x, y: x + y,
    'subtract': lambda x, y: x - y,
    'multiply': lambda x, y: x * y,
    'mean': lambda x, y: (x + y) / 2.0,
    'divide': lambda x, y: x / (y * 1.0),
    'modulo': lambda x, y: x % y,
    'power': lambda x, y: pow(x, y),
}


# Common functions
def get_parsed(_INPUT, conf, **kwargs):
    inputs = imap(DotDict, _INPUT)
    broadcast_funcs = get_funcs(conf, listize=False, **kwargs)
    dispatch_funcs = [utils.passthrough, utils.get_num, utils.passthrough]
    splits = utils.broadcast(inputs, *broadcast_funcs)
    return utils.dispatch(splits, *dispatch_funcs)


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
    _input = yield _INPUT
    parsed = get_parsed(_input, conf, **kwargs)
    _OUTPUT = yield asyncGather(parsed, partial(maybeDeferred, parse_result))
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
    parsed = get_parsed(_INPUT, conf, **kwargs)
    _OUTPUT = utils.gather(parsed, parse_result)
    return _OUTPUT
