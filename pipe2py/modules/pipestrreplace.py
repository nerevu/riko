# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipestrreplace
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=string#StringReplace
"""

from functools import partial
from itertools import imap
from twisted.internet.defer import inlineCallbacks, returnValue, maybeDeferred
from . import get_broadcast_funcs as get_funcs
from pipe2py.lib import utils
from pipe2py.lib.dotdict import DotDict
from pipe2py.twisted.utils import asyncGather

SWITCH = {
    '1': lambda word, rule: word.replace(rule.find, rule.replace, 1),
    '2': lambda word, rule: utils.rreplace(word, rule.find, rule.replace, 1),
    '3': lambda word, rule: word.replace(rule.find, rule.replace),
    # todo: else assertion
}


# Common functions
def get_parsed(_INPUT, conf, **kwargs):
    inputs = imap(DotDict, _INPUT)
    broadcast_funcs = get_funcs(conf['RULE'], **kwargs)
    dispatch_funcs = [utils.passthrough, utils.get_word, utils.passthrough]
    splits = utils.broadcast(inputs, *broadcast_funcs)
    return utils.dispatch(splits, *dispatch_funcs)


def parse_result(rules, word, _pass):
    func = lambda word, rule: SWITCH.get(rule.param)(word, rule)
    return word if _pass else reduce(func, rules, word)


# Async functions
@inlineCallbacks
def asyncPipeStrReplace(context=None, _INPUT=None, conf=None, **kwargs):
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
    _input = yield _INPUT
    parsed = get_parsed(_input, conf, **kwargs)
    _OUTPUT = yield asyncGather(parsed, partial(maybeDeferred, parse_result))
    returnValue(_OUTPUT)


# Synchronous functions
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
    parsed = get_parsed(_INPUT, conf, **kwargs)
    _OUTPUT = utils.gather(parsed, parse_result)
    return _OUTPUT
