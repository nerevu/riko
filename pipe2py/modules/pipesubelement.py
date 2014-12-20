# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipesubelement
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=operators#SubElement
"""

from pipe2py import util
from pipe2py.lib.dotdict import DotDict


def pipe_subelement(context=None, _INPUT=None, conf=None, **kwargs):
    """An operator extracts select sub-elements from a feed. Not loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : pipe2py.modules pipe like object (iterable of items)
    conf : {'path': {'value': <element path>}}

    Yields
    ------
    _OUTPUT : items
    """
    for item in _INPUT:
        path = DotDict(item).get(conf['path'], **kwargs)

        for res in path:
            for i in util.gen_items(res, True):
                yield i

        yield util.gen_items()

        if item.get('forever'):
            # _INPUT is pipeforever and not a loop,
            # so we just yield our item once
            break
