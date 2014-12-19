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
from itertools import imap, repeat
from pipe2py.lib import utils
from pipe2py.lib.dotdict import DotDict


def func(item, rule):
    string = item.get(rule.field)
    replaced = re.sub(rule.match, rule.replace, string, rule.count)
    item.set(rule.field, replaced)
    return item


def parse_result(rules, item, _pass):
    return item if _pass else reduce(func, rules, item)


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
    conf = DotDict(conf)
    test = kwargs.pop('pass_if', None)
    rule_defs = imap(DotDict, utils.listize(conf['RULE']))
    get_pass = partial(utils.get_pass, test=test)
    parse_conf = partial(utils.parse_conf, **kwargs)
    get_rules = lambda i: imap(parse_conf, rule_defs, repeat(i))
    funcs = [utils.convert_rules, utils.passthrough, utils.passthrough]

    inputs = imap(DotDict, _INPUT)
    splits = utils.split_input(inputs, get_rules, utils.passthrough, get_pass)
    parsed = utils.parse_splits(splits, *funcs)
    _OUTPUT = utils.get_output(parsed, parse_result)
    return _OUTPUT
