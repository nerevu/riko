# vim: sw=4:ts=4:expandtab
"""Exposes parser, wrapper, and stream protocols to extension authors."""

from riko.types._streams import (
    AsyncRecords,
    AsyncRecordStream,
    RecordFeed,
    RecordStream,
)
from riko.types._wrappers import (
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
    "AsyncRecordStream",
    "AsyncRecords",
    "AsyncSplitterWrapper",
    "ModuleWrapper",
    "RecordFeed",
    "RecordStream",
    "SyncOperatorWrapper",
    "SyncProcessorWrapper",
    "SyncSplitterWrapper",
]
