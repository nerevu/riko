# vim: sw=4:ts=4:expandtab
"""
Pytest plugin that keeps a timeout from ever counting as an expected failure.

A ``timeout`` marker is a safety net for a genuine hang, never the way a test is
meant to end. A test whose ``xfail`` is satisfied only because pytest-timeout
interrupted it would hide that hang. And a timeout raised as a signal can land
inside coverage's tracer and deadlock the worker. So this plugin reports such a
test as failed. Bound the test's own work instead (e.g. a long finite source
plus an assertion on how much of it was pulled). How tight each bound is set is
in the ``tests/__init__.py`` docstring.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Generator


TIMEOUT_MARKER = "from pytest-timeout."


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    report = yield
    excinfo = call.excinfo
    timed_out = excinfo is not None and TIMEOUT_MARKER in str(excinfo.value)

    if timed_out and hasattr(report, "wasxfail"):
        reason = report.wasxfail
        del report.wasxfail
        report.outcome = "failed"
        report.longrepr = (
            f"{item.nodeid} hit its timeout, which cannot satisfy xfail "
            f"({reason!r}); bound the test so it ends on its own"
        )

    return report
