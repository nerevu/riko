# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipesubstr
    ~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=string
"""

from pipe2py.lib.dotdict import DotDict


def pipe_substr(context=None, _INPUT=None, conf=None, **kwargs):
    """A string module that returns a substring. Loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : iterable of items or strings
    conf : {
        'from': {'type': 'number', value': <starting position>},
        'length': {'type': 'number', 'value': <count of characters to return>}
    }

    Yields
    ------
    _OUTPUT : substrings
    """
    conf = DotDict(conf)
    start = conf.get('from', func=int, **kwargs)
    length = conf.get('length', func=int, **kwargs)

    for item in _INPUT:
        yield item[start:start + length]

        if item.get('forever'):
            # _INPUT is pipeforever and not a loop,
            # so we just yield our item once
            break
