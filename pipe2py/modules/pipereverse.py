# pipereverse.py
#

from pipe2py import util

def pipe_reverse(context, _INPUT, conf, **kwargs):
    """Reverse the order of items in a feed.

    Keyword arguments:
    context -- pipeline context
    _INPUT -- source generator
    kwargs --
    conf:
        
    Yields (_OUTPUT):
    reversed order of _INPUT items
    """
    
    input=[]
    
    for item in _INPUT:
        input.append(item)
    
    for item in reversed(input):
        yield item