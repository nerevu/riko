# pipeloop.py
#

from pipe2py import util

def pipe_loop(context, _INPUT, conf, embed=None, **kwargs):
    """This operator loops over the input performing the embedded submodule. 

    Keyword arguments:
    context -- pipeline context
    _INPUT -- source generator
    kwargs -- other inputs, e.g. to feed terminals for rule values
    conf:
    embed -- embedded submodule
    
    Yields (_OUTPUT):
    source items after passing through the submodule and adding/replacing values
    """
    #todo hook up any input parameters to the embedded submodule
    
    for item in _INPUT:
        for i in embed:
            item['extra'] = i    #todo add or replace...
            break  #todo ok to always limit inner loop to 1 call (if more then what?)
        
        yield item
            
