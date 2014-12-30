# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.piperename
    ~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=operators#Rename
"""

from itertools import imap
from pipe2py.lib import utils
from pipe2py.lib.dotdict import DotDict


def _convert_item(rules, item, **kwargs):
    for rule in rules:
        try:
            item.set(rule.newval, item.get(rule.field, **kwargs))
        except (IndexError):
            # Catch error when 'newval' is blank (equivalent to deleting field)
            pass

        if rule.op == 'rename':
            item.delete(rule.field)

    return item


def pipe_rename(context=None, _INPUT=None, conf=None, **kwargs):
    """An operator that renames or copies fields in the input source.
    Not loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : pipe2py.modules pipe like object (iterable of items)
    conf : {
        'RULE': [
            {
                'op': {'value': 'rename or copy'},
                'field': {'value': 'old field'},
                'newval': {'value': 'new field'}
            }
        ]
    }

    kwargs : other inputs, e.g., to feed terminals for rule values

    Yields
    ------
    _OUTPUT : items

    """
    conf = DotDict(conf)
    rule_defs = imap(DotDict, utils.listize(conf['RULE']))

    for item in _INPUT:
        rules = (utils.parse_conf(r, item, **kwargs) for r in rule_defs)
        yield _convert_item(rules, DotDict(item), **kwargs)
