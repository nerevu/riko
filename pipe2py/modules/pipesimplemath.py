# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipesimplemath
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=number#SimpleMath
"""

from functools import partial
from math import pow
from pipe2py.lib import utils
from pipe2py.lib.dotdict import DotDict

OPS = {
    'add': lambda x, y: x + y,
    'subtract': lambda x, y: x - y,
    'multiply': lambda x, y: x * y,
    'mean': lambda x, y: (x + y) / 2.0,
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

    Returns
    -------
    _OUTPUT : generator of tokenized floats
    """
    loop_with = kwargs.pop('with', None)
    get_with = lambda i: i.get(loop_with, **kwargs) if loop_with else i
    get_conf = partial(utils.parse_conf, DotDict(conf), **kwargs)
    parse_result = lambda conf, num: OPS[conf.OP](num, conf.OTHER)

    splits = utils.broadcast(_INPUT, DotDict, get_with)
    parsed = utils.dispatch(splits, get_conf, utils.get_num)
    _OUTPUT = utils.gather(parsed, parse_result)
    return _OUTPUT
