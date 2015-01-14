# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipestrtransform
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
"""

from functools import partial
from itertools import imap
from twisted.internet.defer import inlineCallbacks, returnValue, maybeDeferred
from . import get_broadcast_funcs as get_funcs
from pipe2py.lib import utils
from pipe2py.lib.dotdict import DotDict
from pipe2py.twisted.utils import asyncGather


# Common functions
def get_parsed(_INPUT, conf, **kwargs):
    inputs = imap(DotDict, _INPUT)
    broadcast_funcs = get_funcs(conf, listize=False, **kwargs)
    dispatch_funcs = [utils.passthrough, utils.get_word, utils.passthrough]
    splits = utils.broadcast(inputs, *broadcast_funcs)
    return utils.dispatch(splits, *dispatch_funcs)


def parse_result(conf, word, _pass):
    transformation = conf._fields[0]
    return word if _pass else getattr(str, transformation)(word)


# Async functions
@inlineCallbacks
def asyncPipeStrtransform(context=None, _INPUT=None, conf=None, **kwargs):
    """A string module that asynchronously splits a string into tokens
    delimited by separators. Loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : twisted Deferred iterable of items or strings
    conf : {
        'capitalize': {'type': 'bool', value': <1>},
        'lower': {'type': 'bool', value': <1>},
        'upper': {'type': 'bool', value': <1>},
        'swapcase': {'type': 'bool', value': <1>},
        'title': {'type': 'bool', value': <1>},
    }

    Returns
    -------
    _OUTPUT : twisted.internet.defer.Deferred generator of tokenized strings
    """
    _input = yield _INPUT
    parsed = get_parsed(_input, conf, **kwargs)
    _OUTPUT = yield asyncGather(parsed, partial(maybeDeferred, parse_result))
    returnValue(iter(_OUTPUT))


# Synchronous functions
def pipe_strtransform(context=None, _INPUT=None, conf=None, **kwargs):
    """A string module that splits a string into tokens delimited by
    separators. Loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : iterable of items or strings
    conf : {
        'capitalize': {'type': 'bool', value': <1>},
        'lower': {'type': 'bool', value': <1>},
        'upper': {'type': 'bool', value': <1>},
        'swapcase': {'type': 'bool', value': <1>},
        'title': {'type': 'bool', value': <1>},
    }

    Returns
    -------
    _OUTPUT : generator of tokenized strings
    """
    parsed = get_parsed(_INPUT, conf, **kwargs)
    _OUTPUT = utils.gather(parsed, parse_result)
    return _OUTPUT
