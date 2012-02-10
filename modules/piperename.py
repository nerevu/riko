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
    
    rule_defs = conf['RULE']
    if not isinstance(rule_defs, list):
        rule_defs = [rule_defs]
       
    for rule in rule_defs:
        newval = util.get_value(rule['newval'], None, **kwargs) #todo use subkey?
        newfield = rule['field']
        #trick the get_value in the loop to mapping value onto an item key (rather than taking it literally, i.e. make it a LHS reference, not a RHS value)        
        newfield['subkey'] = newfield['value']
        del newfield['value']
        
        rules.append((rule['op']['value'], newfield, newval))
    
    for item in _INPUT:
        for rule in rules:
            try:
                value = util.get_value(rule[1], item, **kwargs) #forces an exception if any part is not found
                util.set_value(item, rule[2], value)
                if rule[0] == 'rename':
                    try:
                        util.del_value(item, rule[1]['subkey'])
                    except (KeyError, TypeError):  #TypeError catches pseudo subkeys, e.g. summary.content
                        pass  #ignore if the target doesn't have our field (todo: issue a warning if debugging?)
            except AttributeError:
                pass  #ignore if the source doesn't have our field (todo: issue a warning if debugging?)
        yield item
            
