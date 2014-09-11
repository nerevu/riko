# pipesimplemath.py
#

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
    """This operator performs basic arithmetic, such as addition and
    subtraction.

    Keyword arguments:
    context -- pipeline context
    _INPUT -- source generator
    kwargs -- other value, if wired in
    conf:
        other -- input value
        op -- operator

    Yields (_OUTPUT):
    result
    """
    conf = DotDict(conf)
    value = conf.get('OTHER', func=float, **kwargs)
    op = conf.get('OP', **kwargs)

    for item in _INPUT:
        yield OPS[op](float(item), value)
