# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipereverse
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=operators#Reverse
"""

def pipe_reverse(context=None, _INPUT=None, conf=None, **kwargs):
    """An operator that reverses the order of source items. Not loopable. Not
    lazy.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : pipe2py.modules pipe like object (iterable of items)
    conf : unused

    Yields
    ------
    _OUTPUT : items
    """
    for item in reversed(list(_INPUT)):
        yield item
