# vim: sw=4:ts=4:expandtab
"""
Stable async-runtime API for Riko.

Names in ``__all__`` are also available from the top-level ``riko`` namespace.
"""

from ._backend import async_sleep, backend, isasync, issync, run
from ._util import async_read, async_return
from .itertools import as_async, async_map, async_map_stream

__all__ = [
    "as_async",
    "async_map",
    "async_map_stream",
    "async_read",
    "async_return",
    "async_sleep",
    "backend",
    "isasync",
    "issync",
    "run",
]
