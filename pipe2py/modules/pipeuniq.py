# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipeuniq
    ~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=operators
"""

from pipe2py.lib import utils
from pipe2py.lib.dotdict import DotDict


def unique_items(items, field):
    seen = set()

    for item in items:
        value = item.get(field)

        if value not in seen:
            seen.add(value)
            yield item


def pipe_uniq(context=None, _INPUT=None, conf=None, **kwargs):
    """An operator that filters out non unique items according to the specified
    field. Not loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : pipe2py.modules pipe like object (iterable of items)
    kwargs -- other inputs, e.g. to feed terminals for rule values
    conf : {'field': {'type': 'text', value': <field to be unique>}}

    Returns
    -------
    _OUTPUT : generator of unique items
    """
    test = kwargs.pop('pass_if', None)
    _pass = utils.get_pass(test=test)
    parsed = utils.parse_conf(DotDict(conf), **kwargs)
    _OUTPUT = _INPUT if _pass else unique_items(_INPUT, parsed.field)
    return _OUTPUT
