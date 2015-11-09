# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipesort
    ~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=operators#Sort
"""

from __future__ import (
    absolute_import, division, print_function, with_statement,
    unicode_literals)

from operator import itemgetter
from functools import partial
from itertools import imap
from pipe2py.lib import utils
from pipe2py.lib.dotdict import DotDict


def get_comparer(x):
    if x.startswith('-'):
        result = (itemgetter(x[1:].strip()), -1)
    else:
        result = (itemgetter(x.strip()), 1)

    return result


def multikeysort(left, right, comparers=None):
    for func, multiplier in comparers:
        try:
            result = cmp(func(left), func(right))
        except (KeyError, TypeError):
            # todo: perhaps care more if only one side has the missing key
            # todo: handle bool better?
            pass
        else:
            return multiplier * result

    return 0


def pipe_sort(context=None, _INPUT=None, conf=None, **kwargs):
    """An operator that sorts the input source according to the specified key.
    Not loopable. Not lazy.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : pipe2py.modules pipe like object (iterable of items)
    kwargs -- other inputs, e.g. to feed terminals for rule values
    conf : {
        'KEY': [
            {
                'field': {'type': 'text', 'value': 'title'},
                'dir': {'type': 'text', 'value': 'DESC'}
            }
        ]
    }

    Returns
    -------
    _OUTPUT : generator of sorted items
    """
    test = kwargs.pop('pass_if', None)
    _pass = utils.get_pass(test=test)
    key_defs = imap(DotDict, utils.listize(conf['KEY']))
    get_value = partial(utils.get_value, **kwargs)
    parse_conf = partial(utils.parse_conf, parse_func=get_value, **kwargs)
    keys = imap(parse_conf, key_defs)
    order = ('%s%s' % ('-' if k.dir == 'DESC' else '', k.field) for k in keys)
    comparers = map(get_comparer, order)
    cmp_func = partial(multikeysort, comparers=comparers)
    _OUTPUT = _INPUT if _pass else iter(sorted(_INPUT, cmp=cmp_func))
    return _OUTPUT
