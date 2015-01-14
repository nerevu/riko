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

import re
from functools import partial
from itertools import imap, starmap
from twisted.internet.defer import inlineCallbacks, returnValue, maybeDeferred
from . import get_broadcast_funcs as get_funcs
from pipe2py.lib import utils
from pipe2py.lib.dotdict import DotDict
from pipe2py.twisted.utils import asyncGather


# Common functions
def get_parsed(_INPUT, conf, convert=True, **kwargs):
    inputs = imap(DotDict, _INPUT)
    pkwargs = utils.combine_dicts(kwargs, {'parse': False, 'ftype': 'pass'})
    broadcast_funcs = get_funcs(conf['RULE'], **pkwargs)
    splits = utils.broadcast(inputs, *broadcast_funcs)

    if convert:
        convert_func = partial(utils.convert_rules, recompile=True)
        dispatch_funcs = [convert_func, utils.passthrough, utils.passthrough]
        result = utils.dispatch(splits, *dispatch_funcs)
    else:
        result = splits

    return result


def get_substitutions(field, word, rules):
    replacement = reduce(utils.substitute, rules, word)
    return (field, replacement)


def get_groups(rules, item):
    field_groups = utils.group_by(list(rules), 'field').items()
    groups = starmap(lambda f, r: (f, item.get(f) or '', r), field_groups)
    return groups


# Async functions
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
    _input = yield _INPUT
    parsed = get_parsed(_input, conf, **kwargs)
    _OUTPUT = yield asyncGather(parsed, partial(maybeDeferred, parse_result))
    returnValue(iter(_OUTPUT))


# Synchronous functions
def parse_result(rules, item, _pass):
    if not _pass:
        groups = get_groups(rules, item)
        substitutions = starmap(get_substitutions, groups)
        list(starmap(item.set, substitutions))

    return item


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
    parsed = get_parsed(_INPUT, conf, **kwargs)
    _OUTPUT = utils.gather(parsed, parse_result)
    return _OUTPUT
