# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipesubstr
    ~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=string#SubString
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
    start = int(conf.start)
    end = int(conf.start + conf.length)

    try:
        parsed = word if _pass else word[start:end]
    except UnicodeDecodeError:
        parsed = word.decode('utf-8')[start:end]

    return parsed


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
    conf['start'] = conf.pop('from', dict.get(conf, 'start'))
    splits = yield asyncGetSplits(_INPUT, conf, **cdicts(opts, kwargs))
    parsed = yield asyncDispatch(splits, *get_async_dispatch_funcs())
    _OUTPUT = yield asyncStarMap(partial(maybeDeferred, parse_result), parsed)
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
    conf['start'] = conf.pop('from', dict.get(conf, 'start'))
    splits = get_splits(_INPUT, conf, **cdicts(opts, kwargs))
    parsed = utils.dispatch(splits, *get_dispatch_funcs())
    _OUTPUT = starmap(parse_result, parsed)
    return _OUTPUT
