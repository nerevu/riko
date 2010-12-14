# pipeuniq.py
#

from pipe2py import util

def pipe_uniq(context, _INPUT, conf, **kwargs):
    """This operator filters out non unique items according to the specified field. 

    Keyword arguments:
    context -- pipeline context        
    _INPUT -- source generator
    kwargs -- other inputs, e.g. to feed terminals for rule values
    conf:
        field -- field to be unique
    
    Yields (_OUTPUT):
    source items, one per unique field value
    """
       
    field = util.get_value(conf['field'], None, **kwargs)
    order = ['%s%s' % ('', field)]

    #read all and sort
    sorted_input = []
    for item in _INPUT:
        sorted_input.append(item)
    sorted_input = util.multikeysort(sorted_input, order)
            
    seen = None
    for item in sorted_input:
        #todo: do we ever need get_value here instead of item[]?
        if seen != item[field]:
            yield item
            seen = item[field]

        