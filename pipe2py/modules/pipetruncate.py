# pipetruncate.py
#

from pipe2py.lib.dotdict import DotDict
from itertools import islice


def pipe_truncate(context=None, _INPUT=None, conf=None, **kwargs):
    """This operator truncates the number of items in a feed.

    Keyword arguments:
    context -- pipeline context
    _INPUT -- source generator
    kwargs -- terminal, if the truncation value is wired in
    conf:
        count -- length of the truncated feed, if specified literally

    Yields (_OUTPUT):
    truncated list of source items
    """
    conf = DotDict(conf)
    limit = conf.get('count', func=int, **kwargs)

    for item in islice(_INPUT, limit):
        yield item
