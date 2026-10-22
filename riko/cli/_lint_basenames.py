# vim: sw=4:ts=4:expandtab

"""
Checks that no two package modules share a file name.

Duplicate basenames make tracebacks, editor tabs, and search results ambiguous, so
each pair must be deliberate and allowlisted. An allowlisted name that is no longer
duplicated is reported too, so the allowlist cannot outlive its pairs.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, NamedTuple

from riko.base._config import DUPLICATE_BASENAMES

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


class BasenameIssue(NamedTuple):
    """A duplicated module basename, or an allowlist entry that names none."""

    basename: str
    paths: tuple[Path, ...]
    message: str

    def __str__(self) -> str:
        """Renders the issue as a ``basename: message (paths)`` line."""
        paths = ", ".join(str(path) for path in self.paths)
        return f"{self.basename}: {self.message} ({paths})"


def gen_basename_issues(
    *roots: Path, allowed: frozenset[str] = DUPLICATE_BASENAMES
) -> Iterator[BasenameIssue]:
    """
    Finds module basenames shared by more than one file under ``roots``.

    Args:

        roots: The package folders to scan.
        allowed: Basenames that may be shared.

    Yields:

        One finding per shared basename not in ``allowed``, then one per ``allowed``
        entry that is no longer shared.

    """
    groups: defaultdict[str, list[Path]] = defaultdict(list)

    for root in roots:
        for path in sorted(root.rglob("*.py")):
            if path.name != "__init__.py":
                groups[path.name].append(path.relative_to(root.parent))

    duplicated = {name: paths for name, paths in groups.items() if len(paths) > 1}

    for name, paths in sorted(duplicated.items()):
        if name not in allowed:
            message = "basename is shared; rename one or allowlist the pair"
            yield BasenameIssue(name, tuple(sorted(paths)), message)

    for name in sorted(allowed - duplicated.keys()):
        message = "allowlisted basename is no longer duplicated; remove it"
        yield BasenameIssue(name, tuple(sorted(groups.get(name, []))), message)
