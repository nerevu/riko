# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.filter
~~~~~~~~~~~~~~~~~~~
Provides functions for filtering (including or excluding) items from a stream.

With Filter you create rules that compare item elements to values you specify.
So, for example, you may create a rule that says "permit items where the
item.description contains 'kittens'". Or a rule that says "omit any items where
the item.y:published is before yesterday".

A single Filter module can contain multiple rules. You can choose whether those
rules will Permit or Block items that match those rules. Finally, you can choose
whether an item must match all the rules, or if it can just match any rule.

Examples:
    basic usage::

        >>> from riko.modules.filter import pipe
        >>>
        >>> items = ({'x': x} for x in range(5))
        >>> rule = {'field': 'x', 'op': 'is', 'value': 3}
        >>> next(pipe(items, conf={'rule': rule})) == {'x': 3}
        True

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

import re
import operator as op

from decimal import Decimal, InvalidOperation

import pygogo as gogo

from builtins import *  # noqa pylint: disable=unused-import
from . import operator
from riko.parsers import parse_conf
from riko.cast import cast_date

OPTS = {'listize': True, 'extract': 'rule'}
DEFAULTS = {'combine': 'and', 'mode': 'permit'}
ITER_ATTRS = {'__next__', 'next', '__iter__'}
COMBINE_BOOLEAN = {'and': all, 'or': any}

SWITCH = {
    'contains': lambda x, y: x and y.lower() in x.lower(),
    'doesnotcontain': lambda x, y: x and y.lower() not in x.lower(),
    'matches': lambda x, y: re.search(y, x),
    'eq': op.eq,
    'is': op.eq,
    'isnot': op.ne,
    'truthy': bool,
    'falsy': op.not_,
    'greater': op.gt,
    'after': op.gt,
    'atleast': op.ge,
    'less': op.lt,
    'before': op.lt,
    'atmost': op.le,
}

logger = gogo.Gogo(__name__, monolog=True).logger
is_iterable = lambda item: ITER_ATTRS.intersection(dir(item))


def _parse_x_y(_x, _y):
    try:
        x = Decimal(_x)
        y = Decimal(_y)
    except (InvalidOperation, TypeError, ValueError):
        try:
            x = cast_date(_x)['date']
            y = cast_date(_y)['date']
        except (ValueError, KeyError, IndexError, TypeError):
            x, y = _x, _y

    return x, y


def parse_rule(rule, item, **kwargs):
    truthy_like = rule.op in {'truthy', 'falsy'}
    _x, _y = item.get(rule.field, **kwargs), rule.value
    has_value = _y is not None

    if has_value and not truthy_like:
        x, y = _parse_x_y(_x, _y)
    else:
        x, y = _x, _y

    if has_value or truthy_like:
        operation = SWITCH.get(rule.op)

    if truthy_like:
        result = operation(x)
    elif has_value:
        try:
            result = operation(x, y)
        except AttributeError:
            result = False
    else:
        result = False

    return result


def parser(stream, rules, tuples, **kwargs):
    """ Parses the pipe content

    Args:
        stream (Iter[dict]): The source. Note: this shares the `tuples`
            iterator, so consuming it will consume `tuples` as well.

        rules (List[obj]): the item independent rules (Objectify instances).

        tuples (Iter[(dict, obj)]): Iterable of tuples of (item, rules)
            `item` is an element in the source stream (a DotDict instance)
            and `rules` is the rule configuration (an Objectify instance).
            Note: this shares the `stream` iterator, so consuming it will
            consume `stream` as well.

        kwargs (dict): Keyword arguments.

    Yields:
        dict: The output

    Examples:
        >>> from meza.fntools import Objectify
        >>> from riko.dotdict import DotDict
        >>> from itertools import repeat
        >>>
        >>> conf = DotDict({'mode': 'permit', 'combine': 'and'})
        >>> kwargs = {'conf': conf}
        >>> rule = {'field': 'ex', 'op': 'greater', 'value': 3}
        >>> objrule = Objectify(rule)
        >>> stream = (DotDict({'ex': x}) for x in range(5))
        >>> tuples = zip(stream, repeat(objrule))
        >>> next(parser(stream, [objrule], tuples, **kwargs)) == {'ex': 4}
        True
    """
    conf = kwargs['conf']

    # TODO: add terminal check
    dynamic = any('subkey' in v for v in conf.values() if is_iterable(v))
    objconf = None if dynamic else parse_conf({}, conf=conf, objectify=True)

    for item in stream:
        if dynamic:
            objconf = parse_conf(item, conf=conf, objectify=True)

        permit = objconf.mode == 'permit'
        results = (parse_rule(rule, item, **kwargs) for rule in rules)

        try:
            result = COMBINE_BOOLEAN[objconf.combine](results)
        except KeyError:
            msg = "Invalid combine: %s. (Expected 'and' or 'or')"
            raise Exception(msg % objconf.combine)

        if (result and permit) or not (result or permit):
            yield item
        elif objconf.stop:
            break


