# vim: sw=4:ts=4:expandtab
"""
riko.bado.util
~~~~~~~~~~~~~~
Provides functions for creating asynchronous riko pipes

Examples:
    basic usage::

        >>> from riko import get_path

"""

from functools import partial
from os import environ
from sys import executable

try:
    from twisted.internet.defer import Deferred
    from twisted.internet.defer import maybeDeferred as maybe_deferred  # noqa: N813
except ImportError:
    maybe_deferred = lambda *_: None
    get_process_output = None
    Deferred = None
    reactor = None
else:
    from twisted.internet import defer, reactor
    from twisted.internet.utils import (
        getProcessOutput as get_process_output,  # noqa: N813
    )

    async_none = defer.succeed(None)
    async_return = partial(defer.succeed)
    async_partial = lambda f, **kwargs: partial(maybe_deferred, f, **kwargs)


async def async_sleep(seconds: float):
    d = Deferred()
    # IDelayedCall stub missing delay param
    reactor.callLater(seconds, d.callback, None)  # type: ignore[arg-type]
    await d


def defer_to_process(command) -> defer.Deferred:
    return get_process_output(executable, ["-c", command], environ)
