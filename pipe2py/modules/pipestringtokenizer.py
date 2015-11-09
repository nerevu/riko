# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipestringtokenizer
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=string#StringTokenizer
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

opts = {'listize': False, 'finitize': True}


# Common functions
def parse_result(conf, word, _pass):
    if _pass:
        token = None
    else:
        splits = filter(None, word.split(conf.delimiter))

        try:
            chunks = set(splits) if conf.dedupe else splits
        except AttributeError:
            chunks = splits

        try:
            chunks = sorted(chunks) if conf.sort else chunks
        except AttributeError:
            chunks = chunks

        token = [{'content': chunk} for chunk in chunks] or [{}]

    return token


# Async functions
@inlineCallbacks
def asyncPipeStringtokenizer(context=None, _INPUT=None, conf=None, **kwargs):
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
    conf['delimiter'] = conf.pop('to-str', dict.get(conf, 'delimiter'))
    splits = yield asyncGetSplits(_INPUT, conf, **cdicts(opts, kwargs))
    parsed = yield asyncDispatch(splits, *get_async_dispatch_funcs())
    items = yield asyncStarMap(partial(maybeDeferred, parse_result), parsed)
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
    conf['delimiter'] = conf.pop('to-str', dict.get(conf, 'delimiter'))
    splits = get_splits(_INPUT, conf, **cdicts(opts, kwargs))
    parsed = utils.dispatch(splits, *get_dispatch_funcs())
    items = starmap(parse_result, parsed)
    _OUTPUT = utils.multiplex(items)
    return _OUTPUT
