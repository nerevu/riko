# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipestringtokenizer
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=string#StringTokenizer
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
    conf['delimiter'] = conf.pop('to-str')
    inputs = imap(DotDict, _INPUT)
    broadcast_funcs = get_funcs(conf, **kwargs)
    dispatch_funcs = [utils.compress_conf, utils.get_word, utils.passthrough]
    splits = utils.broadcast(inputs, *broadcast_funcs)
    return utils.dispatch(splits, *dispatch_funcs)


def parse_result(conf, word, _pass):
    if _pass:
        token = None
    else:
        splits = word.split(conf.delimiter)

        try:
            chunks = set(splits) if conf.dedupe else splits
        except AttributeError:
            chunks = splits

        try:
            chunks = sorted(chunks) if conf.sort else chunks
        except AttributeError:
            chunks = chunks

        token = ({'content': chunk} for chunk in chunks)

    return token


# Async functions
@inlineCallbacks
def asyncPipeStringTokenizer(context=None, _INPUT=None, conf=None, **kwargs):
    """A string module that asynchronously splits a string into tokens
    delimited by separators. Loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : twisted Deferred iterable of items or strings
    conf : {
        'to-str': {'value': <delimiter>},
        'dedupe': {'type': 'bool', value': <1>},
        'sort': {'type': 'bool', value': <1>}
    }

    Returns
    -------
    _OUTPUT : twisted.internet.defer.Deferred generator of items
    """
    _input = yield _INPUT
    parsed = get_parsed(_input, conf, **kwargs)
    items = yield asyncGather(parsed, partial(maybeDeferred, parse_result))
    _OUTPUT = utils.multiplex(items)
    returnValue(_OUTPUT)


# Synchronous functions
def pipe_stringtokenizer(context=None, _INPUT=None, conf=None, **kwargs):
    """A string module that splits a string into tokens delimited by
    separators. Loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : iterable of items or strings
    conf : {
        'to-str': {'value': <delimiter>},
        'dedupe': {'type': 'bool', value': <1>},
        'sort': {'type': 'bool', value': <1>}
    }

    Returns
    -------
    _OUTPUT : generator of items
    """
    parsed = get_parsed(_INPUT, conf, **kwargs)
    items = utils.gather(parsed, parse_result)
    _OUTPUT = utils.multiplex(items)
    return _OUTPUT
