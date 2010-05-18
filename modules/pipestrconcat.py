# pipestrconcat.py  #aka stringbuilder
#

from pipe2py import util

def pipe_strconcat(context, _INPUT, conf, **kwargs):
    """This source builds a string.
    
    Keyword arguments:
    context -- pipeline context
    _INPUT -- source generator
    conf:
        part -- parts
    
    Yields (_OUTPUT):
    string
    """
    for item in _INPUT:
        s = ""
        for part in conf['part']:
            if "subkey" in part:
                s += item[part['subkey']]   #todo: use this subkey check anywhere we can embed a module
            else:
                s += util.get_value(part, kwargs)
    
        yield s

