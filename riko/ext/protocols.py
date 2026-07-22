# vim: sw=4:ts=4:expandtab
"""
riko.ext.protocols
~~~~~~~~~~~~~~~~~~~
Parser/wrapper ``Protocol`` types and stream vocabulary surfaced for extension
authors. Definitions live in :mod:`riko.types.general`; this module is the stable
re-export point. ``Stream``/``AsyncStream`` (sync/async iterators of ``Item``) and
``Feed`` (an ``AsyncIterable[Item]`` incremental source) are the I/O contracts an
async source adapter targets.
"""

from riko.types.general import (
    AsyncItems,
    AsyncOperatorWrapper,
    AsyncProcessorWrapper,
    AsyncSplitterWrapper,
    AsyncStream,
    Feed,
    ModuleWrapper,
    Stream,
    SyncOperatorWrapper,
    SyncProcessorWrapper,
    SyncSplitterWrapper,
)

__all__ = [
    "AsyncItems",
    "AsyncOperatorWrapper",
    "AsyncProcessorWrapper",
    "AsyncSplitterWrapper",
    "AsyncStream",
    "Feed",
    "ModuleWrapper",
    "Stream",
    "SyncOperatorWrapper",
    "SyncProcessorWrapper",
    "SyncSplitterWrapper",
]
