# vim: sw=4:ts=4:expandtab

"""
Keeps the full suite's uncovered lines from rising above a recorded ceiling.

The ceiling lives in ``pyproject.toml`` under ``[tool.riko.coverage]`` as the number
of statements a full-suite run leaves unexecuted. A run fails when it leaves more
uncovered, and lowers the ceiling when it leaves fewer, so uncovered code only ever
ratchets down. Losing coverage of existing code and adding untested code both raise
the count; deleting code never does.
"""

from __future__ import annotations

import json
import re
import tomllib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

_TABLE = "[tool.riko.coverage]"
_CEILING_LINE = re.compile(r"(?m)^(uncovered[ \t]*=[ \t]*)[0-9]+[ \t]*$")


def get_uncovered_ceiling(pyproject_text: str) -> int | None:
    """
    Gets the recorded uncovered-line ceiling from ``pyproject.toml`` text.

    Args:

        pyproject_text: The contents of ``pyproject.toml``.

    Returns:

        The ceiling, or ``None`` when none is recorded yet.

    """
    table = tomllib.loads(pyproject_text).get("tool", {}).get("riko", {})
    ceiling = table.get("coverage", {}).get("uncovered")
    return None if ceiling is None else int(ceiling)


def get_ratcheted_ceiling(ceiling: int, uncovered: int) -> int:
    """
    Gets the ceiling after a run: lowered to ``uncovered`` when that is lower.

    Args:

        ceiling: The recorded ceiling.
        uncovered: The run's count of unexecuted statements.

    Returns:

        The smaller of ``ceiling`` and ``uncovered``.

    Examples:

        >>> get_ratcheted_ceiling(1249, 1240)
        1240
        >>> get_ratcheted_ceiling(1249, 1260)
        1249

    """
    return min(ceiling, uncovered)


def build_ceiling_text(pyproject_text: str, ceiling: int) -> str:
    """
    Builds ``pyproject.toml`` text recording ``ceiling``.

    Args:

        pyproject_text: The contents of ``pyproject.toml``.
        ceiling: The uncovered-line ceiling to record.

    Returns:

        The text with the ``[tool.riko.coverage]`` ceiling set, adding the table
        when it is missing.

    Raises:

        ValueError: If the table exists without an ``uncovered`` line.

    Examples:

        >>> build_ceiling_text("[tool.riko.coverage]\\nuncovered = 1249\\n", 1240)
        '[tool.riko.coverage]\\nuncovered = 1240\\n'

    """
    if _TABLE not in pyproject_text:
        text = f"{pyproject_text.rstrip()}\n\n{_TABLE}\nuncovered = {ceiling}\n"
    elif _CEILING_LINE.search(pyproject_text):
        text = _CEILING_LINE.sub(rf"\g<1>{ceiling}", pyproject_text, count=1)
    else:
        raise ValueError(f"{_TABLE} has no uncovered line")

    return text


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
