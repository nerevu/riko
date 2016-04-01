# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.piperename
~~~~~~~~~~~~~~~~~~~~~~~
Provides functions for renaming, copying, and deleting elements of a feed item.

There are several cases when this is useful, for example when the input data is
not in RSS format (e.g., elements are not named title, link, description, etc.)
and you want to output it as RSS, or when the input data contains geographic
data but their element names aren't recognized by the Location Extractor
module.

You rename an element by creating a mapping between the original name and a new
element name. You delete an element by not supplying a new element name. You
copy an element by setting the `copy` field to True.

Examples:
    basic usage::

        >>> from riko.modules.piperename import pipe
        >>> conf = {'rule': {'field': 'content', 'newval': 'greeting'}}
        >>> next(pipe({'content': 'hello world'}, conf=conf))
        {u'greeting': u'hello world'}

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
from riko.lib.dotdict import DotDict
from riko.lib.utils import combine_dicts as cdicts, remove_keys
from riko.twisted import utils as tu

OPTS = {'extract': 'rule', 'listize': True, 'emit': True}
DEFAULTS = {}
logger = Logger(__name__).logger


def reducer(item, rule):
    new_dict = {rule.newval: item.get(rule.field)} if rule.newval else {}
    old_dict = item if rule.copy else remove_keys(item, rule.field)
    return DotDict(cdicts(old_dict, new_dict))


@inlineCallbacks
def asyncParser(item, rules, skip, **kwargs):
    """ Asynchronously parses the pipe content

    Args:
        item (obj): The entry to process (a DotDict instance)
        rules (List[obj]): the parsed rules (Objectify instances).
        skip (bool): Don't parse the content
        kwargs (dict): Keyword arguments

    Kwargs:
        feed (dict): The original item

    Returns:
        Deferred: twisted.internet.defer.Deferred Tuple of (item, skip)

    Examples:
        >>> from twisted.internet.task import react
        >>> from riko.lib.dotdict import DotDict
        >>> from riko.lib.utils import Objectify
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(x[0])
        ...     item = DotDict({'content': 'hello world'})
        ...     rule = {'field': 'content', 'newval': 'greeting'}
        ...     kwargs = {'feed': item}
        ...     d = asyncParser(item, [Objectify(rule)], False, **kwargs)
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=tu.FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        {u'greeting': u'hello world'}
    """
    if skip:
        item = kwargs['feed']
    else:
        item = yield tu.coopReduce(reducer, rules, item)

    result = (item, skip)
    returnValue(result)


def parser(item, rules, skip, **kwargs):
    """ Parsers the pipe content

    Args:
        item (obj): The entry to process (a DotDict instance)
        rules (List[obj]): the parsed rules (Objectify instances).
        skip (bool): Don't parse the content
        kwargs (dict): Keyword arguments

    Kwargs:
        feed (dict): The original item

    Returns:
        Tuple (dict, bool): Tuple of (item, skip)

    Examples:
        >>> from riko.lib.dotdict import DotDict
        >>> from riko.lib.utils import Objectify
        >>>
        >>> item = DotDict({'content': 'hello world'})
        >>> rule = {'field': 'content', 'newval': 'greeting'}
        >>> kwargs = {'feed': item}
        >>> parser(item, [Objectify(rule)], False, **kwargs)[0]
        {u'greeting': u'hello world'}
    """
    item = kwargs['feed'] if skip else reduce(reducer, rules, item)
    return item, skip


@processor(DEFAULTS, async=True, **OPTS)
def asyncPipe(*args, **kwargs):
    """A processor module that asynchronously renames or copies fields in a
    feed item.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'rule'.

            rule (dict): can be either a dict or list of dicts. Must contain
                the key 'field'.

                field (str): The item attribute to rename
                newval (str): The new item attribute name
                copy (bool): Copy the item attribute instead of renaming it
                    (default: False)

    Returns:
       Deferred: twisted.internet.defer.Deferred item with concatenated content

    Examples:
        >>> from twisted.internet.task import react
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x))
        ...     conf = {'rule': {'field': 'content', 'newval': 'greeting'}}
        ...     d = asyncPipe({'content': 'hello world'}, conf=conf)
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=tu.FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        {u'greeting': u'hello world'}
    """
    return asyncParser(*args, **kwargs)


@processor(**OPTS)
def pipe(*args, **kwargs):
    """A processor that renames or copies fields in a feed item.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'rule'.

            rule (dict): can be either a dict or list of dicts. Must contain
                the key 'field'. May contain the keys 'newval' or 'copy'.

                field (str): The item attribute to rename
                newval (str): The new item attribute name (default: None). If
                    blank, the field will be deleted.

                copy (bool): Copy the item attribute instead of renaming it
                    (default: False)

    Yields:
        dict: an item with concatenated content

    Examples:
        >>> rule = {'field': 'content', 'newval': 'greeting'}
        >>> next(pipe({'content': 'hello world'}, conf={'rule': rule}))
        {u'greeting': u'hello world'}
        >>> conf = {'rule': {'field': 'content'}}
        >>> next(pipe({'content': 'hello world'}, conf=conf))
        {}
        >>> rule['copy'] = True
        >>> result = pipe({'content': 'hello world'}, conf={'rule': rule})
        >>> sorted(next(result).keys())
        [u'content', u'greeting']
    """
    return parser(*args, **kwargs)
