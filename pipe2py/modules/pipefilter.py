# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipefilter
    ~~~~~~~~~~~~~~~~~~~~~~~~~~

    Provides methods for filtering (including or excluding) items from a feed.

    http://pipes.yahoo.com/pipes/docs?doc=operators#Filter
"""

import re

from datetime import datetime as dt
from decimal import Decimal, InvalidOperation
from itertools import imap
from pipe2py.lib import utils
from pipe2py.lib.dotdict import DotDict


COMBINE_BOOLEAN = {'and': all, 'or': any}
SWITCH = {
    # todo: check which of these should be case insensitive
    # todo: use regex?
    'contains': lambda x, y: x and x.lower() in y.lower(),
    'doesnotcontain': lambda x, y: x and x.lower() not in y.lower(),
    'matches': lambda x, y: re.search(x, y),
    'is': lambda x, y: cmp(x, y) is 0,
    'greater': lambda x, y: cmp(x, y) is -1,
    'less': lambda x, y: cmp(x, y) is 1,
    'after': lambda x, y: cmp(x, y) is -1,
    'before': lambda x, y: cmp(x, y) is 1,
}


def _gen_rulepass(rules, item):
    for rule in rules:
        if not rule.value:
            yield True
            continue

        try:
            x = Decimal(rule.value)
            y = Decimal(item.get(rule.field))
        except InvalidOperation:
            x = rule.value
            y = item.get(rule.field)

        if y is None:
            yield False
            continue
        elif isinstance(y, basestring):
            try:
                y = dt.strptime(y, utils.DATE_FORMAT).timetuple()
            except ValueError:
                pass

        try:
            yield SWITCH.get(rule.op)(x, y)
        except (UnicodeDecodeError, AttributeError):
            yield False


def pipe_filter(context=None, _INPUT=None, conf=None, **kwargs):
    """An operator that filters for source items matching the given rules.
    Not loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : pipe2py.modules pipe like object (iterable of items)
    conf : {
        'MODE': {'value': <'permit' or 'block'>},
        'COMBINE': {'value': <'and' or 'or'>}
        'RULE': [
            {
                'field': {'value': 'search field'},
                'op': {'value': 'one of SWITCH above'},
                'value': {'value': 'search term'}
            }
        ]
    }

    kwargs : other inputs, e.g., to feed terminals for rule values

    Yields
    ------
    _OUTPUT : items

    Examples
    --------
    >>> import os.path as p
    >>> from pipe2py.modules.pipeforever import pipe_forever
    >>> from pipe2py.modules.pipefetchdata import pipe_fetchdata
    >>> parent = p.dirname(p.dirname(__file__))
    >>> file_name = p.abspath(p.join(parent, 'data', 'gigs.json'))
    >>> path = 'value.items'
    >>> url = 'file://%s' % file_name
    >>> conf = {'URL': {'value': url}, 'path': {'value': path}}
    >>> input = pipe_fetchdata(_INPUT=pipe_forever(), conf=conf)
    >>> mode = {'value': 'permit'}
    >>> combine = {'value': 'and'}
    >>> rule = [{'field': {'value': 'title'}, 'op': {'value': 'contains'}, \
'value': {'value': 'web'}}]
    >>> conf = {'MODE': mode, 'COMBINE': combine, 'RULE': rule}
    >>> pipe_filter(_INPUT=input, conf=conf).next()['title']
    u'E-Commerce Website Developer | Elance Job'
    >>> rule = [{'field': {'value': 'title'}, 'op': {'value': 'contains'}, \
'value': {'value': 'kjhlked'}}]
    >>> conf = {'MODE': mode, 'COMBINE': combine, 'RULE': rule}
    >>> list(pipe_filter(_INPUT=input, conf=conf))
    []
    """
    conf = DotDict(conf)
    mode = conf.get('MODE', **kwargs)
    combine = conf.get('COMBINE', **kwargs)
    rule_defs = imap(DotDict, utils.listize(conf['RULE']))

    for item in _INPUT:
        item = DotDict(item)
        rules = (utils.parse_conf(r, item, **kwargs) for r in rule_defs)

        if combine in COMBINE_BOOLEAN:
            generated_rules = _gen_rulepass(rules, DotDict(item))
            res = COMBINE_BOOLEAN[combine](generated_rules)
        else:
            raise Exception(
                "Invalid combine: %s. (Expected 'and' or 'or')" % combine)

        if (res and mode == 'permit') or (not res and mode == 'block'):
            yield item
