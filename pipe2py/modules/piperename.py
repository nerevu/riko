# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.piperename
    ~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=operators#Rename
"""

from functools import partial
from itertools import imap
from twisted.internet.defer import inlineCallbacks, returnValue, maybeDeferred
from . import get_broadcast_funcs as get_funcs
from pipe2py.lib import utils
from pipe2py.lib.dotdict import DotDict
from pipe2py.twisted.utils import asyncGather


# Common functions
def get_splits(_INPUT, conf, **kwargs):
    inputs = imap(DotDict, _INPUT)
    broadcast_funcs = get_funcs(conf['RULE'], ftype='pass', **kwargs)
    return utils.broadcast(inputs, *broadcast_funcs)


def func(item, rule, **kwargs):
    try:
        item.set(rule.newval, item.get(rule.field, **kwargs))
    except (IndexError):
        # Catch error when 'newval' is blank (equivalent to deleting field)
        pass

    if rule.op == 'rename':
        item.delete(rule.field)

    return item


def parse_result(rules, item, _pass, **kwargs):
    return item if _pass else reduce(partial(func, **kwargs), rules, item)


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
    _input = yield _INPUT
    splits = get_splits(_input, conf, **kwargs)
    _OUTPUT = yield asyncGather(splits, partial(maybeDeferred, parse_result))
    returnValue(iter(_OUTPUT))


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
    splits = get_splits(_INPUT, conf, **kwargs)
    _OUTPUT = utils.gather(splits, partial(parse_result, **kwargs))
    return _OUTPUT
