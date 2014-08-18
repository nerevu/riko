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
    """
    mode = conf['MODE']['value']
    combine = conf['COMBINE']['value']
    rules = []

    rule_defs = util.listize(conf['RULE'])

    for rule in rule_defs:
        field = rule['field']['value']
        value = util.get_value(rule['value'], None, **kwargs) #todo use subkey?
        rules.append((field, rule['op']['value'], value))

    for item in _INPUT:
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

    data = util.get_subkey(field, item)

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
