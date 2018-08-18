# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.bado.util
~~~~~~~~~~~~~~
Provides functions for creating asynchronous riko pipes

Examples:
    basic usage::

        >>> from riko import get_path
        >>> from riko.bado.util import xml2etree
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from os import environ
from sys import executable
from functools import partial

from builtins import *  # noqa pylint: disable=unused-import

from riko.parsers import _make_content, entity2text

try:
    from twisted.internet.defer import maybeDeferred, Deferred
except ImportError:
    maybeDeferred = lambda *args: None
else:
    from twisted.internet import defer
    from twisted.internet.utils import getProcessOutput
    from twisted.internet.reactor import callLater

    from . import microdom
    from .microdom import EntityReference

    async_none = defer.succeed(None)
    async_return = partial(defer.succeed)
    async_partial = lambda f, **kwargs: partial(maybeDeferred, f, **kwargs)


def async_sleep(seconds):
    d = Deferred()
    callLater(seconds, d.callback, None)
    return d


def defer_to_process(command):
    return getProcessOutput(executable, ['-c', command], environ)


def xml2etree(f, xml=True):
    readable = hasattr(f, 'read')

    if xml and readable:
        parse = microdom.parseXML
    elif readable:
        parse = partial(microdom.parse, lenient=True)
    elif xml:
        parse = microdom.parseXMLString
    else:
        parse = partial(microdom.parseString, lenient=True)

    return parse(f)


def etree2dict(element, tag='content'):
    """Convert a microdom element tree into a dict imitating how Yahoo Pipes
    does it.

    TODO: checkout twisted.words.xish
    """
    i = dict(element.attributes) if hasattr(element, 'attributes') else {}
    value = element.nodeValue if hasattr(element, 'nodeValue') else None

    if isinstance(element, EntityReference):
        value = entity2text(value)

    i.update(_make_content(i, value, tag))

    for child in element.childNodes:
        tag = child.tagName if hasattr(child, 'tagName') else 'content'
        value = etree2dict(child, tag)

        # try to join the content first since microdom likes to split up
        # elements that contain a mix of text and entity reference
        try:
            i.update(_make_content(i, value, tag, append=False))
        except TypeError:
            i.update(_make_content(i, value, tag))

    if ('content' in i) and not set(i).difference(['content']):
        # element is leaf node and doesn't have attributes
        i = i['content']

    return i
