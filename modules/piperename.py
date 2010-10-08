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
            #Map names with dot notation onto nested dictionaries, e.g. 'a.content' -> ['a']['content']
            #todo: optimise by pre-calculating splits
            #      and if this logic is stable, wrap in util functions and use everywhere items are accessed
            #reduce(lambda i,k:i.get(k), [item] + rule[2].split('.')[:-1])[rule[2].split('.')[-1]] = reduce(lambda i,k:i.get(k), [item] + rule[1].split('.'))
            try:
                value = reduce(lambda i,k:i.get(k), [item] + rule[1].split('.')) #forces an exception if any part is not found
                reduce(lambda i,k:i.setdefault(k, {}), [item] + rule[2].split('.')[:-1])[rule[2].split('.')[-1]] = value
                if rule[0] == 'rename':
                    try:
                        del reduce(lambda i,k:i.get(k), [item] + rule[1].split('.')[:-1])[rule[1].split('.')[-1]]
                    except KeyError:
                        pass  #ignore if the target doesn't have our field (todo: issue a warning if debugging?)
            except AttributeError:
                pass  #ignore if the source doesn't have our field (todo: issue a warning if debugging?)
        yield item
            
