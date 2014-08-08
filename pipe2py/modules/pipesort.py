# pipesort.py
#

from pipe2py import util

def pipe_sort(context, _INPUT, conf, **kwargs):
    """This operator sorts the input source according to the specified key. 

    Keyword arguments:
    context -- pipeline context        
    _INPUT -- source generator
    kwargs -- other inputs, e.g. to feed terminals for rule values
    conf:
        KEY -- list of fields to sort by
    
    Yields (_OUTPUT):
    source items sorted by key
    """
    order = []
       
    keys = conf['KEY']
    if not isinstance(keys, list):
        keys = [keys]
    for key in keys:
        field = util.get_value(key['field'], None, **kwargs)
        sort_dir = util.get_value(key['dir'], None, **kwargs)
        order.append('%s%s' % (sort_dir=='DESC' and '-' or '', field))

    #read all and sort
    sorted_input = []
    for item in _INPUT:
        sorted_input.append(item)
    sorted_input = util.multikeysort(sorted_input, order)
            
    for item in sorted_input:
        yield item
        