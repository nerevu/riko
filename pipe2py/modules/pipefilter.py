# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipefilter
    ~~~~~~~~~~~~~~~~~~~~~~~~~~

    Provides methods for filtering (including or excluding) items from a feed.

    http://pipes.yahoo.com/pipes/docs?doc=operators#Filter
"""

import re

from datetime import datetime as dt
from decimal import Decimal, InvalidOperation
from functools import partial
from itertools import imap, repeat, ifilter
from pipe2py.lib import utils
from pipe2py.lib.dotdict import DotDict


COMBINE_BOOLEAN = {'and': all, 'or': any}
SWITCH = {
    # todo: check which of these should be case insensitive
    # todo: use regex?
    'contains': lambda x, y: x and x.lower() in y.lower(),
    'doesnotcontain': lambda x, y: x and x.lower() not in y.lower(),
    'matches': lambda x, y: re.search(x, y),
    'is': lambda x, y: cmp(x, y) is 0,
    'greater': lambda x, y: cmp(x, y) is -1,
    'less': lambda x, y: cmp(x, y) is 1,
    'after': lambda x, y: cmp(x, y) is -1,
    'before': lambda x, y: cmp(x, y) is 1,
}


def parse_result(results, item, _pass, permit=True):
    if _pass:
        _output = item
    elif not ((results and permit) or (not results and not permit)):
        _output = None
    else:
        _output = item

    return _output


def parse_rule(rule, item, **kwargs):
    if not rule.value:
        result = True
    else:
        try:
            x = Decimal(rule.value)
            y = Decimal(item.get(rule.field, **kwargs))
        except InvalidOperation:
            x = rule.value
            y = item.get(rule.field)

        if y is None:
            result = False
        elif isinstance(y, basestring):
            try:
                y = dt.strptime(y, utils.DATE_FORMAT).timetuple()
            except ValueError:
                pass

        try:
            result = SWITCH.get(rule.op)(x, y)
        except (UnicodeDecodeError, AttributeError):
            result = False

    return result


def parse_rules(rules, item, _pass, **kwargs):
    results = imap(partial(parse_rule, **kwargs), rules, repeat(item))
    return (results, item, _pass)


def pipe_filter(context=None, _INPUT=None, conf=None, **kwargs):
    """An operator that filters for source items matching the given rules.
    Not loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : pipe2py.modules pipe like object (iterable of items)
    conf : {
        'MODE': {'value': <'permit' or 'block'>},
        'COMBINE': {'value': <'and' or 'or'>}
        'RULE': [
            {
                'field': {'value': 'search field'},
                'op': {'value': 'one of SWITCH above'},
                'value': {'value': 'search term'}
            }
        ]
    }

    kwargs : other inputs, e.g., to feed terminals for rule values

    Returns
    -------
    _OUTPUT : generator of filtered items

    Examples
    --------
    >>> import os.path as p
    >>> from pipe2py.modules.pipeforever import pipe_forever
    >>> from pipe2py.modules.pipefetchdata import pipe_fetchdata
    >>> parent = p.dirname(p.dirname(__file__))
    >>> file_name = p.abspath(p.join(parent, 'data', 'gigs.json'))
    >>> path = 'value.items'
    >>> url = 'file://%s' % file_name
    >>> conf = {'URL': {'value': url}, 'path': {'value': path}}
    >>> input = pipe_fetchdata(_INPUT=pipe_forever(), conf=conf)
    >>> mode = {'value': 'permit'}
    >>> combine = {'value': 'and'}
    >>> rule = [{'field': {'value': 'title'}, 'op': {'value': 'contains'}, \
'value': {'value': 'web'}}]
    >>> conf = {'MODE': mode, 'COMBINE': combine, 'RULE': rule}
    >>> pipe_filter(_INPUT=input, conf=conf).next()['title']
    u'E-Commerce Website Developer | Elance Job'
    >>> rule = [{'field': {'value': 'title'}, 'op': {'value': 'contains'}, \
'value': {'value': 'kjhlked'}}]
    >>> conf = {'MODE': mode, 'COMBINE': combine, 'RULE': rule}
    >>> list(pipe_filter(_INPUT=input, conf=conf))
    []
    """
    conf = DotDict(conf)
    test = kwargs.pop('pass_if', None)
    permit = conf.get('MODE', **kwargs) == 'permit'
    combine = conf.get('COMBINE', **kwargs)

    if not combine in ['and', 'or']:
        raise Exception(
            "Invalid combine: %s. (Expected 'and' or 'or')" % combine)

    rule_defs = imap(DotDict, utils.listize(conf['RULE']))
    get_pass = partial(utils.get_pass, test=test)
    parse_conf = partial(utils.parse_conf, **kwargs)
    get_rules = lambda i: imap(parse_conf, rule_defs, repeat(i))
    funcs = [COMBINE_BOOLEAN[combine], utils.passthrough, utils.passthrough]

    inputs = imap(DotDict, _INPUT)
    splits = utils.split_input(inputs, get_rules, utils.passthrough, get_pass)
    outputs = utils.get_output(splits, partial(parse_rules, **kwargs))
    parsed = utils.parse_splits(outputs, *funcs)
    _OUTPUT = utils.get_output(parsed, partial(parse_result, permit=permit))
    return _OUTPUT
