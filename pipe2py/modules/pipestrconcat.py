# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipestrconcat
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=string#StringBuilder
"""

# aka stringbuilder

from functools import partial
from itertools import starmap
from twisted.internet.defer import inlineCallbacks, returnValue, maybeDeferred
from . import get_splits, asyncGetSplits
from pipe2py.lib import utils
from pipe2py.twisted.utils import asyncStarMap


# Common functions
def parse_result(parts, _, _pass):
    if _pass:
        result = ''
    else:
        result = ''.join((p.get('x') for p in parts))

    return result


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
    pkwargs = {'ftype': None, 'parse': False, 'd_index': 'x'}
    combined = utils.combine_dicts(pkwargs, kwargs)
    splits = yield asyncGetSplits(_INPUT, conf['part'], **combined)
    _OUTPUT = yield asyncStarMap(partial(maybeDeferred, parse_result), splits)
    returnValue(iter(_OUTPUT))


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
    pkwargs = {'ftype': None, 'parse': False, 'd_index': 'x'}
    combined = utils.combine_dicts(pkwargs, kwargs)
    splits = get_splits(_INPUT, conf['part'], **combined)
    _OUTPUT = starmap(parse_result, splits)
    return _OUTPUT
