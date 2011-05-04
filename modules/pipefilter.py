# pipefilter.py
#

import datetime
import re
from pipe2py import util
from decimal import Decimal

COMBINE_BOOLEAN = {"and": all, "or": any}

def pipe_filter(context, _INPUT, conf, **kwargs):
    """This operator filters the input source, including or excluding fields, that match a set of defined rules. 

    Keyword arguments:
    context -- pipeline context        
    _INPUT -- source generator
    kwargs -- other inputs, e.g. to feed terminals for rule values
    conf:
        MODE -- filter mode, either "permit" or "block"
        COMBINE -- filter boolean combination, either "and" or "or"
        RULE -- rules - each rule comprising (field, op, value)
    
    Yields (_OUTPUT):
    source items that match the rules
    """
    mode = conf['MODE']['value']
    combine = conf['COMBINE']['value']
    rules = []

    rule_defs = conf['RULE']
    if not isinstance(rule_defs, list):
        rule_defs = [rule_defs]
    
    for rule in rule_defs:
        field = rule['field']['value']
        value = util.get_value(rule['value'], None, **kwargs) #todo use subkey?
        rules.append((field, rule['op']['value'], value))
    
    for item in _INPUT:
        if combine in COMBINE_BOOLEAN: 
            res = COMBINE_BOOLEAN[combine](_rulepass(rule, item) for rule in rules)
        else:
            raise Exception("Invalid combine %s (expecting and or or)" % combine)

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

