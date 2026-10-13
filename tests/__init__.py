# vim: sw=4:ts=4:expandtab
"""
Provides the riko test suite and its shared helpers.

Placing a test takes two lookups.

1. Tier, first match wins: ``functional`` when the test runs a CLI command, an
   ``examples`` pipeline, or a stored fixture workflow end to end; ``public`` when
   it uses only supported names; ``internal`` otherwise.
2. File: find the subject (the riko name whose behavior the test asserts) in that
   tier's index, the ``__init__.py`` docstring of its folder. Each subject has
   exactly one file. When the subject is missing, add it to the closest row.

Inside a file, every test belongs to a ``Test<Subject>`` class (its async twin,
``TestAsync<Subject>``, follows it). Helpers sit directly above the one class that
uses them, at the top of the file when several classes do, or in a ``tests/_*.py``
module when several files do. Within a class, behavior tests come first, then
rejection tables, then strict-xfail tripwires. A regression test goes in its
subject's class; a tripwire goes where the real test will live once it flips.

Files start coarse. Split one past about 2000 lines by moving its largest subject
row into ``test_<file>_<row>.py``; merge one under about 300 lines back into its
neighbor.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from riko.bado._backend import issync, run

if TYPE_CHECKING:
    from collections.abc import AsyncIterable

TESTS_DIR = Path(__file__).parent.absolute()

skipif_issync = pytest.mark.skipif(issync, reason="async support not available")


def async_test(f):
    """Shortcut to apply multiple pytest markers at once."""
    f = pytest.mark.anyio(f)
    f = skipif_issync(f)
    return f


def aresolve[T](aiterable: AsyncIterable[T]) -> list[T]:
    """Drain *aiterable* to a list via ``riko.bado.run`` (one event loop)."""

    async def _collect() -> list[T]:
        return [item async for item in aiterable]

    return run(_collect)
