# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipestrtransform
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
"""

from functools import partial
from itertools import starmap
from twisted.internet.defer import inlineCallbacks, returnValue, maybeDeferred
from . import (
    get_dispatch_funcs, get_async_dispatch_funcs, get_splits, asyncGetSplits)
from pipe2py.lib import utils
from pipe2py.lib.utils import combine_dicts as cdicts
from pipe2py.twisted.utils import asyncStarMap, asyncDispatch

opts = {'listize': False}


# Common functions
def parse_result(conf, word, _pass):
    allowed = {'capitalize', 'lower', 'upper', 'swapcase', 'title'}
    _pass = _pass if conf.transformation in allowed else True
    encoded = str(word.encode('utf-8'))
    return word if _pass else getattr(str, conf.transformation)(encoded)


# Async functions
@inlineCallbacks
def asyncPipeStrtransform(context=None, _INPUT=None, conf=None, **kwargs):
    """A string module that asynchronously splits a string into tokens
    delimited by separators. Loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : twisted Deferred iterable of items or strings
    conf : {'transformation': {value': <'swapcase'>}}

    Returns
    -------
    _OUTPUT : twisted.internet.defer.Deferred generator of tokenized strings
    """
    splits = yield asyncGetSplits(_INPUT, conf, **cdicts(opts, kwargs))
    parsed = yield asyncDispatch(splits, *get_async_dispatch_funcs())
    _OUTPUT = yield asyncStarMap(partial(maybeDeferred, parse_result), parsed)
    returnValue(iter(_OUTPUT))


# Synchronous functions
def pipe_strtransform(context=None, _INPUT=None, conf=None, **kwargs):
    """A string module that splits a string into tokens delimited by
    separators. Loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : iterable of items or strings
    conf : {'transformation': {value': <'swapcase'>}}

    Returns
    -------
    _OUTPUT : generator of tokenized strings
    """
    splits = get_splits(_INPUT, conf, **cdicts(opts, kwargs))
    parsed = utils.dispatch(splits, *get_dispatch_funcs())
    _OUTPUT = starmap(parse_result, parsed)
    return _OUTPUT
