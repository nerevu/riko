# vim: sw=4:ts=4:expandtab
"""Provides shared write targets for write-session and target tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from riko.definitions._write import WriteCapabilities, WriteMode
from riko.types._enums import Backends


@dataclass(frozen=True)
class RecordStore:
    """A native keyed target exercising the match-keyed/idempotent branches."""

    backend: ClassVar[Backends] = Backends.AIRTABLE

    def get_capabilities(self, fmt=None) -> WriteCapabilities:
        return WriteCapabilities(
            modes=frozenset(WriteMode),
            match_keyed_modes=frozenset({WriteMode.MERGE, WriteMode.DELETE}),
            idempotent_modes=frozenset({WriteMode.APPEND}),
        )
