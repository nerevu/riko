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
from itertools import imap
from pipe2py.lib import utils
from pipe2py.lib.dotdict import DotDict


def func(item, rule):
    string = item.get(rule.field)
    replaced = re.sub(rule.match, rule.replace, string, rule.count)
    item.set(rule.field, replaced)
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

    Yields
    ------
    _OUTPUT : items
    """
    conf = DotDict(conf)
    test = kwargs.pop('pass_if', None)
    rule_defs = imap(DotDict, utils.listize(conf['RULE']))

    for item in _INPUT:
        if utils.get_pass(item, test):
            yield item
            continue

        item = DotDict(item)
        rules = (utils.parse_conf(r, item, **kwargs) for r in rule_defs)
        new_rules = utils.convert_rules(rules)
        yield reduce(func, new_rules, item)
