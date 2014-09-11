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
from pipe2py.lib.dotdict import DotDict


def _get_args(item, rule, sub_string, sub_func, key=False):
    content = item[rule[0]]['content'] if key else item[rule[0]]
    return (rule[0], re.sub(sub_string, sub_func, unicode(content)))


def _gen_rules(rule_defs, **kwargs):
    for rule in rule_defs:
        rule = DotDict(rule)

        # flags = re.DOTALL # DOTALL was the default for pipe2py previously
        # flag 'm'
        flags = re.MULTILINE if 'multilinematch' in rule else 0

        # flag 'i'; this name is reversed from its meaning
        flags |= re.IGNORECASE if 'casematch' in rule else 0

        # flag 's'
        flags |= re.DOTALL if 'singlelinematch' in rule else 0

        # todo: 'globalmatch' is the default in python
        # todo: if set, re.sub() below would get count=0 and by default would
        # get count=1

        # todo: use subkey?
        match = rule.get('match', **kwargs)

        # compile for speed and we need to pass flags
        matchc = re.compile(match, flags)

        # todo: use subkey?
        replace = rule.get('replace', **kwargs) or ''

        # Convert regex to Python format
        # todo: use a common routine for this
        # map $1 to \1 etc.
        # todo: also need to escape any existing \1 etc.
        replace = re.sub('\$(\d+)', r'\\\1', replace)
        yield (rule.get('filed'), matchc, replace)


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
    rule_defs = util.listize(conf['RULE'])

    # use list bc iterator gets used up if there are no matching feeds
    rules = list(_gen_rules(rule_defs, **kwargs))

    for item in _INPUT:
        item = DotDict(item)

        def sub_fields(matchobj):
            return item.get(matchobj.group(1), **kwargs)

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
                sub_string = '\$\{(.+?)\}'

                if (
                    hasattr(item[rule[0]], 'keys')
                    and 'content' in item[rule[0]]
                ):
                    # this looks like an HTML node, so only do substitution on
                    # the content of the node possible gotcha: the content
                    # might be a subtree, in which case we revert to modifying
                    # the literal of the subtree dict
                    args1 = _get_args(item, rule, rule[1], rule[2], 'content')
                    args2 = _get_args(item, rule, sub_string, sub_fields)
                else:
                    args1 = _get_args(item, rule, rule[1], rule[2])
                    args2 = _get_args(item, rule, sub_string, sub_fields)

                item.set(*args1)
                item.set(*args2)

        yield item
