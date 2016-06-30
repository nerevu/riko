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
from html.entities import entitydefs, name2codepoint

from builtins import *

from riko.lib.utils import _make_content

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

    asyncNone = defer.succeed(None)
    asyncReturn = partial(defer.succeed)
    asyncPartial = lambda f, **kwargs: partial(maybeDeferred, f, **kwargs)

DEF2NAME = {v: k for k, v in entitydefs.items()}


def asyncSleep(seconds):
    d = Deferred()
    callLater(seconds, d.callback, None)
    return d


def deferToProcess(source, function, *args, **kwargs):
    command = "from %s import %s\n%s(*%s, **%s)" % (
        source, function, function, args, kwargs)

    return getProcessOutput(executable, ['-c', command], environ)


def def2unicode(entitydef):
    """Convert an HTML entity reference into unicode.
    Double check if I need this since it seems to convert the input back into
    itself!
    """
    try:
        name = DEF2NAME[entitydef]
    except KeyError:
        cp = int(entitydef.lstrip('&#').rstrip(';'))
    else:
        cp = name2codepoint[name]

    return chr(cp)


def xml2etree(f, html=False):
    if hasattr(f, 'read'):
        parse = microdom.parse if html else microdom.parseXML
    else:
        parse = microdom.parseString

    return parse(f)


def etreeToDict(element, tag='content'):
    """Convert a microdom element tree into a dict imitating how Yahoo Pipes
    does it.

    TODO: checkout twisted.words.xish
    """
    i = dict(element.attributes) if hasattr(element, 'attributes') else {}
    value = element.nodeValue if hasattr(element, 'nodeValue') else None

    if isinstance(element, EntityReference):
        value = def2unicode(value)

    i.update(_make_content(i, value, tag))

    for child in element.childNodes:
        tag = child.tagName if hasattr(child, 'tagName') else 'content'
        value = etreeToDict(child, tag)

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
