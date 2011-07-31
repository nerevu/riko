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

    rule_defs = conf['RULE']
    if not isinstance(rule_defs, list):
        rule_defs = [rule_defs]
    
    for rule in rule_defs:
        #todo use the undocumented g,s,m,i flags here: rule['singlelinematch']['value'] == 2 indicates re.DOTALL
        # so use that to pass to re.compile: see here for more http://livedocs.adobe.com/flex/3/html/help.html?content=12_Using_Regular_Expressions_10.html
        match = util.get_value(rule['match'], None, **kwargs) #todo use subkey?
        matchc = re.compile(match, re.DOTALL)  #compile for speed and we need to pass flags
        replace = util.get_value(rule['replace'], None, **kwargs) #todo use subkey?
        if replace is None:
            replace = ''
        
        #convert regex to Python format: todo use a common routine for this
        replace = re.sub('\$(\d+)', r'\\\1', replace)   #map $1 to \1 etc.   #todo: also need to escape any existing \1 etc.

        rules.append((rule['field']['value'], matchc, replace))
            
    for item in _INPUT:
        def sub_fields(matchobj):
            return util.get_value({'subkey':matchobj.group(1)}, item)
            
        for rule in rules:
            #todo: do we ever need get_value here instead of item[]?
            if rule[0] in item and item[rule[0]]:
                util.set_value(item, rule[0], re.sub(rule[1], rule[2], unicode(item[rule[0]])))
    
                util.set_value(item, rule[0], re.sub('\$\{(.+)\}', sub_fields, unicode(item[rule[0]])))
            
        yield item

