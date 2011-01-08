# pipesubelement.py
#

from pipe2py import util

def pipe_subelement(context, _INPUT, conf, **kwargs):
    """Returns a subelement.
    
    Keyword arguments:
    context -- pipeline context
    _INPUT -- source generator
    conf:
        path -- contains the value and type to select
    
    Yields (_OUTPUT):
    subelement of source item
    """
    path = conf['path']
    path['subkey'] = path['value']  #switch to using as a reference
    del path['value']

    for item in _INPUT:
        t = util.get_value(path, item)
        if t:
            if isinstance(t, list):
                for nested_item in t:
                    yield nested_item
            else:
                yield t
            
        if item == True: #i.e. this is being fed forever, i.e. not in a loop, so we just yield our item once
            break        
