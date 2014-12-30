# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipestrreplace
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=string
"""

from itertools import imap
from pipe2py.lib import utils
from pipe2py.lib.dotdict import DotDict

SWITCH = {
    '1': lambda word, rule: word.replace(rule.find, rule.replace, 1),
    '2': lambda word, rule: utils.rreplace(word, rule.find, rule.replace, 1),
    '3': lambda word, rule: word.replace(rule.find, rule.replace),
    # todo: else assertion
}


def pipe_strreplace(context=None, _INPUT=None, conf=None, **kwargs):
    """A string module that replaces text. Loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : iterable of items or strings
    conf : {
        'RULE': [
            {
                'param': {'value': <match type: 1=first, 2=last, 3=every>},
                'find': {'value': <text to find>},
                'replace': {'value': <replacement>}
            }
        ]
    }

    Yields
    ------
    _OUTPUT : replaced strings
    """
    conf = DotDict(conf)
    test = kwargs.pop('pass_if', None)
    loop_with = kwargs.pop('with', None)
    rule_defs = imap(DotDict, utils.listize(conf['RULE']))

    func = lambda word, rule: SWITCH.get(rule.param)(word, rule)

    for item in _INPUT:
        if utils.get_pass(item, test):
            yield
            continue

        _input = DotDict(item)
        _with = item.get(loop_with, **kwargs) if loop_with else item
        word = utils.get_word(_with)
        rules = (utils.parse_conf(r, _input, **kwargs) for r in rule_defs)
        yield reduce(func, rules, word)
