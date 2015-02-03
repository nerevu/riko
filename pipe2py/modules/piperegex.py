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

from functools import partial
from itertools import starmap
from twisted.internet.defer import inlineCallbacks, returnValue, maybeDeferred
from . import (
    get_dispatch_funcs, get_async_dispatch_funcs, get_splits, asyncGetSplits)
from pipe2py.lib import utils
from pipe2py.lib.utils import combine_dicts as cdicts
from pipe2py.twisted.utils import asyncDispatch

opts = {'convert': False, 'ftype': 'pass'}
substitute = utils.multi_substitute
convert_func = partial(utils.convert_rules, recompile=False)


# Common functions
def get_groups(rules, item):
    field_groups = utils.group_by(list(rules), 'field').iteritems()
    return ((f, item.get(f) or '', r) for f, r in field_groups)


# Async functions
@inlineCallbacks
def asyncParseResult(rules, item, _pass):
    if not _pass:
        groups = get_groups(rules, item)
        substitutions = yield maybeDeferred(get_substitutions, groups)
        list(starmap(item.set, substitutions))

    returnValue(item)


@inlineCallbacks
def asyncPipeRegex(context=None, _INPUT=None, conf=None, **kwargs):
    """An operator that asynchronously replaces text in items using regexes.
    Each has the general format: "In [field] replace [match] with [replace]".
    Not loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : asyncPipe like object (twisted Deferred iterable of items)
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
    splits = yield asyncGetSplits(_INPUT, conf['RULE'], **cdicts(opts, kwargs))
    asyncConvert = partial(maybeDeferred, convert_func)
    asyncFuncs = get_async_dispatch_funcs('pass', asyncConvert)
    parsed = yield asyncDispatch(splits, *asyncFuncs)
    _OUTPUT = yield maybeDeferred(parse_results, parsed)
    returnValue(iter(_OUTPUT))


# Synchronous functions
def get_substitutions(groups):
    for field, word, rules in groups:
        values = utils.group_by(rules, 'flags').itervalues()
        replacement = reduce(substitute, values, word) if word else word
        yield (field, replacement)


def parse_results(parsed):
    for rules, item, _pass in parsed:
        if not _pass:
            groups = get_groups(rules, item)
            substitutions = get_substitutions(groups)
            list(starmap(item.set, substitutions))

        yield item


def pipe_regex(context=None, _INPUT=None, conf=None, **kwargs):
    """An operator that replaces text in items using regexes. Each has the
    general format: "In [field] replace [match] with [replace]". Not loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : pipe2py.modules pipe like object (iterable of items)
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
    splits = get_splits(_INPUT, conf['RULE'], **cdicts(opts, kwargs))
    parsed = utils.dispatch(splits, *get_dispatch_funcs('pass', convert_func))
    _OUTPUT = parse_results(parsed)
    return _OUTPUT
