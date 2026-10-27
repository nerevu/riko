# vim: sw=4:ts=4:expandtab

"""
Keeps a measured count from rising above a ceiling recorded in ``pyproject.toml``.

Each ceiling is one integer key in a ``[tool.riko.<table>]`` table. A count above
its ceiling fails; a count below it lowers the ceiling, so the count only ever
ratchets down.
"""

from __future__ import annotations

import re
import tomllib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def _build_ceiling_line(key: str) -> re.Pattern[str]:
    """Builds the pattern that matches ``key``'s ceiling line."""
    return re.compile(rf"(?m)^({re.escape(key)}[ \t]*=[ \t]*)[0-9]+([ \t]*(?:#.*)?)$")


def get_ceiling(pyproject_text: str, table: str, key: str) -> int | None:
    """
    Gets a recorded ceiling from ``pyproject.toml`` text.

    Args:

        pyproject_text: The contents of ``pyproject.toml``.
        table: The ``[tool.riko.<table>]`` table holding the ceiling.
        key: The ceiling's key in that table.

    Returns:

        The ceiling, or ``None`` when none is recorded yet.

    Examples:

        >>> get_ceiling("[tool.riko.typing]\\nany = 9\\n", "typing", "any")
        9

    """
    tables = tomllib.loads(pyproject_text).get("tool", {}).get("riko", {})
    ceiling = tables.get(table, {}).get(key)
    return None if ceiling is None else int(ceiling)


def build_ceiling_text(pyproject_text: str, table: str, key: str, ceiling: int) -> str:
    """
    Builds ``pyproject.toml`` text recording ``ceiling``.

    Args:

        pyproject_text: The contents of ``pyproject.toml``.
        table: The ``[tool.riko.<table>]`` table holding the ceiling.
        key: The ceiling's key in that table.
        ceiling: The ceiling to record.

    Returns:

        The text with the ceiling set, adding the table or key when it is missing.

    Examples:

        >>> build_ceiling_text("[tool.riko.typing]\\nany = 9\\n", "typing", "any", 8)
        '[tool.riko.typing]\\nany = 8\\n'

    """
    header = f"[tool.riko.{table}]"
    line = _build_ceiling_line(key)

    if header not in pyproject_text:
        text = f"{pyproject_text.rstrip()}\n\n{header}\n{key} = {ceiling}\n"
    elif get_ceiling(pyproject_text, table, key) is None:
        text = pyproject_text.replace(header, f"{header}\n{key} = {ceiling}", 1)
    else:
        start = pyproject_text.index(header)
        head, tail = pyproject_text[:start], pyproject_text[start:]
        text = head + line.sub(rf"\g<1>{ceiling}\g<2>", tail, count=1)

    return text


def ratchet_ceiling(
    pyproject: Path, table: str, key: str, count: int, noun: str
) -> int:
    """
    Checks ``count`` against its recorded ceiling, lowering the ceiling on a gain.

    The first measurement records the ceiling.

    Args:

        pyproject: The ``pyproject.toml`` file holding the ceiling.
        table: The ``[tool.riko.<table>]`` table holding the ceiling.
        key: The ceiling's key in that table.
        count: The measured count.
        noun: What ``count`` counts, for the printed report.

    Returns:

        ``1`` when ``count`` exceeds the ceiling, else ``0``.

    """
    text = pyproject.read_text(encoding="utf-8")
    recorded = get_ceiling(text, table, key)
    ceiling = count if recorded is None else recorded
    ratcheted = min(ceiling, count)

    if count > ceiling:
        print(f"{count} {noun} exceed the recorded ceiling of {ceiling}.")
    elif recorded is None or ratcheted < recorded:
        data = build_ceiling_text(text, table, key, ratcheted)
        pyproject.write_text(data, encoding="utf-8")
        print(f"{count} {noun}; recorded the ceiling as {ratcheted}.")
    else:
        print(f"{count} {noun} hold the ceiling of {ceiling}.")

    return 1 if count > ceiling else 0
