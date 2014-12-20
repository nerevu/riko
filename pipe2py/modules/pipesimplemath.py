# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipesimplemath
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=number#SimpleMath
"""

from pipe2py.lib.dotdict import DotDict
from math import pow

OPS = {
    'add': lambda x, y: x + y,
    'subtract': lambda x, y: x - y,
    'multiply': lambda x, y: x * y,
    'divide': lambda x, y: x / (y * 1.0),
    'modulo': lambda x, y: x % y,
    'power': lambda x, y: pow(x, y),
}


def pipe_simplemath(context=None, _INPUT=None, conf=None, **kwargs):
    """A number module that performs basic arithmetic, such as addition and
    subtraction. Loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : iterable of items or numbers
    kwargs -- other value, if wired in
    conf : {
        'OTHER': {'type': 'number', 'value': <'5'>},
        'OP': {'type': 'text', 'value': <'modulo'>}
    }

    Yields
    ------
    _OUTPUT : float
    """
    conf = DotDict(conf)
    value = conf.get('OTHER', func=float, **kwargs)
    op = conf.get('OP', **kwargs)

    for item in _INPUT:
        yield OPS[op](float(item), value)
