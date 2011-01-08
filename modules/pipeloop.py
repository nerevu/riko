# pipeloop.py
#

from pipe2py import util
import copy
from urllib2 import HTTPError

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
    assign_part = conf['assign_part']['value']
    emit_part = conf['emit_part']['value']
    loop_with = conf['with']['value']
    embed_conf = conf['embed']['value']['conf']
    
    #Prepare the submodule to take parameters from the loop instead of from the user
    embed_context = copy.copy(context)
    embed_context.submodule = True
    
    for item in _INPUT:        
        if loop_with:
            inp = item[loop_with]  #todo: get_value here?
        else:
            inp = item
            
        #Pass any input parameters into the submodule
        embed_context.inputs = {}
        for k in embed_conf:
            embed_context.inputs[k] = unicode(util.get_value(embed_conf[k], item))
        p = embed(embed_context, [inp], embed_conf)  #prepare the submodule
        
        results = None
        try:
            for i in p:
                if mode == 'assign' and assign_part == 'first' or mode == 'EMIT' and emit_part == 'all':
                    results = i
                    break
                else:
                    if results:
                        results += i  #is ok here, i.e. for assign/emit_part=all?
                    else:
                        results = i
        except HTTPError:  #todo any other errors we want to continue looping after?
            if context.verbose:
                print "Submodule gave HTTPError - continuing the loop"
            continue
        
        if mode == 'assign':
            util.set_value(item, assign_to, results)
        elif mode == 'EMIT':
            item = results
        else:
            raise Exception("Invalid mode %s (expecting assign or EMIT)" % mode)

        yield item
            
