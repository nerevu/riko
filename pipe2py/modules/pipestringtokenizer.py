# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipestringtokenizer
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=string
"""

from functools import partial
from pipe2py.lib import utils
from pipe2py.lib.dotdict import DotDict


def parse_result(conf, word, _pass):
    if _pass:
        token = None
    else:
        splits = word.split(conf.delimiter)

        try:
            chunks = set(splits) if conf.dedupe else splits
        except AttributeError:
            chunks = splits

        try:
            chunks = sorted(chunks) if conf.sort else chunks
        except AttributeError:
            chunks = chunks

        token = ({'content': chunk} for chunk in chunks)

    return token


def pipe_stringtokenizer(context=None, _INPUT=None, conf=None, **kwargs):
    """A string module that splits a string into tokens delimited by
    separators. Loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : iterable of items or strings
    conf : {
        'to-str': {'value': <delimiter>},
        'dedupe': {'type': 'bool', value': <1>},
        'sort': {'type': 'bool', value': <1>}
    }

    Returns
    -------
    _OUTPUT : generator of items
    """
    conf = DotDict(conf)
    conf['delimiter'] = conf.pop('to-str')
    test = kwargs.pop('pass_if', None)
    loop_with = kwargs.pop('with', None)
    get_with = lambda i: i.get(loop_with, **kwargs) if loop_with else i
    get_pass = partial(utils.get_pass, test=test)
    get_conf = partial(utils.parse_conf, conf, **kwargs)
    funcs = [get_conf, utils.get_word, utils.passthrough]

    splits = utils.broadcast(_INPUT, DotDict, get_with, get_pass)
    parsed = utils.dispatch(splits, *funcs)
    items = utils.gather(parsed, parse_result)
    _OUTPUT = utils.multiplex(items)
    return _OUTPUT
