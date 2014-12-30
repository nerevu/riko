# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipestrtransform
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
"""

from functools import partial
from pipe2py.lib import utils
from pipe2py.lib.dotdict import DotDict


def parse_result(conf, word, _pass):
    transformation = conf._fields[0]
    return word if _pass else getattr(str, transformation)(word)


def pipe_strtransform(context=None, _INPUT=None, conf=None, **kwargs):
    """A string module that splits a string into tokens delimited by
    separators. Loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : iterable of items or strings
    conf : {
        'capitalize': {'type': 'bool', value': <1>},
        'lower': {'type': 'bool', value': <1>},
        'upper': {'type': 'bool', value': <1>},
        'swapcase': {'type': 'bool', value': <1>},
        'title': {'type': 'bool', value': <1>},
    }

    Yields
    ------
    _OUTPUT : tokenized strings
    """
    test = kwargs.pop('pass_if', None)
    loop_with = kwargs.pop('with', None)
    get_with = lambda i: i.get(loop_with, **kwargs) if loop_with else i
    get_pass = partial(utils.get_pass, test=test)
    get_conf = partial(utils.parse_conf, DotDict(conf), **kwargs)

    splits = utils.split_input(_INPUT, DotDict, get_with, get_pass)
    funcs = [get_conf, utils.get_word, utils.passthrough]
    parsed = utils.parse_splits(splits, *funcs)
    _OUTPUT = utils.get_output(parsed, parse_result)
    return _OUTPUT
