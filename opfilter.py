# opfilter.py
#

def op_filter(_INPUT, MODE, COMBINE, RULE):
    """This operator filters the input source, including or excluding fields, that match a set of defined rules. 

    Keyword arguments:
    _INPUT -- source generator
    MODE -- filter mode, either "permit" or "block"
    COMBINE -- filter boolean combination, either "and" or "or"
    RULE -- rule generator - each rules comprising (field, op, value)
    
    Yields (_OUTPUT):
    source items that match the rules
    """
    for item in _INPUT:
        res = False

        #todo rewrite using any/all
        if COMBINE == "and":
            for rule in RULE:
                if not _rulepass(rule, item):
                    break
            else:
                res = True
        elif COMBINE == "or":
            for rule in rules:
                if _rulepass(rule, item):
                    res = True
                    break
        else:
            raise Exception("Invalid combine %s (expecting and or or)" % COMBINE)

        if (res and MODE == "permit") or (not res and MODE == "block"):
            yield item

#todo precompile these?
def _rulepass(rule, item):
    field, op, value = rule
    if op == "contains":
        if value in item[field]:  #todo case insensitive? use regex?
            return True

    return False

# Example use
if __name__ == '__main__':
    items = op_filter([{title:"one"}, {title:"two"}, {title:"three"}], "permit", "and", [("title", "contains", "t")])
    for item in items:
        print item
