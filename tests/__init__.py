# vim: sw=4:ts=4:expandtab
"""
Provides the riko test suite and its shared helpers.

Placing a test takes two lookups.

1. Tier, first match wins: ``functional`` when the test runs a CLI command, an
   ``examples`` pipeline, or a stored fixture workflow end to end; ``public`` when
   it uses only supported names (the stable, extension, and typing surfaces);
   ``internal`` otherwise. A code-generator check that sweeps every fixture stays
   with the generator in ``internal``.
2. File: find the subject (the riko name whose behavior the test asserts) in that
   tier's index, the ``__init__.py`` docstring of its folder. Each subject has
   exactly one file. When the subject is missing, add its ``Test<Subject>`` class
   to the closest file. Each tier's ``__init__.py`` is generated whole from those
   classes, so run ``manage codegen --tests`` and never edit it by hand.

Before adding a test, search every tier and the doctests for the behavior it
asserts (the setting, error, or outcome, not just the subject's name); the tidy
overlap scanner finds a test's current home. Add a test only for a behavior no
existing test asserts; a behavior already asserted at another level (say, end to
end through ``Pipeline``) needs no lower-level twin unless that twin checks
something the other cannot reach.

Inside a file, every test belongs to a ``Test<Subject>`` class (its async twin,
``TestAsync<Subject>``, follows it). Helpers sit directly above the one class that
uses them, at the top of the file when several classes do, or in a ``tests/_*.py``
module when several files do. Module-level constants are the exception: every
one except a ``pytest.param`` table sits at the top of the file, private names
first, with any helper a constant needs above them. Code repeated inline three
or more times becomes one such helper. Within a class, behavior tests come first,
then rejection tables, then strict-xfail tripwires. A regression test goes in its
subject's class; a tripwire goes where the real test will live once it flips.

Tests that share setup and assertion and differ only in data are one
parametrized test, and a new case of an existing shape is a row, not a method.
Keep the table as a module-level constant above its class, one
``pytest.param(..., id="kebab-id")`` per row, each on one line where it fits:
name long or repeated values once and drop the trailing comma from a row that
fits. An ``ids=[...]`` list is fine only when the values and the ids fit
together on one line, e.g. ``parametrize("v", [a, b], ids=["one", "two"])``. A
test whose name states a distinct rule stays its own test, as do sync and async
twins. Folding tests should leave the file shorter; if it grows, compact the
rows.

Every bound a test sets (``mark.timeout``, ``fail_after``, a ``wait``/``join``/
``result`` timeout, and the ``timeout``/``faulthandler_timeout`` globals in
``pyproject.toml``) is the smallest feasible value, never a round guess: measure
the worst ``call`` time over three ``pytest -n auto --durations=0`` runs and take
the smallest of 1, 2, 3, 5, 8, 10, 15, 20, 30 seconds that is at least five
times it, with a floor of 1 second. An inner bound stays below its outer one. A
value that is the test's subject (``shutdown_timeout=0.05``) is not a bound. A
``timeout`` marker is a backstop for a true hang (``tests/_timeouts.py``): a test
guarding "this stops promptly" blocks for longer than its elapsed-time assertion
but shorter than the backstop, so a regression fails the assertion instead.

Files start coarse. Before splitting one past about 2000 lines, move out what
belongs elsewhere and trim its overlaps; if it is still over, move its largest
subject row, with the rows that share its concept, into a file named for that
concept (``test_write.py`` came out of ``test_pipeline.py``). Merge one under
about 300 lines back into its neighbor. A split or merge ends with an overlap
check across the files it touched and their tier: each moved test asserts the
subject its new row names, no test repeats another's input and outcome (in either
file, the other tiers, or a doctest), no class left behind belongs with the moved
row, and every helper sits where the helper rule above puts it now that its users
changed.
"""

from __future__ import annotations

import os
import subprocess
import sys
from importlib.util import find_spec
from typing import TYPE_CHECKING, Any

import pytest

from riko.bado._backend import issync, run
from riko.base._paths import ROOT_DIR
from riko.base._paths import TESTS_DIR as TESTS_DIR

if TYPE_CHECKING:
    from collections.abc import AsyncIterable


SCRIPT_TIMEOUT = 5


skipif_issync = pytest.mark.skipif(issync, reason="async support not available")


def async_test(f):
    """Shortcut to apply multiple pytest markers at once."""
    f = pytest.mark.anyio(f)
    f = skipif_issync(f)
    return f


def is_installed(module: str) -> bool:
    """Check whether *module* is importable in this environment."""
    return find_spec(module) is not None


def aresolve[T](aiterable: AsyncIterable[T]) -> list[T]:
    """Drain *aiterable* to a list via ``riko.bado.run`` (one event loop)."""

    async def _collect() -> list[T]:
        return [item async for item in aiterable]

    return run(_collect)


def run_python(
    *args: str, hash_seed: str | None = None, check: bool = True, **kwargs: Any
) -> subprocess.CompletedProcess[str]:
    """
    Runs ``python *args`` from the checkout root and returns the finished process.

    The run captures text output, raises on a nonzero exit unless ``check`` is
    false, and is killed after ``SCRIPT_TIMEOUT`` seconds; ``kwargs`` override
    the other ``subprocess.run`` options.
    ``hash_seed`` sets ``PYTHONHASHSEED`` for the child.
    """
    seed = {} if hash_seed is None else {"PYTHONHASHSEED": hash_seed}
    options = {
        "capture_output": True,
        "cwd": ROOT_DIR,
        "env": os.environ | seed,
        "text": True,
        "timeout": SCRIPT_TIMEOUT,
    }
    return subprocess.run([sys.executable, *args], check=check, **options | kwargs)
