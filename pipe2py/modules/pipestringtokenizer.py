# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipestringtokenizer
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=string
"""

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
    delim = conf.get('to-str', **kwargs)

    for item in _INPUT:
        for chunk in item.split(delim):
            yield {'content': chunk}

        if item.get('forever'):
            # _INPUT is pipeforever and not a loop,
            # so we just yield our item once
            break
