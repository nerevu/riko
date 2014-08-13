# pipeitembuilder.py
#

import urllib
from pipe2py import util
from pipe2py.lib.dotdict import DotDict


def pipe_itembuilder(context=None, _INPUT=None, conf=None, **kwargs):
    """This source builds an item.

    Keyword arguments:
    context -- pipeline context
    _INPUT -- source generator
    conf:
        attrs -- key, value pairs

    Yields (_OUTPUT):
    item
    """
    # conf = DotDict(conf)
    attrs = util.listize(conf['attrs'])

    for item in _INPUT:
        d = DotDict()

        for attr in attrs:
            attr = DotDict(attr)

            try:
                key = util.get_value(attr['key'], item, **kwargs)
                value = util.get_value(attr['value'], item, **kwargs)
            except KeyError:
                continue  #ignore if the item is referenced but doesn't have our source or target field (todo: issue a warning if debugging?)

            d.set(key, value)

        yield d

        if item.get('forever'):
            # _INPUT is pipeforever and not a loop,
            # so we just yield our item once
            break
