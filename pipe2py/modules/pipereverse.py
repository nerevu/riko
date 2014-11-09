# pipereverse.py
#


def pipe_reverse(context=None, _INPUT=None, conf=None, **kwargs):
    """Reverse the order of items in a feed.

    Keyword arguments:
    context -- pipeline context
    _INPUT -- source generator
    kwargs --
    conf:

    Yields (_OUTPUT):
    reversed order of _INPUT items
    """
    for item in reversed(list(_INPUT)):
        yield item
