# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipeunion
    ~~~~~~~~~~~~~~~~~~~~~~~~~
    Provides methods for merging separate sources into a single list of items.

    http://pipes.yahoo.com/pipes/docs?doc=operators#Union
"""

from itertools import chain, ifilter
from pipe2py.lib import utils

others_filter = lambda x: x[0].startswith('_OTHER')


def gen_input_items(_INPUT):
    for item in _INPUT:
        # this is being fed forever, i.e. not a real source so just use _OTHERs
        if item.get('forever'):
            break

        yield item


def gen_others(others):
    for src, items in others:
        yield items


def pipe_union(context=None, _INPUT=None, conf=None, **kwargs):
    """An operator that merges multiple source together. Not loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT :  pipe2py.modules pipe like object (iterable of items)
    conf : unused

    Keyword arguments
    -----------------
    _OTHER1 : pipe2py.modules pipe like object
    _OTHER2 : etc.

    Returns
    -------
    _OUTPUT : generator of items
    """

    others = ifilter(others_filter, kwargs.items())
    others_iter = gen_others(others)
    others_items = utils.multiplex(others_iter)
    input_items = gen_input_items(_INPUT)
    _OUTPUT = chain(input_items, others_items)
    return _OUTPUT
