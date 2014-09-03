# pipestrreplace.py
#
from pipe2py import util
from pipe2py.lib.dotdict import DotDict

SWITCH = {
    '1': lambda item, rule: item.replace(rule[0], rule[2], 1),
    '2': lambda item, rule: util.rreplace(item, rule[0], rule[2], 1),
    '3': lambda item, rule: item.replace(rule[0], rule[2]),
    # todo: else assertion
}


def pipe_strreplace(context=None, _INPUT=None, conf=None, **kwargs):
    """Replaces text with replacement text.

    Keyword arguments:
    context -- pipeline context
    _INPUT -- source generator
    conf:
        RULE -- rules - each rule comprising (find, param, replace):
            find -- text to find
            param -- type of match: 1=first, 2=last, 3=every
            replace -- text to replace with

    Yields (_OUTPUT):
    source string with replacements
    """
    conf = DotDict(conf)
    fields = ['find', 'param', 'replace']
    rules = list(util.gen_rules(conf['RULE'], fields, **kwargs))

    for item in _INPUT:
        yield reduce(
            lambda x, y: x or y,
            (SWITCH.get(rule[1])(item, rule) for rule in rules),
            item
        )
