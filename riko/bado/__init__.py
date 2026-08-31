# vim: sw=4:ts=4:expandtab
"""
riko.bado
~~~~~~~~~

Stable, SemVer-guaranteed async API for Riko.

The names in ``__all__`` are also re-exported from :mod:`riko`. Riko's private backend
facade lives in :mod:`riko.bado._backend`.
"""

from riko.bado._backend import backend, isasync, issync, run
from riko.bado._util import async_return
from riko.bado.io import async_read, async_url_open, async_write, get_async_temp_file
from riko.bado.itertools import as_async, async_map, async_map_stream, async_sleep

__all__ = [
    "as_async",
    "async_map",
    "async_map_stream",
    "async_read",
    "async_return",
    "async_sleep",
    "async_url_open",
    "async_write",
    "backend",
    "get_async_temp_file",
    "isasync",
    "issync",
    "run",
]
