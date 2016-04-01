# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.pipestrreplace
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Provides functions for string search-and-replace.

You provide the module with the text string to search for, and what to replace
it with. Multiple search-and-replace pairs can be added. You can specify to
replace all occurrences of the search string, just the first occurrence, or the
last occurrence.

Examples:
    basic usage::

        >>> from riko.modules.pipestrreplace import pipe
        >>> conf = {'rule': {'find': 'hello', 'replace': 'bye'}}
        >>> next(pipe({'content': 'hello world'}, conf=conf))['strreplace']
        'bye world'

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from functools import reduce

from builtins import *
from twisted.internet.defer import inlineCallbacks, returnValue

from . import processor
from riko.lib.log import Logger
from riko.twisted import utils as tu

OPTS = {
    'listize': True, 'ftype': 'text', 'field': 'content', 'extract': 'rule'}

DEFAULTS = {}
logger = Logger(__name__).logger

PARAMS = {
    'first': lambda word, rule: word.replace(rule.find, rule.replace, 1),
    'last': lambda word, rule: rule.replace.join(word.rsplit(rule.find, 1)),
    'every': lambda word, rule: word.replace(rule.find, rule.replace),
}


def reducer(word, rule):
    return PARAMS.get(rule.param, PARAMS['every'])(word, rule)


@inlineCallbacks
def asyncParser(word, rules, skip, **kwargs):
    """ Asynchronously parses the pipe content

    Args:
        word (str): The string to transform
        rules (List[obj]): the parsed rules (Objectify instances).
        skip (bool): Don't parse the content
        kwargs (dict): Keyword arguments

    Kwargs:
        assign (str): Attribute to assign parsed content (default: exchangerate)
        feed (dict): The original item

    Returns:
        Deferred: twisted.internet.defer.Deferred Tuple of (item, skip)

    Examples:
        >>> from twisted.internet.task import react
        >>> from riko.lib.utils import Objectify
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(x[0])
        ...     item = {'content': 'hello world'}
        ...     conf = {'rule': {'find': 'hello', 'replace': 'bye'}}
        ...     rule = Objectify(conf['rule'])
        ...     kwargs = {'feed': item, 'conf': conf}
        ...     d = asyncParser(item['content'], [rule], False, **kwargs)
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=tu.FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        bye world
    """
    if skip:
        value = kwargs['feed']
    else:
        value = yield tu.coopReduce(reducer, rules, word)

    result = (value, skip)
    returnValue(result)


def parser(word, rules, skip, **kwargs):
    """ Parses the pipe content

    Args:
        word (str): The string to transform
        rules (List[obj]): the parsed rules (Objectify instances).
        skip (bool): Don't parse the content
        kwargs (dict): Keyword arguments

    Kwargs:
        assign (str): Attribute to assign parsed content (default: strtransform)
        feed (dict): The original item

    Returns:
        Tuple(dict, bool): Tuple of (item, skip)

    Examples:
        >>> from riko.lib.utils import Objectify
        >>>
        >>> item = {'content': 'hello world'}
        >>> conf = {'rule': {'find': 'hello', 'replace': 'bye'}}
        >>> rule = Objectify(conf['rule'])
        >>> kwargs = {'feed': item, 'conf': conf}
        >>> parser(item['content'], [rule], False, **kwargs)[0]
        u'bye world'
    """
    value = kwargs['feed'] if skip else reduce(reducer, rules, word)
    return value, skip


@processor(DEFAULTS, async=True, **OPTS)
def asyncPipe(*args, **kwargs):
    """A processor module that asynchronously replaces the text of a field of a
    feed item.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'rule'.

            rule (dict): can be either a dict or list of dicts. Must contain
                the keys 'find' and 'replace'. May contain the key 'param'.

                find (str): The string to find.
                replace (str): The string replacement.
                param (str): The type of replacement. Must be one of: 'first',
                    'last', or 'every' (default: 'every').

        assign (str): Attribute to assign parsed content (default: strreplace)
        field (str): Item attribute from which to obtain the first number to
            operate on (default: 'content')

    Returns:
       Deferred: twisted.internet.defer.Deferred item with replaced content

    Examples:
        >>> from twisted.internet.task import react
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x)['strreplace'])
        ...     conf = {'rule': {'find': 'hello', 'replace': 'bye'}}
        ...     d = asyncPipe({'content': 'hello world'}, conf=conf)
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=tu.FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        bye world
    """
    return asyncParser(*args, **kwargs)


@processor(**OPTS)
def pipe(*args, **kwargs):
    """A processor that replaces the text of a field of a feed item.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'rule'.

            rule (dict): can be either a dict or list of dicts. Must contain
                the keys 'find' and 'replace'. May contain the key 'param'.

                find (str): The string to find.
                replace (str): The string replacement.
                param (str): The type of replacement. Must be one of: 'first',
                    'last', or 'every' (default: 'every').

        assign (str): Attribute to assign parsed content (default: strreplace)
        field (str): Item attribute from which to obtain the first number to
            operate on (default: 'content')

    Yields:
        dict: an item with replaced content

    Examples:
        >>> conf = {'rule': {'find': 'hello', 'replace': 'bye'}}
        >>> next(pipe({'content': 'hello world'}, conf=conf))['strreplace']
        'bye world'
        >>> rules = [
        ...     {'find': 'Gr', 'replace': 'M'},
        ...     {'find': 'e', 'replace': 'a', 'param': 'last'}]
        >>> conf = {'rule': rules}
        >>> kwargs = {'conf': conf, 'field': 'title', 'assign': 'result'}
        >>> next(pipe({'title': 'Greetings'}, **kwargs))['result']
        u'Meatings'
    """
    return parser(*args, **kwargs)
