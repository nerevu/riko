# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.pipeitembuilder
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Provides functions for creating a single-item data source

With the Item Builder module, you can create a single-item data source by
assigning values to one or more item attributes. The module lets you assign
a value to an attribute.

Item Builder's strength is its ability to restructure and rename multiple
elements in a feed. When Item Builder is fed an input feed, the assigned values
can be existing attributes of the input feed. These attributes can be reassigned
or used to create entirely new attributes.

Examples:
    basic usage::

        >>> from riko.modules.pipeitembuilder import pipe
        >>> attrs = {'key': 'title', 'value': 'the title'}
        >>> next(pipe(conf={'attrs': attrs}))['title']
        u'the title'

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from builtins import *

from . import processor
from riko.lib.log import Logger
from riko.lib.dotdict import DotDict

OPTS = {'listize': True, 'extract': 'attrs', 'ftype': 'none'}
logger = Logger(__name__).logger


def parser(_, attrs, skip, **kwargs):
    """ Parses the pipe content

    Args:
        _ (None): Ignored
        attrs (List[dict]): Attributes
        skip (bool): Don't parse the content
        kwargs (dict): Keyword arguments

    Kwargs:
        feed (dict): The original item

    Returns:
        Tuple[Iter(dict), bool]: Tuple of (feed, skip)

    Examples:
        >>> from riko.lib.utils import Objectify
        >>> attrs = [
        ...     {'key': 'title', 'value': 'the title'},
        ...     {'key': 'desc', 'value': 'the desc'}]
        >>> result, skip = parser(None, map(Objectify, attrs), False)
        >>> result == {'title': 'the title', 'desc': 'the desc'}
        True
    """
    items = ((a.key, a.value) for a in attrs)
    feed = kwargs['feed'] if skip else DotDict(items)
    return feed, skip


@processor(async=True, **OPTS)
def asyncPipe(*args, **kwargs):
    """A source that asynchronously builds an item.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'attrs'.

            attrs (dict): can be either a dict or list of dicts. Must contain
                the keys 'key' and 'value'.

                key (str): the attribute name
                value (str): the attribute value

    Returns:
        dict: twisted.internet.defer.Deferred an iterator of items

    Examples:
        >>> from twisted.internet.task import react
        >>> from riko.twisted import utils as tu
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x)['title'])
        ...     attrs = [
        ...         {'key': 'title', 'value': 'the title'},
        ...         {'key': 'desc.content', 'value': 'the desc'}]
        ...
        ...     d = asyncPipe(conf={'attrs': attrs})
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=tu.FakeReactor())
        ...     pass
        ... except SystemExit:
        ...     pass
        ...
        the title
    """
    return parser(*args, **kwargs)


@processor(**OPTS)
def pipe(*args, **kwargs):
    """A source that builds an item.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'attrs'.

            attrs (dict): can be either a dict or list of dicts. Must contain
                the keys 'key' and 'value'.

                key (str): the attribute name
                value (str): the attribute value

    Yields:
        dict: an item

    Examples:
        >>> attrs = [
        ...     {'key': 'title', 'value': 'the title'},
        ...     {'key': 'desc.content', 'value': 'the desc'}]
        >>> next(pipe(conf={'attrs': attrs})) == {
        ...     u'title': 'the title', u'desc': {u'content': 'the desc'}}
        True
    """
    return parser(*args, **kwargs)
