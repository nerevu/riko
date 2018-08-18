# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.itembuilder
~~~~~~~~~~~~~~~~~~~~~~~~
Provides functions for creating a single-item data source

With the Item Builder module, you can create a single-item data source by
assigning values to one or more item attributes. The module lets you assign
a value to an attribute.

Item Builder's strength is its ability to restructure and rename multiple
elements in a stream. When Item Builder is fed an input stream, the assigned
values can be existing attributes of the stream. These attributes can be
reassigned or used to create entirely new attributes.

Examples:
    basic usage::

        >>> from riko.modules.itembuilder import pipe
        >>>
        >>> attrs = {'key': 'title', 'value': 'the title'}
        >>> next(pipe(conf={'attrs': attrs}))['title'] == 'the title'
        True

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from builtins import *  # noqa pylint: disable=unused-import

from . import processor
import pygogo as gogo
from riko.dotdict import DotDict

OPTS = {'listize': True, 'extract': 'attrs', 'ftype': 'none'}
logger = gogo.Gogo(__name__, monolog=True).logger


def parser(_, attrs, skip=False, **kwargs):
    """ Parses the pipe content

    Args:
        _ (None): Ignored
        attrs (List[dict]): Attributes
        skip (bool): Don't parse the content
        kwargs (dict): Keyword arguments

    Kwargs:
        stream (dict): The original item

    Returns:
        Iter(dict): The stream of items

    Examples:
        >>> from meza.fntools import Objectify
        >>> attrs = [
        ...     {'key': 'title', 'value': 'the title'},
        ...     {'key': 'desc', 'value': 'the desc'}]
        >>> result = parser(None, map(Objectify, attrs))
        >>> result == {'title': 'the title', 'desc': 'the desc'}
        True
    """
    items = ((a.key, a.value) for a in attrs)
    return kwargs['stream'] if skip else DotDict(items)


@processor(isasync=True, **OPTS)
def async_pipe(*args, **kwargs):
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
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x)['title'])
        ...     attrs = [
        ...         {'key': 'title', 'value': 'the title'},
        ...         {'key': 'desc.content', 'value': 'the desc'}]
        ...
        ...     d = async_pipe(conf={'attrs': attrs})
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
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
        ...     'title': 'the title', 'desc': {'content': 'the desc'}}
        True
    """
    return parser(*args, **kwargs)
