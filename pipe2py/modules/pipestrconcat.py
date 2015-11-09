# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipestrconcat
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=string#StringBuilder
"""

# aka stringbuilder

from __future__ import (
    absolute_import, division, print_function, with_statement,
    unicode_literals)

from functools import partial
from itertools import starmap, imap
from twisted.internet.defer import inlineCallbacks, returnValue, maybeDeferred
from . import get_splits, asyncGetSplits
from pipe2py.lib.utils import combine_dicts as cdicts
from pipe2py.twisted.utils import asyncStarMap

opts = {'ftype': None, 'parse': False, 'dictize': True}


def parse_result(parts, _, _pass):
    parts = list(parts)

    try:
        parsed = '' if _pass else ''.join(parts)
    except UnicodeDecodeError:
        decoded = [p.decode('utf-8') for p in parts]
        parsed = ''.join(decoded)

    return parsed


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
            {'value': <'<img src="'>},
            {'subkey': <'img.src'>},
            {'value': <'">'>}
        ]
    }

    Returns
    -------
    _OUTPUT : twisted.internet.defer.Deferred generator of joined strings
    """
    splits = yield asyncGetSplits(_INPUT, conf['part'], **cdicts(opts, kwargs))
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
            {'value': '<img src="'},
            {'subkey': 'img.src'},
            {'value': '">'}
        ]
    }

    Returns
    -------
    _OUTPUT : generator of joined strings
    """
    splits = get_splits(_INPUT, conf['part'], **cdicts(opts, kwargs))
    _OUTPUT = starmap(parse_result, splits)
    return _OUTPUT
