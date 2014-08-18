# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.piperegex
    ~~~~~~~~~~~~~~

    Provides methods for modifing fields in a feed using regular
    expressions, a powerful type of pattern matching.
    Think of it as search-and-replace on steriods.
    You can define multiple Regex rules.
    Each has the general format: "In [field] replace [regex pattern] with
    [text]".

    http://pipes.yahoo.com/pipes/docs?doc=operators#Regex
"""

import re
from pipe2py import util


def pipe_regex(context=None, _INPUT=None, conf=None, **kwargs):
    """Applies regex rules to _INPUT items.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : source generator of dicts
    conf: dict
        {
            'RULE': [
                {
                    'field': {'value': 'search field'},
                    'match': {'value': 'regex'},
                    'replace': {'value': 'replacement'}
                }
            ]
        }

    Yields
    ------
    _OUTPUT : source pipe items post regexes application
    """
    rules = []

    rule_defs = conf['RULE']
    if not isinstance(rule_defs, list):
        rule_defs = [rule_defs]

    for rule in rule_defs:
        # flags = re.DOTALL # DOTALL was the default for pipe2py previously
        flags = 0

        # flag 'm'
        if 'multilinematch' in rule:
            flags |= re.MULTILINE

        # flag 'i'; this name is reversed from its meaning
        if 'casematch' in rule:
            flags |= re.IGNORECASE

        # flag 's'
        if 'singlelinematch' in rule:
            flags |= re.DOTALL
        #todo 'globalmatch' is the default in python
        #todo if set, re.sub() below would get count=0 and by default would get count=1

        match = util.get_value(rule['match'], None, **kwargs) #todo use subkey?
        matchc = re.compile(match, flags)  #compile for speed and we need to pass flags
        replace = util.get_value(rule['replace'], None, **kwargs) #todo use subkey?
        if replace is None:
            replace = ''

        #convert regex to Python format: todo use a common routine for this
        replace = re.sub('\$(\d+)', r'\\\1', replace)   #map $1 to \1 etc.   #todo: also need to escape any existing \1 etc.

        rules.append((rule['field']['value'], matchc, replace))

    for item in _INPUT:
        def sub_fields(matchobj):
            return util.get_value({'subkey':matchobj.group(1)}, item)

        for rule in rules:
            # todo: do we ever need get_value here instead of item[]?
            # when the subject being examined is an HTML node, not a
            # string then the unicode() converts the dict representing the node
            # to a dict literal, and then attempts to apply the pattern
            # to the literal; as an HTML element node, it may have attributes
            # which then appear in the literal. It should be only matching on
            # (and replacing the value of) the `.content` subelement
            # I'm not confident that what is below will work across the board
            # nor if this is the right way to detect that we're looking at
            # an HTML node and not a plain string
            if rule[0] in item and item[rule[0]]:
                if (
                    isinstance(item[rule[0]], dict)
                    and 'content' in item[rule[0]]
                ):
                    # this looks like an HTML node, so only do substitution on
                    # the content of the node possible gotcha: the content
                    # might be a subtree, in which case we revert to modifying
                    # the literal of the subtree dict
                    util.set_value(item, rule[0], re.sub(rule[1], rule[2], unicode(item[rule[0]]['content'])))
                    util.set_value(item, rule[0], re.sub('\$\{(.+?)\}', sub_fields, unicode(item[rule[0]])))
                else:
                    util.set_value(item, rule[0], re.sub(rule[1], rule[2], unicode(item[rule[0]])))
                    util.set_value(item, rule[0], re.sub('\$\{(.+?)\}', sub_fields, unicode(item[rule[0]])))
        yield item

