# piperegex.py
#

import re
from pipe2py import util


def pipe_regex(context, _INPUT, conf, **kwargs):
    """This operator replaces values using regexes. 

    Keyword arguments:
    context -- pipeline context
    _INPUT -- source generator
    kwargs -- other inputs, e.g. to feed terminals for rule values
    conf:
        RULE -- rules - each rule comprising (field, match, replace)
    
    Yields (_OUTPUT):
    source items after replacing values matching regexes
    """
    rules = []
       
    for rule in conf['RULE']:
        #TODO compile regex here: c = re.compile(match)
        match = util.get_value(rule['match'], kwargs) #todo use subkey?
        replace = util.get_value(rule['replace'], kwargs) #todo use subkey?
        
        #convert regex to Python format: todo use a common routine for this
        replace = re.sub('\$(\d+)', r'\\\1', replace)   #map $1 to \1 etc.   #todo: also need to escape any existing \1 etc.

        rules.append((rule['field']['value'], match, replace))
            
    for item in _INPUT:
        for rule in rules:
            item[rule[0]] = re.sub(rule[1], rule[2], item[rule[0]])
            
        yield item