@operator(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args, **kwargs):
    """An operator that asynchronously filters for source items matching
    the given rules.

    Args:
        items (Iter[dict]): The source.
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'rule'. May
            contain the keys 'mode', 'combine', or 'stop'.

            mode (str): returns the matches if set to 'permit', otherwise
                returns the non-matches (default: 'permit').

            rule (dict): can be either a dict or list of dicts. Must contain
                the keys 'field', 'op', and 'value'.

                field (str): the item field to search.
                op (str): the operation, must be one of 'contains',
                    'doesnotcontain', 'matches', 'is', 'isnot', 'truthy',
                    'falsy', 'greater', 'less', 'after', or 'before',
                    'atleast', 'atmost'.

                value (scalar): the value to compare the item's field to.

            combine (str): determines how to interpret multiple rules and must
                be either 'and' or 'or'. 'and' means all rules must pass, and
                'or' means any rule must pass (default: 'and')

            stop (bool): stop after first failure (default: False)

    Returns:
        Deferred: twisted.internet.defer.Deferred iterator of the filtered items

    Examples:
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> def run(reactor):
        ...     title = 'Website Developer'
        ...     callback = lambda x: print(next(x)['title'] == title)
        ...     items = [{'title': 'Good job!'}, {'title': title}]
        ...     rule = {'field': 'title', 'op': 'contains', 'value': 'web'}
        ...     d = async_pipe(items, conf={'rule': rule})
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        True
    """
    return parser(*args, **kwargs)


@operator(DEFAULTS, **OPTS)
def pipe(*args, **kwargs):
    """An operator that extracts items matching the given rules.

    Args:
        items (Iter[dict]): The source.
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'rule'. May
            contain the keys 'mode', 'combine', or 'stop'.

            mode (str): returns the matches if set to 'permit', otherwise
                returns the non-matches (default: 'permit').

            rule (dict): can be either a dict or list of dicts. Must contain
                the keys 'field', 'op', and 'value'.

                field (str): the item field to search.
                op (str): the operation, must be one of 'contains',
                    'doesnotcontain', 'matches', 'is', 'isnot', 'truthy',
                    'falsy', 'greater', 'less', 'after', or 'before',
                    'atleast', 'atmost'.

                value (scalar): the value to compare the item's field to.

            combine (str): determines how to interpret multiple rules and must
                be either 'and' or 'or'. 'and' means all rules must pass, and
                'or' means any rule must pass (default: 'and')

            stop (bool): stop after first failure (default: False)

        field (str): Item attribute from which to obtain the string to be
            tokenized (default: content)

    Yields:
        dict: the filtered items

    Examples:
        >>> title = 'Website Developer'
        >>> items = [{'title': 'Good job!'}, {'title': title}]
        >>> rule = {'field': 'title', 'op': 'contains', 'value': 'web'}
        >>> next(pipe(items, conf={'rule': rule})) == {'title': title}
        True
        >>> rule['value'] = 'kjhlked'
        >>> any(pipe(items, conf={'rule': [rule]}))
        False
        >>> items = ({'x': x} for x in range(5))
        >>> rule = {'field': 'x', 'op': 'less', 'value': 2}
        >>> result = pipe(items, conf={'rule': rule, 'stop': True})
        >>> len(list(result)) == 2
        True
    """
    return parser(*args, **kwargs)
