# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipesimplemath
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=number#SimpleMath
"""

from math import pow
from pipe2py.lib import utils
from pipe2py.lib.dotdict import DotDict

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
    loop_with = kwargs.pop('with', None)

    for item in _INPUT:
        _input = DotDict(item)
        _with = item.get(loop_with, **kwargs) if loop_with else item
        value = utils.get_value(conf['OTHER'], _input, **kwargs)
        op = utils.get_value(conf['OP'], _input, **kwargs)
        num = utils.get_num(_with)
        yield OPS[op](num, value)
