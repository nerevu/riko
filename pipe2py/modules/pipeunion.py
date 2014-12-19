# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipeunion
    ~~~~~~~~~~~~~~~~~~~~~~~~~
    Provides methods for merging separate sources into a single list of items.

    http://pipes.yahoo.com/pipes/docs?doc=operators#Union
"""

from pipe2py.lib import utils


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

    Yields
    -------
    _OUTPUT : items
    """
    for item in _INPUT:
        # this is being fed forever, i.e. not a real source so just use _OTHERs
        if item.get('forever'):
            break

        yield item

    # todo: can the multiple sources should be pulled over multiple servers?
    sources = (
        items for src, items in kwargs.items() if src.startswith('_OTHER')
    )

    for item in utils.multiplex(sources):
        yield item
