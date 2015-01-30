# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipestrtransform
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
"""

from __future__ import (
    absolute_import, division, print_function, with_statement,
    unicode_literals)

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
    return word if _pass else getattr(str, conf.transformation)(word)


# Async functions
@inlineCallbacks
def asyncPipeStrtransform(context=None, item=None, conf=None, **kwargs):
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
    split = yield asyncGetSplit(item, conf, **cdicts(opts, kwargs))
    parsed = yield asyncDispatch(split, *get_async_dispatch_funcs())
    _OUTPUT = yield asyncStarMap(partial(maybeDeferred, parse_result), parsed)
    returnValue(iter(_OUTPUT))


# Synchronous functions
def pipe_strtransform(context=None, item=None, conf=None, **kwargs):
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
    split = get_split(item, conf, **cdicts(opts, kwargs))
    parsed = utils.dispatch(split, *get_dispatch_funcs())
    return starmap(parse_result, parsed)
