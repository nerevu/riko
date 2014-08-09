# pipetail.py
#

from pipe2py import util

def pipe_tail(context, _INPUT, conf, **kwargs):
    """This operator truncates the number of items in a feed.

    Keyword arguments:
    context -- pipeline context
    _INPUT -- source generator
    kwargs -- terminal, if the truncation value is wired in
    conf:
        count -- length of the truncated feed, if specified literally
        
    Yields (_OUTPUT):
    tail-truncated list of source items
    """

    count = conf['count']
    limit = int(util.get_value(count, None, **kwargs))

    try:
        #if python 2.6+ we can use a sliding window and save memory
        from collections import deque
        buffer = deque(_INPUT, limit)
    except:
        buffer = []
    for item in _INPUT:
        buffer.append(item)
    
    #slice [-limit:] in a list/deque compatible way
    for i in xrange(-1, -(min(len(buffer), limit)+1), -1):
        yield buffer[i]
    