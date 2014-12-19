# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipestrreplace
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=string
"""

from pipe2py.lib import utils
from pipe2py.lib.dotdict import DotDict

SWITCH = {
    '1': lambda item, rule: item.replace(rule[0], rule[2], 1),
    '2': lambda item, rule: utils.rreplace(item, rule[0], rule[2], 1),
    '3': lambda item, rule: item.replace(rule[0], rule[2]),
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
    fields = ['find', 'param', 'replace']
    rule_defs = [DotDict(rule_def) for rule_def in utils.listize(conf['RULE'])]

    # use list bc iterator gets used up if there are no matching feeds
    rules = list(utils.gen_rules(rule_defs, fields, **kwargs))

    for item in _INPUT:
        yield reduce(
            lambda x, y: x or y,
            (SWITCH.get(rule[1])(item, rule) for rule in rules),
            item
        )
