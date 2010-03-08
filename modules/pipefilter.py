# pipefilter.py
#

import datetime
import re
from pipe2py import util

DATE_FORMAT = "%m/%d/%Y"
DATETIME_FORMAT = DATE_FORMAT + " %H:%M:%S"
COMBINE_BOOLEAN = {"and": all, "or": any}
FIELD_MAP = {'pubDate': 'date_parsed',
             }

def pipe_filter(_INPUT, conf, **kwargs):
    """This operator filters the input source, including or excluding fields, that match a set of defined rules. 

    Keyword arguments:
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
       
    for rule in conf['RULE']:
        value = get_value(rule['value'], kwargs) #todo use subkey?

        rules.append((rule['field']['value'], rule['op']['value'], value))
        
    
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
    
    #TODO: is this ok?
    if field in FIELD_MAP:
        field = FIELD_MAP[field]  #map to universal feedparser's normalised names
    
    if field not in item:
        return True
    
    #todo check which of these should be case insensitive
    if op == "contains":
        if value.lower() in item[field].lower():  #todo use regex?
            return True
    if op == "doesnotcontain":
        if value.lower() not in item[field].lower():  #todo use regex?
            return True
    if op == "matches":
        if re.search(value, item[field]):
            return True
    if op == "is":
        if item[field] == value:
            return True
    if op == "greater":
        if item[field] > value:
            return True
    if op == "less":
        if item[field] < value:
            return True
    if op == "after":
        #todo handle partial datetime values
        if datetime.datetime(*item[field][:7]) > datetime.datetime.strptime(value, DATE_FORMAT):
            return True
    if op == "before":
        #todo handle partial datetime values
        if datetime.datetime(*item[field][:7]) < datetime.datetime.strptime(value, DATE_FORMAT):
            return True
        
    return False

# Example use
if __name__ == '__main__':
    items = pipe_filter([{"title":"one"}, {"title":"By two"}, {"title":"three"}], conf={"MODE":{"value":"permit"}, "COMBINE":{"value":"and"}, "RULE":[{"field":{"value":"title"},"op":{"value":"contains"},"value":{"value":"By"}}]})
    for item in items:
        print item
