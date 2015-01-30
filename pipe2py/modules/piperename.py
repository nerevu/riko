# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.piperename
    ~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=operators#Rename
"""

from __future__ import (
    absolute_import, division, print_function, with_statement,
    unicode_literals)

from functools import partial
from twisted.internet.defer import inlineCallbacks, returnValue
from . import get_split, get_dispatch_funcs
from pipe2py.lib.utils import combine_dicts as cdicts
from pipe2py.twisted import utils as tu

opts = {'ftype': 'pass', 'dictize': True}


# Common functions
def func(item, rule, **kwargs):
    try:
        item.set(rule.newval, item.get(rule.field, **kwargs))
    except (IndexError):
        # Catch error when 'newval' is blank (equivalent to deleting field)
        pass

    if rule.op == 'rename':
        item.delete(rule.field)

    return item


# Async functions
def asyncParseResult(rules, item, _pass, **kwargs):
    reduce_func = partial(func, **kwargs)
    if _pass:
        # return tu.asyncReturn(item)
        result = tu.asyncReturn(item)
        return result
    else:
        result = tu.coopReduce(reduce_func, rules, item)
        return result


@inlineCallbacks
def asyncPipeRename(context=None, item=None, conf=None, **kwargs):
    """An operator that asynchronously renames or copies fields in the input
    source. Not loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    item : asyncPipe like object (twisted Deferred iterable of items)
    conf : {
        'RULE': [
            {
                'op': {'value': 'rename or copy'},
                'field': {'value': 'old field'},
                'newval': {'value': 'new field'}
            }
        ]
    }

    kwargs : other inputs, e.g., to feed terminals for rule values

    Returns
    -------
    _OUTPUT : twisted.internet.defer.Deferred generator of items
    """
    pkwargs = cdicts(opts, kwargs, {'async': False})
    split = get_split(item, conf['RULE'], **pkwargs)
    # asyncFuncs = get_dispatch_funcs('pass', async=True)
    # parsed = yield tu.asyncDispatch(split, *asyncFuncs)
    _OUTPUT = yield asyncParseResult(*split, **kwargs)
    # print _OUTPUT
    returnValue(_OUTPUT)


# Synchronous functions
def parse_result(rules, item, _pass, **kwargs):
    reduce_func = partial(func, **kwargs)
    return item if _pass or not item else reduce(reduce_func, rules, item)


def pipe_rename(context=None, item=None, conf=None, **kwargs):
    """An operator that renames or copies item fields. Not loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    item : dict
    conf : {
        'RULE': [
            {
                'op': {'value': 'rename or copy'},
                'field': {'value': 'old field'},
                'newval': {'value': 'new field'}
            }
        ]
    }

    kwargs : other inputs, e.g., to feed terminals for rule values

    Returns
    -------
    _OUTPUT : item
    """
    split = get_split(item, conf['RULE'], **cdicts(opts, kwargs))
    _OUTPUT = parse_result(*split, **kwargs)
    return _OUTPUT
