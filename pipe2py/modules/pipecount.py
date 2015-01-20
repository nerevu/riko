# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipecount
    ~~~~~~~~~~~~~~~~~~~~~~~~~
    Provides methods for counting the number of items in a feed.

    http://pipes.yahoo.com/pipes/docs?doc=operators#Count
"""


def pipe_count(context=None, _INPUT=None, conf=None, **kwargs):
    """An operator that counts the number of _INPUT items and yields it
    forever. Not loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : pipe2py.modules pipe like object (iterable of items)
    conf : not used

    Yields
    ------
    _OUTPUT : number of items in the feed

    Examples
    --------
    >>> generator = (x for x in xrange(5))
    >>> count = pipe_count(_INPUT=generator)
    >>> count  #doctest: +ELLIPSIS
    <generator object pipe_count at 0x...>
    >>> count.next()
    5
    """

    count = len(list(_INPUT))
    # todo: check all operators (not placeable in loops)
    while True:
        yield count
