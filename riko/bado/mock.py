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
import pygogo as gogo

from . import reactor

try:
    from twisted.test.proto_helpers import MemoryReactorClock
except ImportError:
    MemoryReactorClock = object
    FakeReactor = lambda _: lambda: None

logger = gogo.Gogo(__name__, monolog=True).logger


class FakeReactor(MemoryReactorClock):
    """A fake reactor to be used in tests. This reactor doesn't actually do
    much that's useful yet. It accepts TCP connection setup attempts, but
    they will never succeed.

    Examples:
        >>> import sys
        >>>
        >>> try:
        ...     from twisted import internet
        ... except ImportError:
        ...     pass
        ... else:
        ...     from twisted.internet.fdesc import readFromFD, setNonBlocking
        ...     FileDescriptor = internet.abstract.FileDescriptor
        ...
        ...     reactor = FakeReactor()
        ...     f = FileDescriptor(reactor)
        ...     f.fileno = sys.__stdout__.fileno
        ...     fd = f.fileno()
        ...     setNonBlocking(fd)
        ...     readFromFD(fd, print)
    """
    _DELAY = 1

    def __init__(self):
        super(FakeReactor, self).__init__()
        reactor.fake = True
        msg = 'Attention! Running fake reactor'
        logger.debug('%s. Some deferreds may not work as intended.' % msg)

    def callLater(self, when, what, *args, **kwargs):
        """Schedule a unit of work to be done later.
        """
        delayed = super(FakeReactor, self).callLater(
            when, what, *args, **kwargs)
        self.pump()
        return delayed

    def pump(self):
        """Perform scheduled work
        """
        self.advance(self._DELAY)
