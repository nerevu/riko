# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.pipefilter
~~~~~~~~~~~~~~~~~~~~~~~
Provides functions for filtering (including or excluding) items from a feed.

With Filter you create rules that compare feed elements to values you specify.
So, for example, you may create a rule that says "permit items where the
item.description contains 'kittens'". Or a rule that says "omit any items where
the item.y:published is before yesterday".

A single Filter module can contain multiple rules. You can choose whether those
rules will Permit or Block items that match those rules. Finally, you can choose
whether an item must match all the rules, or if it can just match any rule.

Examples:
    basic usage::

        >>> from riko.modules.pipefilter import pipe
        >>> items = ({'x': x} for x in range(5))
        >>> rule = {'field': 'x', 'op': 'is', 'value': 3}
        >>> next(pipe(items, conf={'rule': rule}))
        {u'x': 3}

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

import re
import operator as op

from decimal import Decimal, InvalidOperation

from builtins import *

from . import operator
from riko.lib import utils
from riko.lib.utils import parse_conf
from riko.lib.log import Logger

OPTS = {'listize': True, 'extract': 'rule'}
DEFAULTS = {'combine': 'and', 'mode': 'permit'}
logger = Logger(__name__).logger

COMBINE_BOOLEAN = {'and': all, 'or': any}
SWITCH = {
    'contains': lambda x, y: x and y.lower() in x.lower(),
    'doesnotcontain': lambda x, y: x and y.lower() not in x.lower(),
    'matches': lambda x, y: re.search(x, y),
    'is': op.eq,
    'greater': op.gt,
    'after': op.gt,
    'less': op.lt,
    'before': op.lt,
}


def parse_rule(rule, item, **kwargs):
    if rule.value is None:
        result = True
    else:
        result = None
        x = item.get(rule.field, **kwargs)
        y = rule.value

    if not result and y is None:
        result = False
    else:
        try:
            _x = Decimal(x)
            _y = Decimal(y)
        except (InvalidOperation, TypeError):
            try:
                _x = utils.cast_date(x)
                _y = utils.cast_date(y)
            except ValueError:
                pass
            else:
                x, y = _x, _y
        else:
            x, y = _x, _y

        try:
            result = SWITCH.get(rule.op)(x, y)
        except (UnicodeDecodeError, AttributeError):
            result = False

    return result


def parser(feed, rules, tuples, **kwargs):
    """ Parses the pipe content

    Args:
        feed (Iter[dict]): The source feed. Note: this shares the `tuples`
            iterator, so consuming it will consume `tuples` as well.

        rules (List[obj]): the item independent rules (Objectify instances).

        tuples (Iter[(dict, obj)]): Iterable of tuples of (item, rules)
            `item` is an element in the source feed (a DotDict instance)
            and `rules` is the rule configuration (an Objectify instance).
            Note: this shares the `feed` iterator, so consuming it will
            consume `feed` as well.

        kwargs (dict): Keyword arguments.

    Yields:
        dict: The output

    Examples:
        >>> from riko.lib.utils import Objectify
        >>> from riko.lib.dotdict import DotDict
        >>> from itertools import repeat
        >>>
        >>> conf = DotDict({'mode': 'permit', 'combine': 'and'})
        >>> kwargs = {'conf': conf}
        >>> rule = {'field': 'ex', 'op': 'greater', 'value': 3}
        >>> objrule = Objectify(rule)
        >>> feed = (DotDict({'ex': x}) for x in range(5))
        >>> tuples = zip(feed, repeat(objrule))
        >>> next(parser(feed, [objrule], tuples, **kwargs))
        {u'ex': 4}
    """
    conf = kwargs['conf']
    # TODO: add terminal check
    dynamic = any('subkey' in v for v in conf.values())
    objconf = None if dynamic else parse_conf({}, conf=conf, objectify=True)

    for item in feed:
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


@operator(DEFAULTS, async=True, **OPTS)
def asyncPipe(*args, **kwargs):
    """An operator that asynchronously filters for source items matching
    the given rules.

    Args:
        items (Iter[dict]): The source feed.
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'rule'. May
            contain the keys 'mode', or 'combine'.

            mode (str): returns the matches if set to 'permit', otherwise
                returns the non-matches (default: 'permit').

            rule (dict): can be either a dict or list of dicts. Must contain
                the keys 'field', 'op', and 'value'.

                field (str): the item field to search.
                op (str): the operation, must be one of 'contains',
                    'doesnotcontain', 'matches', 'is', 'greater', 'less',
                    'after', or 'before'.

                value (scalar): the value to compare the item's field to.

            combine (str): determines how to interpret multiple rules and must
                be either 'and' or 'or'. 'and' means all rules must pass, and
                'or' means any rule must pass (default: 'and')

    Returns:
        Deferred: twisted.internet.defer.Deferred iterator of the filtered items

    Examples:
        >>> from twisted.internet.task import react
        >>> from riko.twisted import utils as tu
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x))
        ...     items = [{'title': 'Good job!'}, {'title': 'Website Developer'}]
        ...     rule = {'field': 'title', 'op': 'contains', 'value': 'web'}
        ...     d = asyncPipe(items, conf={'rule': rule})
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=tu.FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        {u'title': u'Website Developer'}
    """
    return parser(*args, **kwargs)


@operator(DEFAULTS, **OPTS)
def pipe(*args, **kwargs):
    """An operator that extracts items matching the given rules.

    Args:
        items (Iter[dict]): The source feed.
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'rule'. May
            contain the keys 'mode', or 'combine'.

            mode (str): returns the matches if set to 'permit', otherwise
                returns the non-matches (default: 'permit').

            rule (dict): can be either a dict or list of dicts. Must contain
                the keys 'field', 'op', and 'value'.

                field (str): the item field to search.
                op (str): the operation, must be one of 'contains',
                    'doesnotcontain', 'matches', 'is', 'greater', 'less',
                    'after', or 'before'.

                value (scalar): the value to compare the item's field to.

            combine (str): determines how to interpret multiple rules and must
                be either 'and' or 'or'. 'and' means all rules must pass, and
                'or' means any rule must pass (default: 'and')

        field (str): Item attribute from which to obtain the string to be
            tokenized (default: content)

    Yields:
        dict: the filtered items

    Examples:
        >>> items = [{'title': 'Good job!'}, {'title': 'Website Developer'}]
        >>> rule = {'field': 'title', 'op': 'contains', 'value': 'web'}
        >>> next(pipe(items, conf={'rule': rule}))
        {u'title': u'Website Developer'}
        >>> rule['value'] = 'kjhlked'
        >>> any(pipe(items, conf={'rule': [rule]}))
        False
    """
    return parser(*args, **kwargs)
