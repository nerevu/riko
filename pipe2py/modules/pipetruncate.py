# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipetruncate
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=operators
"""

from functools import partial
from itertools import repeat, imap, islice
from pipe2py.lib import utils
from pipe2py.lib.dotdict import DotDict


def pipe_truncate(context=None, _INPUT=None, conf=None, **kwargs):
    """An operator that returns a specified number of items from the top of a
    feed. Not loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : pipe2py.modules pipe like object (iterable of items)
    kwargs -- terminal, if the truncation value is wired in
    conf : {'count': {'type': 'number', value': <desired feed length>}}

    Returns
    -------
    _OUTPUT : generator of items
    """
    conf = DotDict(conf)
    test = kwargs.pop('pass_if', None)
    _pass = utils.get_pass({}, test)
    parsed = imap(partial(utils.parse_conf, **kwargs), conf, repeat({}))
    _OUTPUT = _INPUT if _pass else islice(_INPUT, parsed.limit)
    return _OUTPUT
