# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipeunion
    ~~~~~~~~~~~~~~~~~~~~~~~~~
    Provides methods for merging separate sources into a single list of items.

    http://pipes.yahoo.com/pipes/docs?doc=operators#Union
"""

from itertools import chain, ifilter, starmap
from twisted.internet.defer import inlineCallbacks, returnValue
from pipe2py.lib import utils


# Common functions
def get_output(_INPUT, **kwargs):
    others_filter = lambda x: x[0].startswith('_OTHER')
    others = ifilter(others_filter, kwargs.itertems())
    others_iter = starmap(lambda src, items: items, others)
    others_items = utils.multiplex(others_iter)
    input_items = utils.make_finite(_INPUT)
    return chain(input_items, others_items)


# Async functions
@inlineCallbacks
def asyncPipeUnion(context=None, _INPUT=None, conf=None, **kwargs):
    """An operator that asynchronously merges multiple source together.
    Not loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : asyncPipe like object (twisted Deferred iterable of items)
    conf : unused

    Keyword arguments
    -----------------
    _OTHER1 : asyncPipe like object
    _OTHER2 : etc.

    Returns
    -------
    _OUTPUT : twisted.internet.defer.Deferred generator of items
    """
    _input = yield _INPUT
    _OUTPUT = get_output(_input, **kwargs)
    returnValue(_OUTPUT)


# Synchronous functions
def pipe_union(context=None, _INPUT=None, conf=None, **kwargs):
    """An operator that merges multiple source together. Not loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT :  pipe2py.modules pipe like object (iterable of items)
    conf : unused

    Keyword arguments
    -----------------
    _OTHER1 : pipe2py.modules pipe like object
    _OTHER2 : etc.

    Returns
    -------
    _OUTPUT : generator of items
    """
    _OUTPUT = get_output(_INPUT, **kwargs)
    return _OUTPUT
