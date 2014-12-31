# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipestrregex
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=string
"""

import re
from functools import partial
from itertools import imap, repeat
from pipe2py.lib import utils
from pipe2py.lib.dotdict import DotDict


def parse_result(rules, word, _pass):
    func = lambda word, rule: re.sub(rule.match, rule.replace, word)
    return word if _pass else reduce(func, rules, word)


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

    Returns
    -------
    _OUTPUT : generator of replaced strings
    """
    conf = DotDict(conf)
    test = kwargs.pop('pass_if', None)
    loop_with = kwargs.pop('with', None)
    rule_defs = map(DotDict, utils.listize(conf['RULE']))
    get_with = lambda i: i.get(loop_with, **kwargs) if loop_with else i
    get_pass = partial(utils.get_pass, test=test)
    parse_conf = partial(utils.parse_conf, **kwargs)
    get_rules = lambda i: imap(parse_conf, rule_defs, repeat(i))
    funcs1 = [utils.convert_rules, utils.get_word, utils.passthrough]

    inputs = imap(DotDict, _INPUT)
    splits = utils.broadcast(inputs, get_rules, get_with, get_pass)
    parsed = utils.dispatch(splits, *funcs1)
    _OUTPUT = utils.gather(parsed, parse_result)
    return _OUTPUT
