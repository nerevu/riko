# vim: sw=4:ts=4:expandtab
"""Provides string sanitization, docstring-summary, and truncation helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from functools import reduce
from typing import cast

from requests.structures import CaseInsensitiveDict

from ._iterutils import map_values


def replacer(content: str, old: str, new: str = "_") -> str:
    """
    Replaces ``old`` with ``new`` in ``content``.

    Additionally prepends ``content`` with ``new`` if ``content`` starts with a number
    or non-ASCII character.

    Examples:

        >>> replacer('', '')
        ''
        >>> replacer('1abc', '')
        '_1abc'
        >>> replacer('a.b', '.')
        'a_b'

    """
    if old:
        replaced = content.replace(old, new)
    elif content and (content[0].isdecimal() or not content[0].isascii()):
        replaced = f"{new}{content}"
    else:
        replaced = content

    return replaced


def pythonise(
    content: str, encoding: str = "ascii", replace: Sequence[str] = ("-", ":", "/", "")
) -> str:
    """
    Builds a Python-friendly id from ``content``.

    Args:

        content: The raw id to sanitize.
        encoding: The encoding used to drop non-representable characters.
        replace: The substrings replaced with ``_``.

    Returns:

        The sanitized id.

    """
    reduced = reduce(replacer, replace, content)
    return reduced.encode(encoding, "replace").decode(encoding)


def get_doc_summary(obj: object) -> str | None:
    """
    Gets the first non-blank line of an object's docstring.

    Args:

        obj: Any object; one without a docstring has no summary.

    Returns:

        The stripped summary line, or ``None`` when the docstring is missing or blank.

    Examples:

        >>> def shout():
        ...     '''
        ...     Shouts each item.
        ...
        ...     More detail.
        ...     '''
        >>> get_doc_summary(shout)
        'Shouts each item.'
        >>> get_doc_summary(lambda: None)

    """
    lines = (getattr(obj, "__doc__", None) or "").strip().splitlines()
    return lines[0].strip() if lines else None


def truncate_content[T](content: T | object, length: int = 20) -> T:
    if isinstance(content, str):
        truncated = content[:length] + "…" if len(content) > length else content
    elif isinstance(content, (dict, CaseInsensitiveDict, Mapping)):
        truncated = map_values(truncate_content, content)
    elif isinstance(content, (list, tuple, Sequence)):
        truncated = [truncate_content(v) for v in content]
    else:
        truncated = content

    return cast("T", truncated)
