# pipeforever.py
#

def pipe_forever(context, _INPUT, conf, **kwargs):
    """This is a source to enable other modules, e.g. date builder, to be called
       so they can continue to consume values from indirect terminal inputs
    
    Keyword arguments:
    context -- pipeline context
    _INPUT -- not used
    conf -- not used

    Yields (_OUTPUT):
    True
    """       
    while True:
        yield True
