# pipeoutput.py
#

def pipe_output(context, _INPUT, conf=None, **kwargs):
    """This operator outputs the input source, i.e. does nothing.

    Keyword arguments:
    context -- pipeline context   
    _INPUT -- source generator
    conf:
    
    Yields (_OUTPUT):
    source items
    """
    if conf is None:
        conf = {}
    
    for item in _INPUT:
        #todo convert back to XML or JSON
        yield item

