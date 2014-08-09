# pipestrreplace.py
#

from pipe2py import util

def pipe_strreplace(context, _INPUT, conf, **kwargs):
    """Replaces text with replacement text.
    
    Keyword arguments:
    context -- pipeline context
    _INPUT -- source generator
    conf:
        RULE -- rules - each rule comprising (find, param, replace):
            find -- text to find
            param -- type of match: 1=first, 2=last, 3=every
            replace -- text to replace with
    
    Yields (_OUTPUT):
    source string with replacements
    """
    rules = []
       
    rule_defs = conf['RULE']
    if not isinstance(rule_defs, list):
        rule_defs = [rule_defs]
    
    for rule in rule_defs:
        find = util.get_value(rule['find'], None, **kwargs)
        param = util.get_value(rule['param'], None, **kwargs)
        replace = util.get_value(rule['replace'], None, **kwargs)
        rules.append((find, param, replace))

    for item in _INPUT:
        t = item
        for rule in rules:
            if rule[1] == '1':
                t = t.replace(rule[0], rule[2], 1)
            elif rule[1] == '2':
                t = util.rreplace(t, rule[0], rule[2], 1)
            elif rule[1] == '3':
                t = t.replace(rule[0], rule[2])
            #todo else assertion
            
        yield t
