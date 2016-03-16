# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
pipe2py.modules.piperegex
~~~~~~~~~~~~~~~~~~~~~~~~~
Provides functions for modifying the content of a field of a feed item using
regular expressions, a powerful type of pattern matching.

Think of it as search-and-replace on steriods. You can define multiple Regex
rules. Each has the general format: "In [field] replace [regex pattern] with
[text]".

Examples:
    basic usage::

        >>> from pipe2py.modules.piperegex import pipe
        >>>
        >>> match = r'(\w+)\s(\w+)'
        >>> rule = {'field': 'content', 'match': match, 'replace': '$2wide'}
        >>> conf = {'rule': rule}
        >>> pipe({'content': 'hello world'}, conf=conf).next()['content']
        u'worldwide'

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""

from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from . import processor
from pipe2py.lib import utils
from pipe2py.lib.utils import combine_dicts as cdicts
from pipe2py.lib.log import Logger
from pipe2py.twisted import utils as tu
from pipe2py.lib.dotdict import DotDict

OPTS = {'listize': True, 'extract': 'rule', 'emit': True}
DEFAULTS = {'convert': True, 'multi': False}
logger = Logger(__name__).logger


def parser(item, rules, skip, **kwargs):
    """ Parsers the pipe content

    Args:
        item (obj): The entry to process (a DotDict instance)
        rules (List[obj]): the parsed rules (Objectify instances).
        skip (bool): Don't parse the content
        kwargs (dict): Keyword arguments

    Kwargs:
        assign (str): Attribute to assign parsed content (default: exchangerate)
        feed (dict): The original item

    Returns:
        Tuple (dict, bool): Tuple of (item, skip)

    Examples:
        >>> from pipe2py.lib.utils import Objectify
        >>>
        >>> item = DotDict({'content': 'hello world', 'title': 'greeting'})
        >>> match = r'(\w+)\s(\w+)'
        >>> rule = {'field': 'content', 'match': match, 'replace': '$2wide'}
        >>> conf = {'rule': rule, 'multi': False, 'convert': True}
        >>> rules = [Objectify(rule)]
        >>> kwargs = {'feed': item, 'conf': conf}
        >>> regexed, skip = parser(item, rules, False, **kwargs)
        >>> regexed == {'content': 'worldwide', 'title': 'greeting'}
        True
        >>> conf['multi'] = True
        >>> parser(item, rules, False, **kwargs)[0] == regexed
        True
    """
    multi = kwargs['conf']['multi']
    recompile = not multi

    def meta_reducer(item, rules):
        field = rules[0]['field']
        word = item.get(field, **kwargs)
        grouped = utils.group_by(rules, 'flags')
        group_rules = [g[1] for g in grouped] if multi else rules
        reducer = utils.multi_substitute if multi else utils.substitute
        replacement = reduce(reducer, group_rules, word)
        return DotDict(cdicts(item, {field: replacement}))

    if skip:
        item = kwargs['feed']
    else:
        new_rules = [utils.get_new_rule(r, recompile=recompile) for r in rules]
        grouped = utils.group_by(new_rules, 'field')
        field_rules = [g[1] for g in grouped]
        item = reduce(meta_reducer, field_rules, item)

    return item, skip


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs):
    """A processor that replaces text in fields of a feed item using regexes.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'rule'. May
            contain the keys 'multi' or 'convert'.

            rule (dict): can be either a dict or list of dicts. Must contain
                the key 'field'.

                field (str): The item attribute to search
                match (str): The regex to apply
                replace (str): The string replacement
                globalmatch (bool): Find all matches (default: False)
                dotall (bool): Match newlines with '.' (default: False)
                singlelinematch (bool): Don't search across newlines with '^'
                    and '$' (default: False)
                casematch (bool): Perform case sensitive match (default: False)

            multi (bool): Efficiently combine multiple regexes (default: False)
            convert (bool): Convert regex into a Python compatible format
                (default: True)

    Yields:
        dict: an item with concatenated content

    Examples:
        >>> item = {'content': 'hello world', 'title': 'greeting'}
        >>> match = r'(\w+)\s(\w+)'
        >>> rule = {'field': 'content', 'match': match, 'replace': '$2wide'}
        >>> conf = {'rule': rule, 'multi': False, 'convert': True}
        >>> result = pipe(item, conf=conf).next()
        >>> result == {'content': u'worldwide', 'title': 'greeting'}
        True
        >>> conf['multi'] = True
        >>> pipe(item, conf=conf).next() == result
        True
        >>> item = {'content': 'Hello hello?'}
        >>> rule.update({'match': r'hello.+', 'replace': 'bye'})
        >>> pipe(item, conf=conf).next()['content']
        u'bye'
        >>> rule['casematch'] = True
        >>> pipe(item, conf=conf).next()['content']
        u'Hello bye'
    """
    return parser(*args, **kwargs)
