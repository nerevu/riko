"""
Lists public names removed since a release that the changelog never mentions.

Usage:
    python .claude/skills/wrapup/surface_diff.py [--ref TAG]

For each public package (``riko``, ``riko.ext``, ``riko.types``, ``riko.bado``,
``riko.modules``, ``riko.io``) it reads the literal ``__all__`` of the package's
``__init__.py`` at ``TAG`` (default: the latest tag reachable from ``HEAD``) through
``git show`` and in the working tree, and prints each package's counts plus every
removed name that neither ``docs/CHANGES.rst`` nor ``docs/MIGRATION.rst`` names as a
whole word. A package absent at ``TAG`` counts as having no names; one whose ``__all__``
is not a literal list is reported as unreadable rather than guessed.

It exits 1 when a removed name is unlogged, else 0. `/wrapup`'s changelog sweep runs
it. Origin: the 2026-11-03 deep repo audit (promoted 2026-11-04).
"""

from __future__ import annotations

import argparse
import ast
import re
import shutil
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_PACKAGES = ("riko", "riko.ext", "riko.types", "riko.bado", "riko.modules", "riko.io")
_LOGS = ("docs/CHANGES.rst", "docs/MIGRATION.rst")
_SUMMARY = "Lists removed public names the changelog never mentions."
_GIT = shutil.which("git") or "git"


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_GIT, *args], cwd=_ROOT, capture_output=True, text=True, check=False
    )


def _parse_all(source: str) -> set[str] | None:
    names = None

    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        else:
            target, value = None, None

        if isinstance(target, ast.Name) and target.id == "__all__" and value:
            try:
                names = set(ast.literal_eval(value))
            except ValueError:
                names = None

    return names


def _is_logged(name: str, logged: str) -> bool:
    return re.search(rf"\b{re.escape(name)}\b", logged) is not None


def _read_all(package: str, ref: str | None) -> set[str] | None:
    """Reads a package's literal ``__all__``; an absent package has no names."""
    path = f"{package.replace('.', '/')}/__init__.py"

    if ref is None:
        file = _ROOT / path
        source = file.read_text() if file.exists() else None
    else:
        shown = _git("show", f"{ref}:{path}")
        source = shown.stdout if shown.returncode == 0 else None

    return set() if source is None else _parse_all(source)


def main() -> int:
    parser = argparse.ArgumentParser(description=_SUMMARY)
    parser.add_argument("--ref", help="release tag (default: latest reachable tag)")
    args = parser.parse_args()
    ref = args.ref or _git("describe", "--tags", "--abbrev=0", "HEAD").stdout.strip()
    logged = "\n".join((_ROOT / log).read_text() for log in _LOGS)
    unlogged_total = 0
    print(f"baseline {ref}")

    for package in _PACKAGES:
        before, after = _read_all(package, ref), _read_all(package, None)

        if before is None or after is None:
            print(f"{package}: unreadable __all__ (baseline or HEAD is not a literal)")
        else:
            removed = sorted(before - after)
            unlogged = [n for n in removed if not _is_logged(n, logged)]
            unlogged_total += len(unlogged)
            print(
                f"{package}: baseline={len(before)} head={len(after)} "
                f"removed={len(removed)} unlogged={unlogged}"
            )

    return 1 if unlogged_total else 0


if __name__ == "__main__":
    sys.exit(main())
