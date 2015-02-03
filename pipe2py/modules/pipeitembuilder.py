# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipeitembuilder
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=sources#ItemBuilder
"""

from itertools import imap
from twisted.internet.defer import inlineCallbacks, returnValue
from . import get_splits, asyncGetSplits
from pipe2py.lib import utils
from pipe2py.lib.dotdict import DotDict
from pipe2py.lib.utils import combine_dicts as cdicts
from pipe2py.twisted.utils import asyncImap

opts = {'ftype': None, 'listtize': True, 'finitize': True}


# Async functions
@inlineCallbacks
def asyncPipeItembuilder(context=None, _INPUT=None, conf=None, **kwargs):
    """A source that asynchronously builds an item. Loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : asyncPipe like object (twisted Deferred iterable of items)
    conf : {
        'attrs': [
            {'key': {'value': 'title'}, 'value': {'value': 'new title'}},
            {'key': {'value': 'desc.content'}, 'value': {'value': 'new desc'}}
        ]
    }

    Returns
    ------
    _OUTPUT : twisted.internet.defer.Deferred generator of items
    """
    pkwargs = cdicts(opts, kwargs)
    asyncFuncs = yield asyncGetSplits(None, conf['attrs'], **pkwargs)
    _input = yield _INPUT
    finite = utils.finitize(_input)
    inputs = imap(DotDict, finite)
    pieces = yield asyncImap(asyncFuncs[0], inputs)
    results = imap(utils.parse_params, pieces)
    _OUTPUT = imap(DotDict, results)
    returnValue(_OUTPUT)


# Synchronous functions
def pipe_itembuilder(context=None, _INPUT=None, conf=None, **kwargs):
    """A source that builds an item. Loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : pipeforever pipe or an iterable of items
    conf : {
        'attrs': [
            {'key': {'value': <'title'>}, 'value': {'value': <'chair'>}},
            {'key': {'value': <'color'>}, 'value': {'value': <'red'>}}
        ]
    }

    Returns
    ------
    _OUTPUT : generator of items
    """
    funcs = get_splits(None, conf['attrs'], **cdicts(opts, kwargs))
    finite = utils.finitize(_INPUT)
    inputs = imap(DotDict, finite)
    pieces = imap(funcs[0], inputs)
    results = imap(utils.parse_params, pieces)
    _OUTPUT = imap(DotDict, results)
    return _OUTPUT
