# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipestrconcat
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=string#StringBuilder
"""

# aka stringbuilder

from itertools import imap
from pipe2py.lib import utils
from pipe2py.lib.dotdict import DotDict




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

    Yields
    ------
    _OUTPUT : joined strings
    """
    conf = DotDict(conf)
    parts = imap(DotDict, utils.listize(conf['part']))

    for item in _INPUT:
        _input = DotDict(item)
        yield ''.join(utils.get_value(p, _input, **kwargs) for p in parts)
