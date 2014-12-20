# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipetruncate
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=operators
"""

from pipe2py.lib.dotdict import DotDict
from itertools import islice


def pipe_truncate(context=None, _INPUT=None, conf=None, **kwargs):
    """An operator that returns a specified number of items from the top of a
    feed. Not loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : pipe2py.modules pipe like object (iterable of items)
    kwargs -- terminal, if the truncation value is wired in
    conf : {'count': {'type': 'number', value': <desired feed length>}}

    Yields
    ------
    _OUTPUT : items
    """
    conf = DotDict(conf)
    limit = conf.get('count', func=int, **kwargs)

    for item in islice(_INPUT, limit):
        yield item
