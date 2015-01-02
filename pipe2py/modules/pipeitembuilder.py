# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipeitembuilder
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=sources#ItemBuilder
"""

from functools import partial
from itertools import imap, repeat
from pipe2py.lib import utils
from pipe2py.lib.dotdict import DotDict


def pipe_itembuilder(context=None, _INPUT=None, conf=None, **kwargs):
    """A source that builds an item. Loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : pipeforever pipe or an iterable of items
    conf : {
        'attrs': [
            {
                'key': {'value': 'title'},
                'value': {'value': 'new title'}
            }, {
                'key': {'value': 'description.content'},
                'value': {'value': 'new description'}
            }
        ]
    }

    Returns
    ------
    _OUTPUT : generator of items
    """
    conf = DotDict(conf)
    attr_defs = map(DotDict, utils.listize(conf['attrs']))
    parse_conf = partial(utils.parse_conf, **kwargs)
    get_attrs = lambda i: imap(parse_conf, attr_defs, repeat(i))

    finite = utils.make_finite(_INPUT)
    inputs = imap(DotDict, finite)
    attrs = imap(get_attrs, inputs)
    results = imap(utils.parse_params, attrs)
    _OUTPUT = imap(DotDict, results)
    return _OUTPUT
