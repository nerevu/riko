# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipesubstr
    ~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=string#SubString
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
    conf['start'] = conf.pop('from')
    inputs = imap(DotDict, _INPUT)
    broadcast_funcs = get_funcs(conf, **kwargs)
    dispatch_funcs = [utils.compress_conf, utils.get_word, utils.passthrough]
    splits = utils.broadcast(inputs, *broadcast_funcs)
    return utils.dispatch(splits, *dispatch_funcs)


def parse_result(conf, word, _pass):
    start = int(conf.start)
    end = int(conf.start + conf.length)
    return word if _pass else word[start:end]


# Async functions
@inlineCallbacks
def asyncPipeSubstr(context=None, _INPUT=None, conf=None, **kwargs):
    """A string module that asynchronously returns a substring. Loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : twisted Deferred iterable of items or strings
    conf : {
        'from': {'type': 'number', value': <starting position>},
        'length': {'type': 'number', 'value': <count of characters to return>}
    }

    returns
    -------
    _OUTPUT : twisted.internet.defer.Deferred generator of substrings
    """
    _input = yield _INPUT
    parsed = get_parsed(_input, conf, **kwargs)
    _OUTPUT = yield asyncGather(parsed, partial(maybeDeferred, parse_result))
    returnValue(iter(_OUTPUT))


# Synchronous functions
def pipe_substr(context=None, _INPUT=None, conf=None, **kwargs):
    """A string module that returns a substring. Loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : iterable of items or strings
    conf : {
        'from': {'type': 'number', value': <starting position>},
        'length': {'type': 'number', 'value': <count of characters to return>}
    }

    Returns
    -------
    _OUTPUT : generator of substrings
    """
    parsed = get_parsed(_INPUT, conf, **kwargs)
    _OUTPUT = utils.gather(parsed, parse_result)
    return _OUTPUT
