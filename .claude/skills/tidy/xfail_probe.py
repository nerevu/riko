"""
Reports each xfail whose failure today is not the one its marker documents.

Usage:
    PYTHONPATH=.claude/skills/tidy uv run --active pytest -p xfail_probe --no-cov \\
        [-n auto] [FILE ...]

A pytest plugin. A strict xfail is a tripwire: it should fail only until the
pending capability lands, and only with the exception its ``raises=`` names. A
setup error (a fixture that is a plain generator, a missing name) satisfies the
marker too, so the tripwire never trips. The plugin records the exception each
xfail test actually raised and prints one line per suspect after the run:

- ``SETUP`` -- the test errored before its body ran.
- ``MISMATCH`` -- the body raised something other than ``raises=``.
- ``UNPINNED`` -- no ``raises=``, so any exception satisfies the marker.
- ``PASSES`` -- the body raised nothing; the capability may have landed.

Each line reads ``VERDICT nodeid strict=S raises=R actual=A: first message line``,
followed by a count per verdict (``ok`` included). Records travel on the report's
``user_properties``, so the summary is complete under ``-n auto``. It works with or
without ``--runxfail``.
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Generator

    from _pytest.terminal import TerminalReporter

PROPERTY = "xfail_probe"
SUSPECTS = ("SETUP", "MISMATCH", "UNPINNED", "PASSES")
MAX_MESSAGE = 120


def get_names(raises: object) -> str:
    kinds = raises if isinstance(raises, tuple) else (raises,)
    return ",".join(getattr(kind, "__name__", str(kind)) for kind in kinds)


def get_verdict(when: str, raises: object, error: BaseException | None) -> str:
    if when == "setup":
        verdict = "SETUP"
    elif error is None:
        verdict = "PASSES"
    elif raises is None:
        verdict = "UNPINNED"
    elif isinstance(raises, type | tuple) and isinstance(error, raises):
        verdict = "ok"
    else:
        verdict = "MISMATCH"

    return verdict


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    report = yield
    mark = item.get_closest_marker("xfail")
    error = None if call.excinfo is None else call.excinfo.value
    errored = call.when == "setup" and error is not None

    if mark is not None and (call.when == "call" or errored):
        raises = mark.kwargs.get("raises")
        lines = str(error).splitlines() if error is not None else []
        record = {
            "verdict": get_verdict(call.when, raises, error),
            "nodeid": item.nodeid,
            "strict": str(
                mark.kwargs.get("strict", item.config.getini("xfail_strict"))
            ),
            "raises": "-" if raises is None else get_names(raises),
            "actual": "-" if error is None else type(error).__name__,
            "message": lines[0][:MAX_MESSAGE] if lines else "",
        }
        report.user_properties.append((PROPERTY, record))

    return report


class Summary:
    """Collects one session's records and prints them after the run."""

    def __init__(self) -> None:
        self.records: list[dict[str, str]] = []

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        self.records.extend(
            {str(key): str(field) for key, field in value.items()}
            for name, value in report.user_properties
            if name == PROPERTY and isinstance(value, dict)
        )

    def pytest_terminal_summary(self, terminalreporter: TerminalReporter) -> None:
        records = sorted(self.records, key=lambda r: (r["verdict"], r["nodeid"]))
        counts = Counter(record["verdict"] for record in records)
        terminalreporter.section("xfail probe")

        for record in records:
            if record["verdict"] in SUSPECTS:
                terminalreporter.write_line(
                    "{verdict} {nodeid} strict={strict} raises={raises} "
                    "actual={actual}: {message}".format(**record)
                )

        terminalreporter.write_line(
            " ".join(f"{verdict}={counts[verdict]}" for verdict in (*SUSPECTS, "ok"))
        )


def pytest_configure(config: pytest.Config) -> None:
    config.pluginmanager.register(Summary(), f"{PROPERTY}-summary")
