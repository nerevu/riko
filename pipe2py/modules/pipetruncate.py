# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipetruncate
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=operators
"""

from __future__ import (
    absolute_import, division, print_function, with_statement,
    unicode_literals)

from itertools import islice

from . import get_splits, asyncGetSplits
from twisted.internet.defer import inlineCallbacks, returnValue
from pipe2py.lib.utils import combine_dicts as cdicts

opts = {'ftype': None, 'listize': False}


# Async functions
@inlineCallbacks
def asyncPipeUniq(context=None, _INPUT=None, conf=None, **kwargs):
    """An operator that asynchronously returns a specified number of items from
    the top of a feed. Not loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : twisted Deferred iterable of items
    conf : {
        'start': {'type': 'number', value': <starting location>}
        'count': {'type': 'number', value': <desired feed length>}
    }

    returns
    -------
    _OUTPUT : twisted.internet.defer.Deferred generator of unique items
    """
    _input = yield _INPUT
    asyncFuncs = yield asyncGetSplits(None, conf, **cdicts(opts, kwargs))
    pieces = yield asyncFuncs[0]()
    _pass = yield asyncFuncs[2]()

    if _pass:
        _OUTPUT = _input
    else:
        start = int(pieces.start)
        stop = start + int(pieces.count)
        _OUTPUT = islice(_input, start, stop)

    returnValue(_OUTPUT)


# Synchronous functions
def pipe_truncate(context=None, _INPUT=None, conf=None, **kwargs):
    """An operator that returns a specified number of items from the top of a
    feed. Not loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : pipe2py.modules pipe like object (iterable of items)
    kwargs -- terminal, if the truncation value is wired in
    conf : {
        'start': {'type': 'number', value': <starting location>}
        'count': {'type': 'number', value': <desired feed length>}
    }

    Returns
    -------
    _OUTPUT : generator of items
    """
    funcs = get_splits(None, conf, **cdicts(opts, kwargs))
    pieces, _pass = funcs[0](), funcs[2]()

    if _pass:
        _OUTPUT = _INPUT
    else:
        try:
            start = int(pieces.start)
        except AttributeError:
            start = 0

        stop = start + int(pieces.count)
        _OUTPUT = islice(_INPUT, start, stop)

    return _OUTPUT
