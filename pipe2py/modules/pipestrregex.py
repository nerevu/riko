# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipestrregex
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=string
"""

import re
from pipe2py import util
from pipe2py.lib.dotdict import DotDict


def _gen_rules(rule_defs, **kwargs):
    rule_defs = util.listize(rule_defs)

    # todo: compile regex here: c = re.compile(match)
    # todo: use subkey?
    for rule in rule_defs:
        rule = DotDict(rule)
        match = rule.get('match', **kwargs)
        replace = rule.get('replace', **kwargs)

        # Convert regex to Python format
        # todo: use a common routine for this, e.g., map $1 to \1 etc.
        # todo: also need to escape any existing \1 etc.
        replace = re.sub('\$(\d+)', r'\\\1', replace) or ''
        yield (match, replace)


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
    rules = _gen_rules(conf['RULE'], **kwargs)

    for item in _INPUT:
        for rule in rules:
            match, replace = rule
            item = re.sub(match, replace, item)

        yield item
