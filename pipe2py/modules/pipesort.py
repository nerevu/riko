# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipesort
    ~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=operators#Sort
"""

from operator import itemgetter
from pipe2py import util
from pipe2py.lib.dotdict import DotDict


def _multikeysort(items, order):
    """Sorts a items by order

       (items in order preceded with a '-' will sort descending)
    """
    comparers = [
        (
            (itemgetter(x[1:].strip()), -1) if x.startswith('-') else (
                itemgetter(x.strip()), 1
            )
        ) for x in order
    ]

    def comparer(left, right):
        for fn, mult in comparers:
            try:
                result = cmp(fn(left), fn(right))
            except (KeyError, TypeError):
                # todo: perhaps care more if only one side has the missing key
                # todo: handle bool better?
                pass
            else:
                return mult * result

        return 0

    return sorted(items, cmp=comparer)


def _gen_order(keys, **kwargs):
    for key in keys:
        key = DotDict(key)
        field = key.get('field', **kwargs)
        sort_dir = key.get('dir', **kwargs)
        yield '%s%s' % (sort_dir == 'DESC' and '-' or '', field)


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

    Yields
    ------
    _OUTPUT : item
    """
    keys = util.listize(conf['KEY'])
    order = _gen_order(keys, **kwargs)

    for item in _multikeysort(_INPUT, order):
        yield item
