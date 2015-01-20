# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipetruncate
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=operators
"""

from itertools import islice
from . import get_splits


def pipe_truncate(context=None, _INPUT=None, conf=None, **kwargs):
    """An operator that returns a specified number of items from the top of a
    feed. Not loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : pipe2py.modules pipe like object (iterable of items)
    kwargs -- terminal, if the truncation value is wired in
    conf : {'count': {'type': 'number', value': <desired feed length>}}

    Returns
    -------
    _OUTPUT : generator of items
    """
    funcs = get_splits(None, conf, ftype=None, listize=False, **kwargs)
    parsed, _pass = funcs[0](), funcs[2]()
    _OUTPUT = _INPUT if _pass else islice(_INPUT, int(parsed.count))
    return _OUTPUT
