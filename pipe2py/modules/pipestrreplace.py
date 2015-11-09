# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipestrreplace
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=string#StringReplace
"""

from __future__ import (
    absolute_import, division, print_function, with_statement,
    unicode_literals)

from itertools import starmap
from functools import partial
from twisted.internet.defer import inlineCallbacks, returnValue, maybeDeferred

from . import (
    get_dispatch_funcs, get_async_dispatch_funcs, get_splits, asyncGetSplits)
from pipe2py.lib import utils
from pipe2py.twisted.utils import (
    asyncStarMap, asyncDispatch, asyncReturn, asyncReduce)

SWITCH = {
    '1': lambda word, rule: word.replace(rule.find, rule.replace, 1),
    '2': lambda word, rule: utils.rreplace(word, rule.find, rule.replace, 1),
    '3': lambda word, rule: word.replace(rule.find, rule.replace),
    # todo: else assertion
}

# Common functions
func = lambda word, rule: SWITCH.get(rule.param)(word, rule)


# Async functions
def asyncParseResult(rules, word, _pass):
    # asyncSubstitute = coopReduce(func, rules, word)
    asyncSubstitute = asyncReduce(partial(maybeDeferred, func), rules, word)
    return asyncReturn(word) if _pass else asyncSubstitute


@inlineCallbacks
def asyncPipeStrreplace(context=None, _INPUT=None, conf=None, **kwargs):
    """A string module that asynchronously replaces text. Loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : twisted Deferred iterable of items or strings
    conf : {
        'RULE': [
            {
                'param': {'value': <match type: 1=first, 2=last, 3=every>},
                'find': {'value': <text to find>},
                'replace': {'value': <replacement>}
            }
        ]
    }

    Returns
    -------
    _OUTPUT : twisted.internet.defer.Deferred generator of replaced strings
    """
    splits = yield asyncGetSplits(_INPUT, conf['RULE'], **kwargs)
    parsed = yield asyncDispatch(splits, *get_async_dispatch_funcs())
    _OUTPUT = yield asyncStarMap(asyncParseResult, parsed)
    returnValue(iter(_OUTPUT))


# Synchronous functions
def parse_result(rules, word, _pass):
    return word if _pass or not word else reduce(func, rules, word)


def pipe_strreplace(context=None, _INPUT=None, conf=None, **kwargs):
    """A string module that replaces text. Loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : iterable of items or strings
    conf : {
        'RULE': [
            {
                'param': {'value': <match type: 1=first, 2=last, 3=every>},
                'find': {'value': <text to find>},
                'replace': {'value': <replacement>}
            }
        ]
    }

    Returns
    -------
    _OUTPUT : generator of replaced strings
    """
    splits = get_splits(_INPUT, conf['RULE'], **kwargs)
    parsed = utils.dispatch(splits, *get_dispatch_funcs())
    _OUTPUT = starmap(parse_result, parsed)
    return _OUTPUT
