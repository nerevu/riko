# pipefilter.py
#

COMBINE_BOOLEAN = {"and": all, "or": any}

def pipe_filter(_INPUT, conf):
    """This operator filters the input source, including or excluding fields, that match a set of defined rules. 

    Keyword arguments:
    _INPUT -- source generator
    conf:
        MODE -- filter mode, either "permit" or "block"
        COMBINE -- filter boolean combination, either "and" or "or"
        RULE -- rules - each rule comprising (field, op, value)
    
    Yields (_OUTPUT):
    source items that match the rules
    """
    mode = conf['MODE']['value']
    combine = conf['COMBINE']['value']
    rules = [(rule['field']['value'], rule['op']['value'], rule['value']['value']) for rule in conf['RULE']]
    
    for item in _INPUT:
        if combine in COMBINE_BOOLEAN: 
            res = COMBINE_BOOLEAN[combine](_rulepass(rule, item) for rule in rules)
        else:
            raise Exception("Invalid combine %s (expecting and or or)" % combine)

        if (res and mode == "permit") or (not res and mode == "block"):
            yield item

#todo precompile these?
def _rulepass(rule, item):
    field, op, value = rule
    if op == "contains":
        if value in item[field]:  #todo case insensitive? use regex?
            return True
    #TODO etc.
        
    return False

# Example use
if __name__ == '__main__':
    items = pipe_filter([{"title":"one"}, {"title":"By two"}, {"title":"three"}], conf={"MODE":{"value":"permit"}, "COMBINE":{"value":"and"}, "RULE":[{"field":{"value":"title"},"op":{"value":"contains"},"value":{"value":"By"}}]})
    for item in items:
        print item
