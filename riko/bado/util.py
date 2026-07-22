# vim: sw=4:ts=4:expandtab
"""
riko.bado.util
~~~~~~~~~~~~~~
Provides functions for creating asynchronous riko pipes

Examples:
    basic usage::

        >>> from riko import get_path

"""

from __future__ import annotations

from os import environ
from sys import executable

from riko import bado
from riko.bado import defer, get_process_output


async def async_sleep(seconds: float):
    d = defer.Deferred()
    # IDelayedCall stub missing delay param
    bado.reactor.callLater(seconds, d.callback, None)  # type: ignore[arg-type]
    await d


def defer_to_process(command) -> defer.Deferred:
    return get_process_output(executable, ["-c", command], environ)
