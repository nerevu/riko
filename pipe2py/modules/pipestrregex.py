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
from pipe2py.twisted.utils import (
    asyncStarMap, asyncDispatch, asyncReturn, asyncReduce)

func = utils.substitute
convert = partial(utils.convert_rules, recompile=True)


def asyncParseResult(rules, word, _pass):
    # return asyncReturn(word) if _pass else coopReduce(func, rules, word)
    asyncFunc = partial(maybeDeferred, func)
    return asyncReturn(word) if _pass else asyncReduce(asyncFunc, rules, word)


def parse_result(rules, word, _pass):
    return word if _pass else reduce(func, rules, word)


# Async functions
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
            {
                'match': {'value': <regex>},
                'replace': {'value': <'replacement'>}
            }
        ]
    }

    Returns
    -------
    _OUTPUT : twisted.internet.defer.Deferred generator of replaced strings
    """
    splits = yield asyncGetSplits(_INPUT, conf['RULE'], parse=False, **kwargs)
    asyncFuncs = get_async_dispatch_funcs(first=partial(maybeDeferred, convert))
    parsed = yield asyncDispatch(splits, *asyncFuncs)
    _OUTPUT = yield asyncStarMap(partial(maybeDeferred, parse_result), parsed)
    returnValue(iter(_OUTPUT))


# Synchronous functions
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
    splits = get_splits(_INPUT, conf['RULE'], parse=False, **kwargs)
    parsed = utils.dispatch(splits, *get_dispatch_funcs(first=convert))
    _OUTPUT = starmap(parse_result, parsed)
    return _OUTPUT
