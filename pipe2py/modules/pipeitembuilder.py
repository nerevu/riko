# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipeitembuilder
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=sources#ItemBuilder
"""

from itertools import imap, ifilter
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


    Yields
    ------
    _OUTPUT : items
    """
    conf = DotDict(conf)
    attrs = imap(DotDict, utils.listize(conf['attrs']))

    for item in _INPUT:
        _input = DotDict(item)
        pairs = (utils.parse_conf(a, _input, **kwargs) for a in attrs)
        yield DotDict(ifilter(all, pairs))

        if item.get('forever'):
            # _INPUT is infinite and not a loop, so just yield item once
            break
