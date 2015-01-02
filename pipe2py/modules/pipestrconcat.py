# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipestrconcat
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=string#StringBuilder
"""

# aka stringbuilder

from functools import partial
from itertools import imap
from twisted.internet.defer import inlineCallbacks, returnValue, maybeDeferred
from . import get_broadcast_funcs as get_funcs
from pipe2py.lib import utils
from pipe2py.lib.dotdict import DotDict
from pipe2py.twisted.utils import asyncGather


# Common functions
def get_splits(_INPUT, conf, **kwargs):
    inputs = imap(DotDict, _INPUT)
    bkwargs = utils.combine_dicts({'ftype': None, 'parse': False}, kwargs)
    broadcast_funcs = get_funcs(conf['part'], **bkwargs)
    return utils.broadcast(inputs, *broadcast_funcs)


def parse_result(parts, _, _pass):
    # Since `ftype` in `get_splits` above is `None`, the second argument passed
    # here is `None`. This uses `_` as a throw-a-way variable to soak it up.
    return '' if _pass else ''.join(parts)


# Async functions
@inlineCallbacks
def asyncPipeStrconcat(context=None, _INPUT=None, conf=None, **kwargs):
    """A string module that asynchronously builds a string. Loopable. No direct
    input.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : asyncPipe like object (twisted Deferred iterable of items)
    conf : {
        'part': [
            {'value': '<img src="'}, {'subkey': 'img.src'}, {'value': '">'}
        ]
    }

    Returns
    -------
    _OUTPUT : twisted.internet.defer.Deferred generator of joined strings
    """
    _input = yield _INPUT
    splits = get_splits(_input, conf, **kwargs)
    _OUTPUT = yield asyncGather(splits, partial(maybeDeferred, parse_result))
    returnValue(_OUTPUT)


# Synchronous functions
def pipe_strconcat(context=None, _INPUT=None, conf=None, **kwargs):
    """A string module that builds a string. Loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : pipeforever pipe or an iterable of items
    conf : {
        'part': [
            {'value': '<img src="'}, {'subkey': 'img.src'}, {'value': '">'}
        ]
    }

    Returns
    -------
    _OUTPUT : generator of joined strings
    """
    splits = get_splits(_INPUT, conf, **kwargs)
    _OUTPUT = utils.gather(splits, parse_result)
    return _OUTPUT
