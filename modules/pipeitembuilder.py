# pipeitembuilder.py
#

import urllib
from pipe2py import util

def pipe_itembuilder(context, _INPUT, conf, **kwargs):
    """This source builds an item.
    
    Keyword arguments:
    context -- pipeline context
    _INPUT -- source generator
    conf:
        attrs -- key, value pairs
        
    Yields (_OUTPUT):
    item
    """
    attrs = conf['attrs']
    dkv = []
    for attr in attrs:
        key = attr['key']
        if "subkey" not in key:
            key['value'] = util.get_value(key, kwargs)
        value = attr['value']
        if "subkey" not in value:
            value['value'] = util.get_value(value, kwargs)
        
        dkv.append((key, value))
    
    for item in _INPUT:
        d = {}
        
        for (dk, dv) in dkv:
            try:
                if "subkey" in dk:
                    #todo really dereference item? (sample pipe seems to suggest so: surprising)
                    key = reduce(lambda i,k:i.get(k), [item] + dk['subkey'].split('.')) #forces an exception if any part is not found
                    #todo trap and ignore AttributeError here?
                else:
                    key = dk['value']
                if "subkey" in dv:  #todo: use this subkey check anywhere we can embed a module
                    value = reduce(lambda i,k:i.get(k), [item] + dv['subkey'].split('.')) #forces an exception if any part is not found
                    #todo trap and ignore AttributeError here?
                else:
                    value = dv['value']
            except KeyError:
                continue  #ignore if the source doesn't have our source or target field (todo: issue a warning if debugging?)
            
            try:
                reduce(lambda i,k:i.setdefault(k, {}), [d] + key.split('.')[:-1])[key.split('.')[-1]] = value
            except AttributeError:
                continue  #ignore if the source doesn't have our (dereferenced) target field (todo: issue a warning if debugging?)
        
        yield d
        
        if item == True: #i.e. this is being fed forever, i.e. not in a loop, so we just yield our item once
            break
        