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
from twisted.internet.defer import inlineCallbacks, returnValue, maybeDeferred

from . import get_splits, asyncGetSplits
from pipe2py.lib.utils import combine_dicts as cdicts

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


def parse_results(splits, **kwargs):
    for rules, item, _pass in splits:
        if _pass or not item:
            result = item
        else:
            result = reduce(partial(func, **kwargs), rules, item)

        yield result


# Async functions
@inlineCallbacks
def asyncPipeRename(context=None, _INPUT=None, conf=None, **kwargs):
    """An operator that asynchronously renames or copies fields in the input
    source. Not loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : asyncPipe like object (twisted Deferred iterable of items)
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
    splits = yield asyncGetSplits(_INPUT, conf['RULE'], **cdicts(opts, kwargs))
    _OUTPUT = yield maybeDeferred(parse_results, splits, **kwargs)
    returnValue(_OUTPUT)


# Synchronous functions
def pipe_rename(context=None, _INPUT=None, conf=None, **kwargs):
    """An operator that renames or copies fields in the input source.
    Not loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : pipe2py.modules pipe like object (iterable of items)
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
    _OUTPUT : generator of items
    """
    splits = get_splits(_INPUT, conf['RULE'], **cdicts(opts, kwargs))
    _OUTPUT = parse_results(splits, **kwargs)
    return _OUTPUT
