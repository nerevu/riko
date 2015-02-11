# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipeuniq
    ~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=operators#Unique
"""

from . import get_splits, asyncGetSplits
from twisted.internet.defer import inlineCallbacks, returnValue
from pipe2py.lib.utils import combine_dicts as cdicts

opts = {'ftype': None, 'listize': False}


# Common functions
def unique_items(items, field):
    seen = set()

    for item in items:
        value = item.get(field)

        if value not in seen:
            seen.add(value)
            yield item


# Async functions
@inlineCallbacks
def asyncPipeUniq(context=None, _INPUT=None, conf=None, **kwargs):
    """An operator that asynchronously filters out non unique items according
    to the specified field. Not loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : twisted Deferred iterable of items
    conf : {'field': {'type': 'text', 'value': <field to be unique>}}

    returns
    -------
    _OUTPUT : twisted.internet.defer.Deferred generator of unique items
    """
    _input = yield _INPUT
    asyncFuncs = yield asyncGetSplits(None, conf, **cdicts(opts, kwargs))
    pieces = yield asyncFuncs[0]()
    _pass = yield asyncFuncs[2]()
    _OUTPUT = _input if _pass else unique_items(_input, pieces.field)
    returnValue(_OUTPUT)


# Synchronous functions
def pipe_uniq(context=None, _INPUT=None, conf=None, **kwargs):
    """An operator that filters out non unique items according to the specified
    field. Not loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : pipe2py.modules pipe like object (iterable of items)
    kwargs -- other inputs, e.g. to feed terminals for rule values
    conf : {'field': {'type': 'text', 'value': <field to be unique>}}

    Returns
    -------
    _OUTPUT : generator of unique items
    """
    funcs = get_splits(None, conf, **cdicts(opts, kwargs))
    pieces, _pass = funcs[0](), funcs[2]()
    _OUTPUT = _INPUT if _pass else unique_items(_INPUT, pieces.field)
    return _OUTPUT
