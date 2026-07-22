# vim: sw=4:ts=4:expandtab
"""
riko.ext.protocols
~~~~~~~~~~~~~~~~~~~
Parser/wrapper ``Protocol`` types surfaced for extension authors. Definitions
live in :mod:`riko.types.general`; this module is the stable re-export point.
"""

from riko.types.general import (
    AsyncOperatorWrapper,
    AsyncProcessorWrapper,
    AsyncSplitterWrapper,
    ModuleWrapper,
    SyncOperatorWrapper,
    SyncProcessorWrapper,
    SyncSplitterWrapper,
)

__all__ = [
    "AsyncOperatorWrapper",
    "AsyncProcessorWrapper",
    "AsyncSplitterWrapper",
    "ModuleWrapper",
    "SyncOperatorWrapper",
    "SyncProcessorWrapper",
    "SyncSplitterWrapper",
]
