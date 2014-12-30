# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipestringtokenizer
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=string
"""

from pipe2py.lib import utils
from pipe2py.lib.dotdict import DotDict


def pipe_stringtokenizer(context=None, _INPUT=None, conf=None, **kwargs):
    """A string module that splits a string into tokens delimited by
    separators. Loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : iterable of strings
    conf : {'to-str': {'value': <delimiter>}}

    Yields
    ------
    _OUTPUT : tokenized strings
    """
    conf = DotDict(conf)
    test = kwargs.pop('pass_if', None)
    loop_with = kwargs.pop('with', None)

    for item in _INPUT:
        if utils.get_pass(item, test):
            yield
            continue

        _input = DotDict(item)
        _with = item.get(loop_with, **kwargs) if loop_with else item
        word = utils.get_word(_with)
        delim = utils.get_value(conf['to-str'], _input, **kwargs)

        for chunk in word.split(delim):
            yield {'content': chunk}
