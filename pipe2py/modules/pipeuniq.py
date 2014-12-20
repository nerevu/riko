# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipeuniq
    ~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=operators
"""

from pipe2py.lib.dotdict import DotDict


def pipe_uniq(context=None, _INPUT=None, conf=None, **kwargs):
    """An operator that filters out non unique items according to the specified
    field. Not loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : pipe2py.modules pipe like object (iterable of items)
    kwargs -- other inputs, e.g. to feed terminals for rule values
    conf : {'field': {'type': 'text', value': <field to be unique>}}

    Yields
    ------
    _OUTPUT : source items, one per unique field value
    """
    seen = set()
    conf = DotDict(conf)
    field = conf.get('field', **kwargs)

    for item in _INPUT:
        value = DotDict(item).get(field)

        if value not in seen:
            seen.add(value)
            yield item
