# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipestrregex
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=string
"""

import re
from itertools import imap
from pipe2py.lib import utils
from pipe2py.lib.dotdict import DotDict





def pipe_strregex(context=None, _INPUT=None, conf=None, **kwargs):
    """A string module that replaces text using regexes. Each has the general
    format: "In [field] replace [regex pattern] with [text]". Loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : iterable of items or strings
    conf : {
        'RULE': [
            {
                'match': {'value': <regex>},
                'replace': {'value': <'replacement'>}
            }
        ]
    }

    Yields
    ------
    _OUTPUT : replaced strings
    """
    conf = DotDict(conf)
    loop_with = kwargs.pop('with', None)
    rule_defs = imap(DotDict, utils.listize(conf['RULE']))

    func = lambda word, rule: re.sub(rule.match, rule.replace, word)

    for item in _INPUT:
        _input = DotDict(item)
        _with = item.get(loop_with, **kwargs) if loop_with else item
        word = utils.get_word(_with)
        rules = (utils.parse_conf(r, _input, **kwargs) for r in rule_defs)
        new_rules = utils.convert_rules(rules)
        yield reduce(func, new_rules, word)
