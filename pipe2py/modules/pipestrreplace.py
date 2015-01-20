# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipestrreplace
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=string#StringReplace
"""

from functools import partial
from itertools import imap, repeat
from pipe2py.lib import utils
from pipe2py.lib.dotdict import DotDict

SWITCH = {
    '1': lambda word, rule: word.replace(rule.find, rule.replace, 1),
    '2': lambda word, rule: utils.rreplace(word, rule.find, rule.replace, 1),
    '3': lambda word, rule: word.replace(rule.find, rule.replace),
    # todo: else assertion
}


def parse_result(rules, word, _pass):
    func = lambda word, rule: SWITCH.get(rule.param)(word, rule)
    return word if _pass else reduce(func, rules, word)


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
    funcs = [get_rules, utils.get_word, utils.passthrough]

    splits = utils.broadcast(_INPUT, DotDict, get_with, get_pass)
    parsed = utils.dispatch(splits, *funcs)
    _OUTPUT = utils.gather(parsed, parse_result)
    return _OUTPUT
