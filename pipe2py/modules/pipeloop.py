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
            inp = util.get_subkey(loop_with, item)
        else:
            inp = item
            
        #Pass any input parameters into the submodule
        embed_context.inputs = {}
        for k in embed_conf:
            embed_context.inputs[k] = unicode(util.get_value(embed_conf[k], item))
        p = embed(embed_context, [inp], embed_conf)  #prepare the submodule
        
        results = None
        try:
            #loop over the submodule, emitting as we go or collecting results for later assignment
            for i in p:
                if assign_part == 'first':
                    if mode == 'EMIT':
                        yield i
                    else:
                        results = i
                    break
                else:  #all
                    if mode == 'EMIT':
                        yield i
                    else:
                        if results:
                            results.append(i)
                        else:
                            results = [i]
            if results and mode == 'assign':
                #this is a hack to make sure fetchpage works in an out of a loop while not disturbing strconcat in a loop etc.
                #(goes with the comment below about checking the delivery capability of the source)
                if len(results) == 1 and isinstance(results[0], dict):
                    results = [results]
        except HTTPError:  #todo any other errors we want to continue looping after?
            if context.verbose:
                print "Submodule gave HTTPError - continuing the loop"
            continue
        
        if mode == 'assign':
            if results and len(results) == 1:  #note: i suspect this needs to be more discerning and only happen if the source can only ever deliver 1 result, e.g. strconcat vs. fetchpage
                results = results[0]           
            util.set_value(item, assign_to, results)
            yield item
        elif mode == 'EMIT':
            pass  #already yielded
        else:
            raise Exception("Invalid mode %s (expecting assign or EMIT)" % mode)

