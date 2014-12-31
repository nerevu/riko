# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.piperename
    ~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=operators#Rename
"""

from functools import partial
from itertools import imap, repeat
from pipe2py.lib import utils
from pipe2py.lib.dotdict import DotDict


def func(item, rule, **kwargs):
    try:
        item.set(rule.newval, item.get(rule.field, **kwargs))
    except (IndexError):
        # Catch error when 'newval' is blank (equivalent to deleting field)
        pass

    if rule.op == 'rename':
        item.delete(rule.field)

    return item


def parse_result(rules, item, _pass, **kwargs):
    return item if _pass else reduce(partial(func, **kwargs), rules, item)


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

    Returns
    -------
    _OUTPUT : generator of items

    """
    conf = DotDict(conf)
    test = kwargs.pop('pass_if', None)
    rule_defs = imap(DotDict, utils.listize(conf['RULE']))
    get_pass = partial(utils.get_pass, test=test)
    parse_conf = partial(utils.parse_conf, **kwargs)
    get_rules = lambda i: imap(parse_conf, rule_defs, repeat(i))

    inputs = imap(DotDict, _INPUT)
    splits = utils.broadcast(inputs, get_rules, utils.passthrough, get_pass)
    _OUTPUT = utils.gather(splits, partial(parse_result, **kwargs))
    return _OUTPUT
