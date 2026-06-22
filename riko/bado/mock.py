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

from collections.abc import Iterable
from typing import override

import pygogo as gogo

from riko import bado
from riko.bado import MemoryReactorClock

logger = gogo.Gogo(__name__, monolog=True).logger


class FakeReactor(MemoryReactorClock):
    """
    A fake reactor to be used in tests. This reactor doesn't actually do
    much that's useful yet. It accepts TCP connection setup attempts, but
    they will never succeed.

    Examples:
        >>> try:
        ...     from twisted import internet
        ... except ImportError:
        ...     pass
        ... else:
        ...     import os
        ...     from twisted.internet.fdesc import readFromFD, setNonBlocking
        ...
        ...     FileDescriptor = internet.abstract.FileDescriptor
        ...
        ...     reactor = FakeReactor()
        ...     f = FileDescriptor(reactor)
        ...     r_fd, w_fd = os.pipe()
        ...     os.write(w_fd, b'riko')
        ...     os.close(w_fd)
        ...     f.fileno = lambda: r_fd
        ...     fd = f.fileno()
        ...     setNonBlocking(fd)
        ...     readFromFD(fd, print)
        ...     os.close(r_fd)
        4
        b'riko'

    """

    _DELAY = 1
    fake = True

    def __init__(self):
        super().__init__()
        bado.reactor = self

    @override
    def callLater(self, when, what, *args, **kwargs):
        """Schedule a unit of work to be done later."""
        delayed = super().callLater(when, what, *args, **kwargs)
        if when <= self._DELAY:
            self.pump()

        return delayed

    def pump(self, timings: Iterable[float] | None = None):
        """Perform scheduled work"""
        self.advance(self._DELAY)
