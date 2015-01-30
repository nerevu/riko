# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.piperegex
    ~~~~~~~~~~~~~~~~~~~~~~~~~

    Provides methods for modifying fields in a feed using regular
    expressions, a powerful type of pattern matching.
    Think of it as search-and-replace on steroids.
    You can define multiple Regex rules.

    http://pipes.yahoo.com/pipes/docs?doc=operators#Regex
"""

from __future__ import (
    absolute_import, division, print_function, with_statement,
    unicode_literals)

from functools import partial
from itertools import starmap
from twisted.internet import defer as df
from twisted.internet.defer import inlineCallbacks, returnValue
from . import get_dispatch_funcs, get_split
from pipe2py.lib import utils
from pipe2py.lib.utils import combine_dicts as cdicts
from pipe2py.twisted import utils as tu

opts = {'convert': False, 'ftype': 'pass', 'dictize': True}
substitute = utils.multi_substitute
convert_func = partial(utils.convert_rules, recompile=False)


# Common functions
def get_groups(rules, item):
    field_groups = utils.group_by(list(rules), 'field').iteritems()
    return ((f, item.get(f) or '', r) for f, r in field_groups)


# Async functions
@inlineCallbacks
def asyncGetReplacement(field, word, rules):
    values = utils.group_by(rules, 'flags').itervalues()

    if word:
        replacement = yield tu.coopReduce(substitute, values, word)
    else:
        replacement = yield tu.asyncReturn(word)

    returnValue(tuple(field, replacement))


@inlineCallbacks
def asyncParseResult(rules, item, _pass):
    if not _pass:
        groups = get_groups(rules, item)
        substitutions = yield tu.asyncStarMap(asyncGetReplacement, groups)
        list(starmap(item.set, substitutions))

    returnValue(item)


@inlineCallbacks
def asyncPipeRegex(context=None, item=None, conf=None, **kwargs):
    """An operator that asynchronously replaces text in items using regexes.
    Each has the general format: "In [field] replace [match] with [replace]".
    Not loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    item : asyncPipe like object (twisted Deferred iterable of items)
    conf : {
        'RULE': [
            {
                'field': {'value': <'search field'>},
                'match': {'value': <'regex'>},
                'replace': {'value': <'replacement'>},
                'globalmatch': {'value': '1'},
                'singlelinematch': {'value': '2'},
                'multilinematch': {'value': '4'},
                'casematch': {'value': '8'}
            }
        ]
    }

    Returns
    -------
    _OUTPUT : twisted.internet.defer.Deferred generator of items
    """
    pkwargs = cdicts(opts, kwargs, {'async': True})
    split = get_split(item, conf['RULE'], **pkwargs)
    asyncConvert = partial(df.maybeDeferred, convert_func)
    asyncFuncs = get_dispatch_funcs('pass', asyncConvert, async=True)
    parsed = yield tu.asyncDispatch(split, *asyncFuncs)
    _OUTPUT = yield asyncParseResult(*parsed)
    returnValue(_OUTPUT)


# Synchronous functions
def get_replacement(field, word, rules):
    values = utils.group_by(rules, 'flags').itervalues()
    replacement = reduce(substitute, values, word) if word else word
    return (field, replacement)


def parse_result(rules, item, _pass):
    if not _pass:
        groups = get_groups(rules, item)
        substitutions = starmap(get_replacement, groups)
        list(starmap(item.set, substitutions))

    return item


def pipe_regex(context=None, item=None, conf=None, **kwargs):
    """An operator that replaces text in items using regexes. Each has the
    general format: "In [field] replace [match] with [replace]". Not loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    item : pipe2py.modules pipe like object (iterable of items)
    conf : {
        'RULE': [
            {
                'field': {'value': <'search field'>},
                'match': {'value': <'regex'>},
                'replace': {'value': <'replacement'>},
                'globalmatch': {'value': '1'},
                'singlelinematch': {'value': '2'},
                'multilinematch': {'value': '4'},
                'casematch': {'value': '8'}
            }
        ]
    }

    Returns
    -------
    _OUTPUT : generator of items
    """
    split = get_split(item, conf['RULE'], **cdicts(opts, kwargs))
    funcs = get_dispatch_funcs('pass', convert_func)
    parsed = utils.dispatch(split, *funcs)
    _OUTPUT = parse_result(*parsed)
    return _OUTPUT

