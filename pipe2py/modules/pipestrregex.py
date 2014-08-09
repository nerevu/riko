# pipestrregex.py
#

import re
from pipe2py import util


def pipe_strregex(context, _INPUT, conf, **kwargs):
    """This operator replaces values using regexes. 

    Keyword arguments:
    context -- pipeline context
    _INPUT -- source generator
    kwargs -- other inputs, e.g. to feed terminals for rule values
    conf:
        RULE -- rules - each rule comprising (match, replace)
    
    Yields (_OUTPUT):
    source item after replacing values matching regexes
    """
    rules = []
    
    rule_defs = conf['RULE']
    if not isinstance(rule_defs, list):
        rule_defs = [rule_defs]
    
    for rule in rule_defs:
        #TODO compile regex here: c = re.compile(match)
        match = util.get_value(rule['match'], None, **kwargs) #todo use subkey?
        replace = util.get_value(rule['replace'], None, **kwargs) #todo use subkey?
        
        #convert regex to Python format: todo use a common routine for this
        replace = re.sub('\$(\d+)', r'\\\1', replace)   #map $1 to \1 etc.   #todo: also need to escape any existing \1 etc.
        if replace is None:
            replace = ''
        
        rules.append((match, replace))
    
    for item in _INPUT:
        for rule in rules:
            item = re.sub(match, replace, item)
            
        yield item

