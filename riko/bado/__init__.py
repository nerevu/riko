# vim: sw=4:ts=4:expandtab
"""
Provides functions for creating asynchronous riko pipes

Examples:
    basic usage::

        >>> from riko import get_path
        >>> from riko.bado import react

"""

from functools import partial

try:
    from treq import get as async_get
    from treq import json_content as async_json
    from twisted.internet import defer
except ImportError:
    async_get = lambda _: lambda: None
    async_json = lambda _: lambda: None
    async_none = lambda _: lambda: None
    async_return = lambda _: lambda: None
    backend = "empty"
    defer = None
    Deferred = None
    failure = None
    FileSender = None
    gather_results = None
    get_process_output = None
    maybe_deferred = lambda *_: None
    MemoryReactorClock = object
    react = lambda _, _reactor=None: None
    reactor = None
    testing = None
    real_task = None
    implementer = None
    IReactorCore = None

    class Reactor:
        fake = False

    reactor = Reactor()

else:
    from twisted.internet import defer, reactor, testing
    from twisted.internet import task as real_task
    from twisted.internet.defer import Deferred
    from twisted.internet.defer import gatherResults as gather_results  # noqa: N813
    from twisted.internet.defer import maybeDeferred as maybe_deferred  # noqa: N813
    from twisted.internet.interfaces import IReactorCore
    from twisted.internet.task import react
    from twisted.internet.testing import MemoryReactorClock
    from twisted.internet.utils import (
        getProcessOutput as get_process_output,  # noqa: N813
    )
    from twisted.protocols.basic import FileSender
    from twisted.python import failure
    from zope.interface import implementer

    async_none = defer.succeed(None)
    async_return = partial(defer.succeed)
    backend = "twisted"
    reactor.fake = False

async_partial = lambda f, **kwargs: partial(maybe_deferred, f, **kwargs)
_issync = backend == "empty"
_isasync = not _issync

__all__ = [
    "Deferred",
    "FileSender",
    "IReactorCore",
    "MemoryReactorClock",
    "async_get",
    "async_json",
    "async_none",
    "async_partial",
    "async_return",
    "backend",
    "defer",
    "failure",
    "gather_results",
    "get_process_output",
    "implementer",
    "maybe_deferred",
    "react",
    "reactor",
    "real_task",
    "testing",
]
