# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.bado.mock
~~~~~~~~~~~~~~
Provides classes for mocking a reactor during tests

Examples:
    basic usage::

        >>> from riko import get_path
        >>> from riko.bado.mock import FakeReactor
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

import itertools as it
import pygogo as gogo

from builtins import *
from . import reactor

try:
    from twisted.internet.interfaces import IReactorCore
except ImportError:
    implementer = lambda _: lambda _: lambda: None
    IReactorCore, MemoryReactor = object, object
    FakeReactor = lambda _: lambda: None
else:
    from zope.interface import implementer
    from twisted.test.proto_helpers import MemoryReactor

logger = gogo.Gogo(__name__, monolog=True).logger


class FakeDelayedCall(object):
    """Fake delayed call which lets us simulate the scheduler.
    """
    def __init__(self, func):
        """A function to run later.
        """
        self.func = func
        self.cancelled = False

    def cancel(self):
        """Don't run my function later.
        """
        self.cancelled = True


@implementer(IReactorCore)
class FakeReactor(MemoryReactor):
    """A fake reactor to be used in tests. This reactor doesn't actually do
    much that's useful yet. It accepts TCP connection setup attempts, but
    they will never succeed.

    Examples:
        >>> import sys
        >>> from twisted.internet.abstract import FileDescriptor
        >>> from twisted.internet.fdesc import readFromFD, setNonBlocking
        >>>
        >>> # reactor = proto_helpers.FakeReactor()
        >>> reactor = FakeReactor()
        >>> f = FileDescriptor(reactor)
        >>> f.fileno = sys.__stdout__.fileno
        >>> fd = f.fileno()
        >>> setNonBlocking(fd)
        >>> readFromFD(fd, print)
    """
    def __init__(self):
        super(FakeReactor, self).__init__()
        reactor.fake = True
        msg = 'Attention! Running fake reactor'
        logger.debug('%s. Some deffereds may not work as intended.' % msg)
        self.work = []
        self.running = False

    def resolve(self, *args, **kwargs):
        """Return a L{twisted.internet.defer.Deferred} that will resolve a hostname.
        """
        pass

    def run(self):
        """Fake L{IReactorCore.run}.
        """
        self.running = True

    def stop(self):
        """Fake L{IReactorCore.stop}.
        """
        self.running = False

    def crash(self):
        """Fake L{IReactorCore.crash}.
        """
        self.running = False

    def iterate(self, *args, **kwargs):
        """Fake L{IReactorCore.iterate}.
        """
        pass

    def fireSystemEvent(self, *args, **kwargs):
        """Fake L{IReactorCore.fireSystemEvent}.
        """
        pass

    def addSystemEventTrigger(self, *args, **kwargs):
        """Fake L{IReactorCore.addSystemEventTrigger}.
        """
        pass

    def removeSystemEventTrigger(self, *args, **kwargs):
        """Fake L{IReactorCore.removeSystemEventTrigger}.
        """
        pass

    def callWhenRunning(self, *args, **kwargs):
        """Fake L{IReactorCore.callWhenRunning}.
        """
        pass

    def getDelayedCalls(self):
        """Return all the outstanding delayed calls in the system.
        """
        return (x for x in self.work if not x.cancelled)

    def callLater(self, func):
        """Schedule a unit of work to be done later.
        """
        unit = FakeDelayedCall(func)
        self.work = it.chain(self.work, [unit])
        self.pump()
        return unit

    def pump(self):
        """Perform scheduled work
        """
        for unit in self.getDelayedCalls():
            try:
                unit.func()
            except Exception as e:
                logger.error(e)

        return
