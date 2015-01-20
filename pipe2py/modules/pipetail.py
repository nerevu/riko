# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipetail
    ~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=operator
"""

from collections import deque
from pipe2py.lib.dotdict import DotDict


def pipe_tail(context=None, _INPUT=None, conf=None, **kwargs):
    """Returns a specified number of items from the bottom of a feed.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : pipe2py.modules pipe like object (iterable of items)
    kwargs -- terminal, if the truncation value is wired in
    conf : count -- length of the truncated feed, if specified literally

    Yields
    ------
    _OUTPUT : items
    """
    conf = DotDict(conf)
    limit = conf.get('count', func=int, **kwargs)

    for item in deque(_INPUT, limit):
        yield item
