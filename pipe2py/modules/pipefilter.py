# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipefilter
    ~~~~~~~~~~~~~~

    Provides methods for filtering (including or excluding) items from a feed.

    http://pipes.yahoo.com/pipes/docs?doc=operators#Filter
"""

import datetime
import re

from pipe2py import util
from decimal import Decimal
from pipe2py.lib.dotdict import DotDict

COMBINE_BOOLEAN = {"and": all, "or": any}


def pipe_filter(context=None, _INPUT=None, conf=None, **kwargs):
    """Filters for _INPUT items matching the given rules.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : source generator of dicts
    conf : dict
        {
            'MODE': {'value': 'permit' or 'block'},
            'COMBINE': {'value': 'and' or 'or'}
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
    _OUTPUT : source pipe items matching the rules

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
    >>> rule = [{'field': {'value': 'title'}, 'op': {'value': 'contains'}, 'value': {'value': 'web'}}]
    >>> conf = {'MODE': mode, 'COMBINE': combine, 'RULE': rule}
    >>> pipe_filter(_INPUT=input, conf=conf).next()['title']
    u'E-Commerce Website Developer | Elance Job'
    >>> rule = [{'field': {'value': 'title'}, 'op': {'value': 'contains'}, 'value': {'value': 'kjhlked'}}]
    >>> conf = {'MODE': mode, 'COMBINE': combine, 'RULE': rule}
    >>> list(pipe_filter(_INPUT=input, conf=conf))
    []
    """
    conf = DotDict(conf)
    mode = conf.get('MODE')
    combine = conf.get('COMBINE')
    rules = []

    rule_defs = util.listize(conf['RULE'])

    for rule in rule_defs:
        rule = DotDict(rule)
        field = rule.get('field', **kwargs)
        op = rule.get('op', **kwargs)
        value = rule.get('value', **kwargs)
        rules.append((field, op, value))

    for item in _INPUT:
        item = DotDict(item)
        if combine in COMBINE_BOOLEAN:
            res = COMBINE_BOOLEAN[combine](_rulepass(rule, item) for rule in rules)
        else:
            raise Exception(
                "Invalid combine: %s (expecting 'and' or 'or')" % combine)

        if (res and mode == "permit") or (not res and mode == "block"):
            yield item

#todo precompile these into lambdas for speed
def _rulepass(rule, item):
    field, op, value = rule
    data = item.get(field)

    if data is None:
        return False

    #todo check which of these should be case insensitive
    if op == "contains":
        try:
            if value.lower() and value.lower() in data.lower():  #todo use regex?
                return True
        except UnicodeDecodeError:
            pass
    if op == "doesnotcontain":
        try:
            if value.lower() and value.lower() not in data.lower():  #todo use regex?
                return True
        except UnicodeDecodeError:
            pass
    if op == "matches":
        if re.search(value, data):
            return True
    if op == "is":
        if data == value:
            return True
    if op == "greater":
        try:
            if Decimal(data) > Decimal(value):
                return True
        except:
            if data > value:
                return True
    if op == "less":
        try:
            if Decimal(data) < Decimal(value):
                return True
        except:
            if data < value:
                return True
    if op == "after":
        #todo handle partial datetime values
        if isinstance(value, basestring):
            value = datetime.datetime.strptime(value, util.DATE_FORMAT).timetuple()
        if data > value:
            return True
    if op == "before":
        #todo handle partial datetime values
        if isinstance(value, basestring):
            value = datetime.datetime.strptime(value, util.DATE_FORMAT).timetuple()
        if data < value:
            return True

    return False
