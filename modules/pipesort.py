# pipesort.py
#

from pipe2py import util
from operator import itemgetter

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
       
    for key in conf['KEY']:
        field = util.get_value(key['field'], kwargs)
        sort_dir = util.get_value(key['dir'], kwargs)
        order.append('%s%s' % (sort_dir=='DESC' and '-' or '', field))

    #read all and sort
    sorted_input = []
    for item in _INPUT:
        sorted_input.append(item)
    sorted_input = multikeysort(sorted_input, order)
            
    for item in sorted_input:
        yield item
        
def multikeysort(items, columns):
    comparers = [ ((itemgetter(col[1:].strip()), -1) if col.startswith('-') else (itemgetter(col.strip()), 1)) for col in columns]  
    def comparer(left, right):
        for fn, mult in comparers:
            result = cmp(fn(left), fn(right))
            if result:
                return mult * result
        else:
            return 0
    return sorted(items, cmp=comparer)        