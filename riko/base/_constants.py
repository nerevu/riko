"""Shared runtime defaults and encoding constants."""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING

from ._config import settings

if TYPE_CHECKING:
    from collections.abc import Mapping

DEF_CONCURRENCY_LIMIT = settings.concurrency_limit
STREAMING_THRESHOLD = settings.streaming_threshold
ENCODING = settings.encoding
FOREVER_ITEM: Mapping[str, bool] = MappingProxyType({"forever": True})
