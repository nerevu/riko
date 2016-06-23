# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.bado
~~~~~~~~~
Provides functions for creating asynchronous riko pipes

Examples:
    basic usage::

        >>> from riko import get_path
        >>> from riko.bado import react
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from builtins import *

try:
    from twisted.internet.task import react
except ImportError:
    react = lambda _, _reactor=None: None
    inlineCallbacks = lambda _: lambda: None
    returnValue = lambda _: lambda: None
    backend = 'empty'
else:
    from twisted.internet.defer import inlineCallbacks
    from twisted.internet.defer import returnValue
    backend = 'twisted'


class Reactor(object):
    fake = False

reactor = Reactor()
coroutine = inlineCallbacks
return_value = returnValue
_issync = backend == 'empty'
_isasync = not _issync
