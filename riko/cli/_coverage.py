# vim: sw=4:ts=4:expandtab

"""
Measures the full suite's uncovered lines for its recorded ceiling.

The ceiling lives in ``pyproject.toml`` under ``[tool.riko.coverage]`` as the number
of statements a full-suite run leaves unexecuted. Losing coverage of existing code
and adding untested code both raise the count; deleting code never does.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def load_uncovered_lines(report: Path) -> int:
    """
    Loads the count of unexecuted statements from a ``coverage json`` report.

    Args:

        report: The JSON report a coverage run wrote.

    Returns:

        The report's total of missing (unexecuted) statements.

    """
    data = json.loads(report.read_text(encoding="utf-8"))
    return int(data["totals"]["missing_lines"])
