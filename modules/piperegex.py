# piperegex.py
# vim: sw=4:ts=4:expandtab

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
        #flags = re.DOTALL # DOTALL was the default for pipe2py previously
        flags = 0
        if 'multilinematch' in rule: # flag 'm'
            flags |= re.MULTILINE
        if 'casematch' in rule: # flag 'i'; this name is reversed from its meaning
            flags |= re.IGNORECASE
        if 'singlelinematch' in rule: # flag 's'
            flags |= re.DOTALL
        #todo 'globalmatch' is the default in python
        #todo if set, re.sub() below would get count=0 and by default would get count=1

        match = util.get_value(rule['match'], None, **kwargs) #todo use subkey?
        matchc = re.compile(match, flags)  #compile for speed and we need to pass flags
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
            #todo: when the subject being examined is an HTML node, not a string
            #todo: then the unicode() converts the dict representing the node
            #todo: to a dict literal, and then attempts to apply the pattern
            #todo: to the literal; as an HTML element node, it may have attributes
            #todo: which then appear in the literal.  It should be only matching on
            #todo: (and replacing the value of) the .content subelement
            if rule[0] in item and item[rule[0]]:
                util.set_value(item, rule[0], re.sub(rule[1], rule[2], unicode(item[rule[0]])))

                util.set_value(item, rule[0], re.sub('\$\{(.+?)\}', sub_fields, unicode(item[rule[0]])))

        yield item

