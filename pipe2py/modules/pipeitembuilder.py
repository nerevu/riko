# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
pipe2py.modules.pipeitembuilder
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
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

        >>> from pipe2py.modules.pipeitembuilder import pipe
        >>> attrs = {'key': 'title', 'value': 'the title'}
        >>> pipe(conf={'attrs': attrs}).next()['title']
        u'the title'

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""

from __future__ import (
    absolute_import, division, print_function, with_statement,
    unicode_literals)

from itertools import imap
from twisted.internet.defer import inlineCallbacks, returnValue, maybeDeferred

from . import processor, FEEDS, FILES
from pipe2py.lib import utils
from pipe2py.lib.log import Logger
from pipe2py.twisted import utils as tu
from pipe2py.lib.dotdict import DotDict
from pipe2py.lib.utils import combine_dicts as cdicts

OPTS = {'listize': True, 'extract': 'attrs', 'emit': True, 'parser': 'params'}
logger = Logger(__name__).logger


def parser(_, attrs, skip, **kwargs):
    """ Parses the pipe content

    Args:
        _ (dict): The item (ignored)
        attrs (List[dict]): Attributes
        skip (bool): Don't parse the content
        kwargs (dict): Keyword argurments

    Kwargs:
        assign (str): Attribute to assign parsed content (default: content)
        feed (dict): The original item

    Returns:
        Tuple[Iter(dict), bool]: Tuple of (feed, skip)

    Examples:
        >>> attrs = [{'title': 'the title'}, {'desc': 'the desc'}]
        >>> result, skip = parser(None, attrs, False)
        >>> result.next() == {'title': 'the title', 'desc': 'the desc'}
        True
    """
    feed = kwargs['feed'] if skip else iter([DotDict(cdicts(*attrs))])
    return feed, skip


@processor(async=True, **OPTS)
def asyncPipe(*args, **kwargs):
    """A source that asynchronously builds an item.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        context (obj): pipe2py.Context object
        conf (dict): The pipe configuration. Must contain the key 'attrs'. May
            contain the key 'assign'.

            attrs (dict): can be either a dict or list of dicts. Must contain
                the keys 'key' and 'value'.

                key (str): the attribute name
                value (str): the attribute value

            assign (str): Attribute to assign parsed content (default: content)

        field (str): Item attribute from which to obtain the string to be
            tokenized (default: content)

    Returns:
        dict: twisted.internet.defer.Deferred an iterator of items

    Examples:
        >>> from twisted.internet.task import react
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(x.next()['title'])
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
        context (obj): pipe2py.Context object
        conf (dict): The pipe configuration. Must contain the key 'attrs'. May
            contain the key 'assign'.

            attrs (dict): can be either a dict or list of dicts. Must contain
                the keys 'key' and 'value'.

                key (str): the attribute name
                value (str): the attribute value

            assign (str): Attribute to assign parsed content (default: content)

        field (str): Item attribute from which to obtain the string to be
            tokenized (default: content)

    Yields:
        dict: an item

    Examples:
        >>> attrs = [
        ...     {'key': 'title', 'value': 'the title'},
        ...     {'key': 'desc.content', 'value': 'the desc'}]
        >>> pipe(conf={'attrs': attrs}).next() == {
        ...     u'title': 'the title', u'desc': {u'content': 'the desc'}}
        True
    """
    return parser(*args, **kwargs)

