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
    if not isinstance(attrs, list):
        attrs = [attrs]
    
    for item in _INPUT:
        d = {}
        for attr in attrs:
            try:
                key = util.get_value(attr['key'], item, **kwargs)
                value = util.get_value(attr['value'], item, **kwargs)
            except KeyError:
                continue  #ignore if the item is referenced but doesn't have our source or target field (todo: issue a warning if debugging?)
            
            util.set_value(d, key, value)
        
        yield d
        
        if item == True: #i.e. this is being fed forever, i.e. not in a loop, so we just yield our item once
            break
            