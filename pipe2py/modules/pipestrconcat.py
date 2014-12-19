# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipestrconcat
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=string#StringBuilder
"""

# aka stringbuilder

from functools import partial
from itertools import imap, repeat
from pipe2py.lib import utils
from pipe2py.lib.dotdict import DotDict


def parse_result(parts, _pass):
    return '' if _pass else ''.join(parts)


def pipe_strconcat(context=None, _INPUT=None, conf=None, **kwargs):
    """A string module that builds a string. Loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : pipeforever pipe or an iterable of items
    conf : {
        'part': [
            {'value': '<img src="'}, {'subkey': 'img.src'}, {'value': '">'}
        ]
    }

    Returns
    -------
    _OUTPUT : generator of joined strings
    """
    conf = DotDict(conf)
    test = kwargs.pop('pass_if', None)
    part_defs = map(DotDict, utils.listize(conf['part']))
    get_pass = partial(utils.get_pass, test=test)
    get_value = partial(utils.get_value, **kwargs)
    get_parts = lambda i: imap(get_value, part_defs, repeat(i))

    inputs = imap(DotDict, _INPUT)
    splits = utils.split_input(inputs, get_parts, get_pass)
    _OUTPUT = utils.get_output(splits, parse_result)
    return _OUTPUT
