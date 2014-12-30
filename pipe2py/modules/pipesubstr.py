# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipesubstr
    ~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=string
"""

from pipe2py.lib import utils
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
    loop_with = kwargs.pop('with', None)

    for item in _INPUT:
        _input = DotDict(item)
        _with = item.get(loop_with, **kwargs) if loop_with else item
        start = utils.get_value(conf['from'], _input, func=int, **kwargs)
        length = utils.get_value(conf['length'], _input, func=int, **kwargs)
        word = utils.get_word(_with)
        yield word[start:start + length]
