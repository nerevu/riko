# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.subelement
~~~~~~~~~~~~~~~~~~~~~~~
Provides functions for extracting sub-elements from an item

Sometimes the data you need from a stream is buried deep in its hierarchy. You
need to extract just those select sub-elements from the stream. This is what the
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

        >>> from riko.modules.subelement import pipe
        >>>
        >>> sonnet = {
        ...     'author': 'William Shakespeare',
        ...     'title': 'Sonnet 21',
        ...     'stanzas': [
        ...         {'id': 'st1', 'verses': ['st1v1', 'st1v2', 'st1v3']},
        ...         {'id': 'st2', 'verses': ['st2v1', 'st2v2', 'st2v3']},
        ...         {'id': 'st3', 'verses': ['st3v1', 'st3v2', 'st3v3']}]}
        >>>
        >>> conf = {'path': 'stanzas.verses'}
        >>> next(pipe(sonnet, conf=conf)) == {'content': 'st1v1'}
        True

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from builtins import *  # noqa pylint: disable=unused-import

from . import processor
from riko.utils import gen_items
import pygogo as gogo

OPTS = {'emit': True}
DEFAULTS = {'token_key': 'content'}
logger = gogo.Gogo(__name__, monolog=True).logger


def parser(item, objconf, skip=False, **kwargs):
    """ Parses the pipe content

    Args:
        item (obj): The entry to process (a DotDict instance)
        objconf (obj): The pipe configuration (an Objectify instance)
        skip (bool): Don't parse the content

    Returns:
        Iter[dict]: The stream of items

    Examples:
        >>> from riko.dotdict import DotDict
        >>> from meza.fntools import Objectify
        >>>
        >>> conf = {'path': 'stanzas.verses', 'token_key': 'content'}
        >>> objconf = Objectify(conf)
        >>> args = [objconf, False]
        >>>
        >>> sonnet = {'stanzas': [{'verses': ['verse1', 'verse2']}]}
        >>> next(parser(DotDict(sonnet), *args)) == {'content': 'verse1'}
        True
        >>> sonnet = {'stanzas': {'verses': ['verse1', 'verse2']}}
        >>> next(parser(DotDict(sonnet), *args)) == {'content': 'verse1'}
        True
        >>> sonnet = {'stanzas': {'verses': 'verse1'}}
        >>> next(parser(DotDict(sonnet), *args)) == {'content': 'verse1'}
        True
    """
    if skip:
        stream = kwargs['stream']
    else:
        element = item.get(objconf.path, **kwargs)
        stream = gen_items(element, objconf.token_key)

    return stream


@processor(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args, **kwargs):
    """A processor that asynchronously extracts sub-elements from an item.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'path'. May
            contain the key 'token_key'.

            path (str): Path to the element to extract
            token_key (str): Attribute to assign individual tokens (default:
                content). Set to `None` to output raw text.

        assign (str): Attribute to assign parsed content (default: subelement)

    Returns:
       Deferred: twisted.internet.defer.Deferred sub-element item

    Examples:
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x) == {'content': 'verse1'})
        ...     sonnet = {'stanzas': [{'verses': ['verse1', 'verse2']}]}
        ...     conf = {'path': 'stanzas.verses'}
        ...     d = async_pipe(sonnet, conf=conf)
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


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs):
    """A processor that extracts sub-elements from an item.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'path'. May
            contain the key 'token_key'.

            path (str): Path to the element to extract
            token_key (str): Attribute to assign individual tokens (default:
                content). Set to `None` to output raw text.

        assign (str): Attribute to assign parsed content (default: subelement)

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
        >>> verses[0] == {'content': 'st1v1'}
        True
        >>> verses[8] == {'content': 'st3v3'}
        True
        >>> conf.update({'token_key': 'verse'})
        >>> next(pipe(sonnet, conf=conf)) == {'verse': 'st1v1'}
        True
    """
    return parser(*args, **kwargs)
