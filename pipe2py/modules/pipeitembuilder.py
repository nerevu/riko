# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipeitembuilder
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=sources#ItemBuilder
"""

from itertools import imap
from twisted.internet.defer import inlineCallbacks, returnValue
from . import get_broadcast_funcs as get_funcs
from pipe2py.lib import utils
from pipe2py.lib.dotdict import DotDict


# Common functions
def get_output(_INPUT, conf, **kwargs):
    finite = utils.make_finite(_INPUT)
    inputs = imap(DotDict, finite)
    get_pieces = get_funcs(conf['attrs'], **kwargs)[0]
    pieces = imap(get_pieces, inputs)
    results = imap(utils.parse_params, pieces)
    return imap(DotDict, results)


# Async functions
@inlineCallbacks
def asyncPipeItemBuilder(context=None, _INPUT=None, conf=None, **kwargs):
    """A source that asynchronously builds an item. Loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : asyncPipe like object (twisted Deferred iterable of items)
    conf : {
        'attrs': [
            {
                'key': {'value': 'title'},
                'value': {'value': 'new title'}
            }, {
                'key': {'value': 'description.content'},
                'value': {'value': 'new description'}
            }
        ]
    }

    Returns
    ------
    _OUTPUT : twisted.internet.defer.Deferred generator of items
    """
    _input = yield _INPUT
    _OUTPUT = get_output(_input, conf, **kwargs)
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
            {
                'key': {'value': 'title'},
                'value': {'value': 'new title'}
            }, {
                'key': {'value': 'description.content'},
                'value': {'value': 'new description'}
            }
        ]
    }

    Returns
    ------
    _OUTPUT : generator of items
    """
    _OUTPUT = get_output(_INPUT, conf, **kwargs)
    return _OUTPUT
