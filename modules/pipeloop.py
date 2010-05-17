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
        mode -- how to affect output - either assign or EMIT
        assign_to -- if mode is assign, which field to assign to (new or existing)
        loop_with -- pass a particular field into the submodule rather than the whole item
    embed -- embedded submodule
    
    Yields (_OUTPUT):
    source items after passing through the submodule and adding/replacing values
    """
    mode = conf['mode']['value']
    assign_to = conf['assign_to']['value']
    loop_with = conf['with']['value']
    
    for item in _INPUT:        
        if loop_with:
            inp = item[loop_with]
        else:
            inp = item
            
        p = embed(context, [inp])  #prepare the submodule
        
        i = None
        for i in p:
            break  #todo ok to always limit inner loop to 1 call (if more then what?)
        
        if mode == 'assign':
            item[assign_to] = i
        elif mode == 'EMIT':
            item = i
        else:
            raise Exception("Invalid mode %s (expecting assign or EMIT)" % mode)

        yield item
            
