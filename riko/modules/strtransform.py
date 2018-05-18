# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.strtransform
~~~~~~~~~~~~~~~~~~~~~~~~~
Provides functions for performing string transformations on text, e.g.,
capitalize, uppercase, etc.

Examples:
    basic usage::

        >>> from riko.modules.strtransform import pipe
        >>>
        >>> conf = {'rule': {'transform': 'title'}}
        >>> item = {'content': 'hello world'}
        >>> next(pipe(item, conf=conf))['strtransform'] == 'Hello World'
        True

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

import pygogo as gogo

from functools import reduce
from builtins import *  # noqa pylint: disable=unused-import

from . import processor
from riko.bado import coroutine, return_value, itertools as ait

OPTS = {
    'listize': True, 'ftype': 'text', 'field': 'content', 'extract': 'rule'}

DEFAULTS = {}
logger = gogo.Gogo(__name__, monolog=True).logger

ATTRS = {
    'capitalize', 'lower', 'upper', 'swapcase', 'title', 'strip', 'rstrip',
    'lstrip', 'zfill', 'replace', 'count', 'find'}


def reducer(word, rule):
    if rule.transform in ATTRS:
        args = rule.args.split(',') if rule.args else []
        result = getattr(word, rule.transform)(*args)
    else:
        logger.warning('Invalid transformation: %s', rule.transform)
        result = word

    return result


@coroutine
def async_parser(word, rules, skip=False, **kwargs):
    """ Asynchronously parses the pipe content

    Args:
        word (str): The string to transform
        rules (List[obj]): the parsed rules (Objectify instances).
        skip (bool): Don't parse the content
        kwargs (dict): Keyword arguments

    Kwargs:
        assign (str): Attribute to assign parsed content (default: strtransform)
        stream (dict): The original item

    Returns:
        Deferred: twisted.internet.defer.Deferred item

    Examples:
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>> from meza.fntools import Objectify
        >>>
        >>> def run(reactor):
        ...     item = {'content': 'hello world'}
        ...     conf = {'rule': {'transform': 'title'}}
        ...     rule = Objectify(conf['rule'])
        ...     kwargs = {'stream': item, 'conf': conf}
        ...     d = async_parser(item['content'], [rule], **kwargs)
        ...     return d.addCallbacks(print, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        Hello World
    """
    if skip:
        value = kwargs['stream']
    else:
        value = yield ait.coop_reduce(reducer, rules, word)

    return_value(value)


def parser(word, rules, skip=False, **kwargs):
    """ Parses the pipe content

    Args:
        word (str): The string to transform
        rules (List[obj]): the parsed rules (Objectify instances).
        skip (bool): Don't parse the content
        kwargs (dict): Keyword arguments

    Kwargs:
        assign (str): Attribute to assign parsed content (default: strtransform)
        stream (dict): The original item

    Returns:
        dict: The item

    Examples:
        >>> from meza.fntools import Objectify
        >>>
        >>> item = {'content': 'hello world'}
        >>> conf = {'rule': {'transform': 'title'}}
        >>> rule = Objectify(conf['rule'])
        >>> args = item['content'], [rule], False
        >>> kwargs = {'stream': item, 'conf': conf}
        >>> parser(*args, **kwargs) == 'Hello World'
        True
    """
    return kwargs['stream'] if skip else reduce(reducer, rules, word)


@processor(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args, **kwargs):
    """A processor module that asynchronously performs string transformations
    on the field of an item.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'rule'.

            rule (dict): can be either a dict or list of dicts. Must contain
                the key 'transform'. May contain the key 'args'

                transform (str): The string transformation to apply. Must be
                    one of: 'capitalize', 'lower', 'upper', 'swapcase',
                    'title', 'strip', 'rstrip', 'lstrip', 'zfill', 'replace',
                    'count', or 'find'

                args (str): A comma separated list of arguments to supply the
                    transformer.

        assign (str): Attribute to assign parsed content (default: strtransform)
        field (str): Item attribute to operate on (default: 'content')

    Returns:
       Deferred: twisted.internet.defer.Deferred item with transformed content

    Examples:
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x)['strtransform'])
        ...     conf = {'rule': {'transform': 'title'}}
        ...     d = async_pipe({'content': 'hello world'}, conf=conf)
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        Hello World
    """
    return async_parser(*args, **kwargs)


@processor(**OPTS)
def pipe(*args, **kwargs):
    """A processor that performs string transformations on the field of an item.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'rule'.

            rule (dict): can be either a dict or list of dicts. Must contain
                the key 'transform'. May contain the key 'args'

                transform (str): The string transformation to apply. Must be
                    one of: 'capitalize', 'lower', 'upper', 'swapcase',
                    'title', 'strip', 'rstrip', 'lstrip', 'zfill', 'replace',
                    'count', or 'find'

                args (str): A comma separated list of arguments to supply the
                    transformer.

        assign (str): Attribute to assign parsed content (default: strtransform)
        field (str): Item attribute to operate on (default: 'content')

    Yields:
        dict: an item with transformed content

    Examples:
        >>> conf = {'rule': {'transform': 'title'}}
        >>> item = {'content': 'hello world'}
        >>> next(pipe(item, conf=conf))['strtransform'] == 'Hello World'
        True
        >>> rules = [
        ...     {'transform': 'lower'}, {'transform': 'count', 'args': 'g'}]
        >>> conf = {'rule': rules}
        >>> kwargs = {'conf': conf, 'field': 'title', 'assign': 'result'}
        >>> next(pipe({'title': 'Greetings'}, **kwargs))['result']
        2
    """
    return parser(*args, **kwargs)
