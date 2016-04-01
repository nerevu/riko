# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.pipesubelement
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Provides functions for extracting sub-elements from a feed item

Sometimes the data you need from a feed is buried deep in its hierarchy. You
need to extract just those select sub-elements from the feed. This is what the
Sub-element module is for.

Let's suppose we have a Sonnet of William Shakespeare rendered as an item, with
the structure as shown in this (abbreviated) example.

    {
        'author': 'William Shakespeare',
        'title': 'Sonnet 21',
        'stanzas': [
            {
                'id': 'st1',
                'verses': ["So is it not with me...", "Stirr'd by a paint...,"]
            }, {
                'id': 'st2',
                ...
            },
            ...
        ]
    }

When fed the path 'stanza.verse', the Sub-element module will extract just the
verses from each stanza (and any child elements), and discard all the fields
above them (stanza, title, and author).

Examples:
    basic usage::

        >>> from riko.modules.pipesubelement import pipe
        >>>
        >>> sonnet = {
        ...     'author': 'William Shakespeare',
        ...     'title': 'Sonnet 21',
        ...     'stanzas': [
        ...         {'id': 'st1', 'verses': ['st1v1', 'st1v2', 'st1v3']},
        ...         {'id': 'st2', 'verses': ['st2v1', 'st2v2', 'st2v3']},
        ...         {'id': 'st3', 'verses': ['st3v1', 'st3v2', 'st3v3']}]}
        >>>
        >>> next(pipe(sonnet, conf={'path': 'stanzas.verses'}))
        {u'content': u'st1v1'}

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from builtins import *

from . import processor
from riko.lib import utils
from riko.lib.log import Logger

OPTS = {'emit': True}
DEFAULTS = {'token_key': 'content'}
logger = Logger(__name__).logger


def parser(item, objconf, skip, **kwargs):
    """ Parses the pipe content

    Args:
        item (obj): The entry to process (a DotDict instance)
        objconf (obj): The pipe configuration (an Objectify instance)
        skip (bool): Don't parse the content

    Returns:
        Tuple(Iter[dict], bool): Tuple of (feed, skip)

    Examples:
        >>> from riko.lib.dotdict import DotDict
        >>>
        >>> sonnet = {'stanzas': [{'verses': ['verse1', 'verse2']}]}
        >>> conf = {'path': 'stanzas.verses', 'token_key': 'content'}
        >>> objconf = utils.Objectify(conf)
        >>> next(parser(DotDict(sonnet), objconf, False)[0])
        {u'content': u'verse1'}
        >>> sonnet = {'stanzas': {'verses': ['verse1', 'verse2']}}
        >>> next(parser(DotDict(sonnet), objconf, False)[0])
        {u'content': u'verse1'}
        >>> sonnet = {'stanzas': {'verses': 'verse1'}}
        >>> next(parser(DotDict(sonnet), objconf, False)[0])
        {u'content': u'verse1'}
    """
    if skip:
        feed = kwargs['feed']
    else:
        element = item.get(objconf.path, **kwargs)
        feed = utils.gen_items(element, objconf.token_key)

    return feed, skip


@processor(DEFAULTS, async=True, **OPTS)
def asyncPipe(*args, **kwargs):
    """A processor that asynchronously extracts sub-elements for the item of a
    feed.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'path'. May
            contain the key 'token_key'.

            path (str): Path to the element to extract
            token_key (str): Attribute to assign individual tokens (default:
                content)

    Returns:
       Deferred: twisted.internet.defer.Deferred sub-element item

    Examples:
        >>> from twisted.internet.task import react
        >>> from riko.twisted import utils as tu
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x))
        ...     sonnet = {'stanzas': [{'verses': ['verse1', 'verse2']}]}
        ...     conf = {'path': 'stanzas.verses'}
        ...     d = asyncPipe(sonnet, conf=conf)
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=tu.FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        {u'content': u'verse1'}
    """
    return parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs):
    """A processor that extracts sub-elements for the item of a feed.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'path'. May
            contain the key 'token_key'.

            path (str): Path to the element to extract
            token_key (str): Attribute to assign individual tokens (default:
                content)

    Yields:
        dict: a sub-element item

    Examples:
        >>> sonnet = {
        ...     'author': 'William Shakespeare',
        ...     'title': 'Sonnet 21',
        ...     'stanzas': [
        ...         {'id': 'st1', 'verses': ['st1v1', 'st1v2', 'st1v3']},
        ...         {'id': 'st2', 'verses': ['st2v1', 'st2v2', 'st2v3']},
        ...         {'id': 'st3', 'verses': ['st3v1', 'st3v2', 'st3v3']}]}
        >>>
        >>> conf = {'path': 'stanzas.verses'}
        >>> verses = list(pipe(sonnet, conf=conf))
        >>> len(verses)
        9
        >>> verses[0]
        {u'content': u'st1v1'}
        >>> verses[8]
        {u'content': u'st3v3'}
        >>> conf.update({'token_key': 'verse'})
        >>> next(pipe(sonnet, conf=conf))
        {u'verse': u'st1v1'}
    """
    return parser(*args, **kwargs)
