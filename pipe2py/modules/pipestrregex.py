# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipestrregex
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=string
"""

from functools import partial
from itertools import starmap
from twisted.internet.defer import inlineCallbacks, returnValue, maybeDeferred
from . import (
    get_dispatch_funcs, get_async_dispatch_funcs, get_splits, asyncGetSplits)
from pipe2py.lib import utils
from pipe2py.lib.utils import combine_dicts as cdicts
from pipe2py.twisted.utils import (
    asyncStarMap, asyncDispatch, asyncReturn, asyncReduce)

opts = {'convert': False}
func = utils.substitute
convert_func = partial(utils.convert_rules, recompile=True)


# Async functions
def asyncParseResult(rules, word, _pass):
    # return asyncReturn(word) if _pass else coopReduce(func, rules, word)
    asyncFunc = partial(maybeDeferred, func)
    return asyncReturn(word) if _pass else asyncReduce(asyncFunc, rules, word)


@inlineCallbacks
def asyncPipeStrregex(context=None, _INPUT=None, conf=None, **kwargs):
    """A string module that asynchronously replaces text using regexes. Each
    has the general format: "In [field] replace [regex pattern] with [text]".
    Loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : twisted Deferred iterable of items or strings
    conf : {
        'RULE': [
            {'match': {'value': <regex1>}, 'replace': {'value': <'text1'>}},
            {'match': {'value': <regex2>}, 'replace': {'value': <'text2'>}},
            {'match': {'value': <regex3>}, 'replace': {'value': <'text3'>}},
        ]
    }

    Returns
    -------
    _OUTPUT : twisted.internet.defer.Deferred generator of replaced strings
    """
    splits = yield asyncGetSplits(_INPUT, conf['RULE'], **cdicts(opts, kwargs))
    first = partial(maybeDeferred, convert_func)
    asyncFuncs = get_async_dispatch_funcs(first=first)
    parsed = yield asyncDispatch(splits, *asyncFuncs)
    _OUTPUT = yield asyncStarMap(asyncParseResult, parsed)
    returnValue(iter(_OUTPUT))


# Synchronous functions
def parse_result(rules, word, _pass):
    return word if _pass else reduce(func, rules, word)


def pipe_strregex(context=None, _INPUT=None, conf=None, **kwargs):
    """A string module that replaces text using regexes. Each has the general
    format: "In [field] replace [regex pattern] with [text]". Loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : iterable of items or strings
    conf : {
        'RULE': [
            {
                'match': {'value': <regex>},
                'replace': {'value': <'replacement'>}
            }
        ]
    }

    Returns
    -------
    _OUTPUT : generator of replaced strings
    """
    splits = get_splits(_INPUT, conf['RULE'], **cdicts(opts, kwargs))
    parsed = utils.dispatch(splits, *get_dispatch_funcs(first=convert_func))
    _OUTPUT = starmap(parse_result, parsed)
    return _OUTPUT
