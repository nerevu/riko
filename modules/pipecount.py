# pipecount.py
#

from pipe2py import util

def pipe_count(context, _INPUT, conf, **kwargs):
    """Count the number of items in a feed.

    Keyword arguments:
    context -- pipeline context
    _INPUT -- source generator
    kwargs -- other inputs, e.g. to feed terminals for rule values
    conf:
        
    Yields (_OUTPUT):
    a count on the number of items in the feed
    """
    
    yield sum(1 for item in _INPUT)