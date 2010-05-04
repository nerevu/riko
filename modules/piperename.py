# piperename.py
#

from pipe2py import util


def pipe_rename(context, _INPUT, conf, **kwargs):
    """This operator renames or copies fields in the input source. 

    Keyword arguments:
    context -- pipeline context
    _INPUT -- source generator
    kwargs -- other inputs, e.g. to feed terminals for rule values
    conf:
        RULE -- rules - each rule comprising (op, field, newval)
    
    Yields (_OUTPUT):
    source items after copying/renaming
    """
    rules = []
       
    for rule in conf['RULE']:
        newval = util.get_value(rule['newval'], kwargs) #todo use subkey?

        rules.append((rule['op']['value'], rule['field']['value'], newval))
        
    
    for item in _INPUT:
        for rule in rules:
            item[rule[2]] = item[rule[1]]
            if rule[0] == 'rename':
                del item[rule[1]]
        yield item
            
