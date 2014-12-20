# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipeitembuilder
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=sources#ItemBuilder
"""

from pipe2py import util
from pipe2py.lib.dotdict import DotDict


def _gen_key_value(attrs, item, **kwargs):
    for attr in attrs:
        attr = DotDict(attr)

        try:
            key = util.get_value(attr['key'], item, **kwargs)
            value = util.get_value(attr['value'], item, **kwargs)

        # ignore if the item is referenced but doesn't have our source
        # or target field
        # todo: issue a warning if debugging?
        except KeyError:
            continue

        if not all([key, value]):
            continue

        yield (key, value)


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
    # conf = DotDict(conf)
    attrs = util.listize(conf['attrs'])

    for item in _INPUT:
        d = DotDict(_gen_key_value(attrs, DotDict(item), **kwargs))
        [d.set(k, v) for k, v in d.iteritems()]
        yield d

        if item.get('forever'):
            # _INPUT is pipeforever and not a loop,
            # so we just yield our item once
            break
