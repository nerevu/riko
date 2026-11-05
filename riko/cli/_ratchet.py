# vim: sw=4:ts=4:expandtab

"""
Keeps a measured count from rising above a ceiling recorded in ``pyproject.toml``.

Each ceiling is one integer key in a ``[tool.riko.<table>]`` table, with a
``<key>-lowered`` date beside it. A count above its ceiling fails. A count below it
lowers the ceiling and records the date. The count can only ever ratchet down. A
ceiling that holds longer than ``[tool.riko.ratchet] stale-days`` draws a warning. Under
GitHub Actions each warning is a workflow annotation.
"""

from __future__ import annotations

import re
import tomllib
from datetime import date, datetime
from os import environ
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def _build_value_line(key: str) -> re.Pattern[str]:
    """Builds the pattern that matches ``key``'s value line."""
    value = "[^ \\t#\\n]+"
    return re.compile(rf"(?m)^({re.escape(key)}[ \t]*=[ \t]*){value}([ \t]*(?:#.*)?)$")


def _get_value(text: str, table: str, key: str) -> object:
    """Gets a raw ``[tool.riko.<table>]`` value, or ``None`` when it is missing."""
    tables = tomllib.loads(text).get("tool", {}).get("riko", {})
    return tables.get(table, {}).get(key)


def get_ceiling(text: str, table: str, key: str) -> int | None:
    """
    Gets a recorded ceiling from ``pyproject.toml`` text.

    Args:

        text: The contents of ``pyproject.toml``.
        table: The ``[tool.riko.<table>]`` table holding the ceiling.
        key: The ceiling's key in that table.

    Returns:

        The ceiling, or ``None`` when none is recorded yet.

    Examples:

        >>> get_ceiling("[tool.riko.typing]\\nany = 9\\n", "typing", "any")
        9

    """
    ceiling = _get_value(text, table, key)
    return ceiling if isinstance(ceiling, int) else None


def get_lowered(text: str, table: str, key: str) -> date | None:
    """
    Gets the date a ceiling was last lowered from ``pyproject.toml`` text.

    Args:

        text: The contents of ``pyproject.toml``.
        table: The ``[tool.riko.<table>]`` table holding the ceiling.
        key: The ceiling's key in that table.

    Returns:

        The ``<key>-lowered`` date, or ``None`` when none is recorded yet.

    Examples:

        >>> text = "[tool.riko.typing]\\nany = 9\\nany-lowered = 2026-10-27\\n"
        >>> get_lowered(text, "typing", "any")
        datetime.date(2026, 10, 27)

    """
    lowered = _get_value(text, table, f"{key}-lowered")

    if isinstance(lowered, date) and not isinstance(lowered, datetime):
        day = lowered
    else:
        day = None

    return day


def get_stale_days(text: str) -> int | None:
    """
    Gets how many days a ceiling may hold before it draws a warning.

    Args:

        text: The contents of ``pyproject.toml``.

    Returns:

        ``[tool.riko.ratchet] stale-days``, or ``None`` when no window is set.

    Examples:

        >>> get_stale_days("[tool.riko.ratchet]\\nstale-days = 7\\n")
        7

    """
    days = _get_value(text, "ratchet", "stale-days")
    return days if isinstance(days, int) else None


def build_ceiling_text(
    text: str, table: str, key: str, value: int | date, *, after: str | None = None
) -> str:
    """
    Builds ``pyproject.toml`` text recording a ceiling or its date.

    Args:

        text: The contents of ``pyproject.toml``.
        table: The ``[tool.riko.<table>]`` table holding the value.
        key: The value's key in that table.
        value: The ceiling or date to record.
        after: The key whose line a missing key goes under (default: the table header).

    Returns:

        The text with the value set, adding the table or key when it is missing.

    Examples:

        >>> build_ceiling_text("[tool.riko.typing]\\nany = 9\\n", "typing", "any", 8)
        '[tool.riko.typing]\\nany = 8\\n'
        >>> text = "[tool.riko.typing]\\nlimit = 3\\nany = 9\\n"
        >>> build_ceiling_text(text, "typing", "cast", 2, after="any")
        '[tool.riko.typing]\\nlimit = 3\\nany = 9\\ncast = 2\\n'

    """
    header = f"[tool.riko.{table}]"
    start = text.find(header)
    head, tail = text[:start], text[start:]

    if after is None or _get_value(text, table, after) is None:
        anchor = None
    else:
        anchor = _build_value_line(after)

    if start < 0:
        result = f"{text.rstrip()}\n\n{header}\n{key} = {value}\n"
    elif _get_value(text, table, key) is not None:
        line = _build_value_line(key)
        result = head + line.sub(rf"\g<1>{value}\g<2>", tail, count=1)
    elif anchor is not None:
        result = head + anchor.sub(rf"\g<0>\n{key} = {value}", tail, count=1)
    else:
        result = text.replace(header, f"{header}\n{key} = {value}", 1)

    return result


def _report(message: str, *, warn: bool, ci: bool) -> None:
    """Prints a ratchet report, as a workflow annotation for a warning on CI."""
    if not warn:
        print(message)
    elif ci:
        print(f"::warning::{message}")
    else:
        print(f"Warning: {message}")


def ratchet_ceiling(
    pyproject: Path,
    table: str,
    key: str,
    count: int,
    noun: str,
    *,
    today: date | None = None,
) -> int:
    """
    Checks ``count`` against its recorded ceiling, lowering the ceiling on a gain.

    The first measurement records the ceiling. Recording or lowering a ceiling also
    records the day, which starts its staleness clock.

    Args:

        pyproject: The ``pyproject.toml`` file holding the ceiling.
        table: The ``[tool.riko.<table>]`` table holding the ceiling.
        key: The ceiling's key in that table.
        count: The measured count.
        noun: What ``count`` counts, for the printed report.
        today: The day of the measurement (default: the current date).

    Returns:

        ``1`` when ``count`` exceeds the ceiling, else ``0``.

    """
    text = pyproject.read_text(encoding="utf-8")
    recorded = get_ceiling(text, table, key)
    lowered = get_lowered(text, table, key)
    stale_days = get_stale_days(text)
    day = date.today() if today is None else today
    ceiling = count if recorded is None else recorded
    ratcheted = min(ceiling, count)
    ci = bool(environ.get("GITHUB_ACTIONS"))

    if count > ceiling:
        message = f"{count} {noun} exceed the recorded ceiling of {ceiling}."
        warn = False
    elif recorded is None or ratcheted < recorded or lowered is None:
        ratcheted_text = build_ceiling_text(text, table, key, ratcheted)
        args = (ratcheted_text, table, f"{key}-lowered", day)
        data = build_ceiling_text(*args, after=key)
        pyproject.write_text(data, encoding="utf-8")
        message = f"{count} {noun}; recorded the ceiling as {ratcheted} on {day}."

        if ci:
            message += " CI discards this change;"
            message += " run the ratchet locally and commit pyproject.toml."

        warn = ci
    elif stale_days is not None and (day - lowered).days > stale_days:
        message = (
            f"{count} {noun} have held the ceiling of {ceiling} since {lowered}, "
            f"over {stale_days} days; lower it."
        )
        warn = True
    else:
        message = f"{count} {noun} hold the ceiling of {ceiling}."
        warn = False

    _report(message, warn=warn, ci=ci)
    return 1 if count > ceiling else 0
