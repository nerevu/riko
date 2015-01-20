# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipesubstr
    ~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=string#SubString
"""

from functools import partial
from pipe2py.lib import utils
from pipe2py.lib.dotdict import DotDict


def parse_result(conf, word, _pass):
    start = int(conf.start)
    end = int(conf.start + conf.length)
    return word if _pass else word[start:end]


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

    Returns
    -------
    _OUTPUT : generator of substrings
    """
    conf = DotDict(conf)
    conf['start'] = conf.pop('from')
    test = kwargs.pop('pass_if', None)
    loop_with = kwargs.pop('with', None)
    get_with = lambda i: i.get(loop_with, **kwargs) if loop_with else i
    get_conf = partial(utils.parse_conf, conf, **kwargs)
    get_pass = partial(utils.get_pass, test=test)
    funcs = [get_conf, utils.get_word, utils.passthrough]

    splits = utils.broadcast(_INPUT, DotDict, get_with, get_pass)
    parsed = utils.dispatch(splits, *funcs)
    _OUTPUT = utils.gather(parsed, parse_result)
    return _OUTPUT
