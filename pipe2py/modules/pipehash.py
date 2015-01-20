# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipehash
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~
"""

import ctypes
from functools import partial
from itertools import starmap
from twisted.internet.defer import inlineCallbacks, returnValue, maybeDeferred
from . import (
    get_dispatch_funcs, get_async_dispatch_funcs, get_splits, asyncGetSplits)
from pipe2py.lib import utils
from pipe2py.twisted.utils import asyncStarMap, asyncDispatch


# Common functions
def parse_result(conf, word, _pass):
    return word if _pass else ctypes.c_uint(hash(word)).value


# Async functions
@inlineCallbacks
def asyncPipeHash(context=None, _INPUT=None, conf=None, **kwargs):
    """A string module that asynchronously hashes the given text. Loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : twisted Deferred iterable of items or strings

    Returns
    -------
    _OUTPUT : twisted.internet.defer.Deferred generator of hashed strings
    """
    splits = yield asyncGetSplits(_INPUT, conf, listize=False, **kwargs)
    parsed = yield asyncDispatch(splits, *get_async_dispatch_funcs())
    _OUTPUT = yield asyncStarMap(partial(maybeDeferred, parse_result), parsed)
    returnValue(iter(_OUTPUT))


# Synchronous functions
def pipe_hash(context=None, _INPUT=None, conf=None, **kwargs):
    """A string module that hashes the given text. Loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : iterable of items or strings

    Returns
    -------
    _OUTPUT : generator of hashed strings
    """
    splits = get_splits(_INPUT, conf, listize=False, **kwargs)
    parsed = utils.dispatch(splits, *get_dispatch_funcs())
    _OUTPUT = starmap(parse_result, parsed)
    return _OUTPUT
