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
    real_task = None

    class Reactor:
        fake = False

    reactor = Reactor()

else:
    from twisted.internet import defer, reactor, testing
    from twisted.internet import task as real_task
    from twisted.internet.defer import Deferred
    from twisted.internet.defer import gatherResults as gather_results  # noqa: N813
    from twisted.internet.defer import maybeDeferred as maybe_deferred  # noqa: N813
    from twisted.internet.task import react
    from twisted.internet.testing import MemoryReactorClock
    from twisted.internet.utils import (
        getProcessOutput as get_process_output,  # noqa: N813
    )
    from twisted.protocols.basic import FileSender
    from twisted.python import failure

    async_none = defer.succeed(None)
    async_return = partial(defer.succeed)
    async_partial = lambda f, **kwargs: partial(maybe_deferred, f, **kwargs)
    backend = "twisted"
    reactor.fake = False

_issync = backend == "empty"
_isasync = not _issync

__all__ = [
    "Deferred",
    "FileSender",
    "MemoryReactorClock",
    "async_get",
    "async_json",
    "backend",
    "defer",
    "failure",
    "gather_results",
    "get_process_output",
    "maybe_deferred",
    "react",
    "reactor",
    "real_task",
    "testing",
]
