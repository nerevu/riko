"""
Lists the touched neighborhood of a diff: the references that outlive a change.

Usage:
    gates.py scope tidy | python .claude/skills/tidy/neighborhood.py
    python .claude/skills/tidy/neighborhood.py --diff-file .claude/tidy-scope.diff
    python .claude/skills/tidy/neighborhood.py --base <tree-ish> [--roots riko tests]

Reads a unified diff and collects, per file, the module- or class-level
definitions it removed, re-signed (the ``def``/``class`` line changed but the name
survived), and added. Each removed or re-signed name is then looked up with
``git grep -nw --untracked`` across the documentation and source roots, so the
callers and doc mentions tidy must check arrive in one call instead of one grep
per symbol. A name removed in one file and added in another is
reported as a move, not grepped; added names are listed so a same-file removal
plus addition reads as the rename it usually is.

Only lines the diff touched are read; a def line is matched at any indentation
and a constant only at column zero. The scan is static and takes about a second.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass, field

GIT = shutil.which("git") or "git"
DESCRIPTION = "List the references that outlive a diff's definition changes."
ROOTS = ("riko", "tests", "docs", "_docs", "examples", "README.rst", "CONTRIBUTING.rst")
FILE_HEADER = re.compile(r"^\+\+\+ (?:b/)?(.+)$")
DEF_LINE = re.compile(r"^[-+](\s*)(?:async\s+)?(?:def|class)\s+(\w+)")
CONSTANT_LINE = re.compile(r"^[-+]([A-Za-z_]\w*)\s*(?::[^=]*)?=")
MAX_HITS = 25
SAVED_DIFF = re.compile(r"written to (\S+);")


@dataclass
class FileChange:
    """Names a file's diff removed, re-signed, or added at definition level."""

    removed: dict[str, str] = field(default_factory=dict)
    added: dict[str, str] = field(default_factory=dict)

    @property
    def gone(self) -> list[str]:
        return sorted(set(self.removed) - set(self.added))

    @property
    def resigned(self) -> list[str]:
        return sorted(
            name
            for name in set(self.removed) & set(self.added)
            if self.removed[name] != self.added[name]
        )

    @property
    def new(self) -> list[str]:
        return sorted(set(self.added) - set(self.removed))


def get_definition(line: str) -> tuple[str, str] | None:
    """Gets the ``(name, signature)`` a diff line defines, or ``None``."""
    match = DEF_LINE.match(line)

    if match is not None:
        definition = (match.group(2), line[1:].strip())
    elif (constant := CONSTANT_LINE.match(line)) is not None:
        definition = (constant.group(1), constant.group(1))
    else:
        definition = None

    return definition


def parse_diff(text: str) -> dict[str, FileChange]:
    """Parses a unified diff into the definitions each file removed or added."""
    changes: dict[str, FileChange] = defaultdict(FileChange)
    current = None

    for line in text.splitlines():
        header = FILE_HEADER.match(line)

        if header is not None:
            current = header.group(1)
        elif (
            current is not None and line[:1] in "-+" and line[:3] not in {"---", "+++"}
        ):
            definition = get_definition(line)

            if definition is not None:
                side = (
                    changes[current].removed
                    if line[0] == "-"
                    else changes[current].added
                )
                side.setdefault(*definition)

    return {
        path: change
        for path, change in changes.items()
        if change.removed or change.added
    }


def grep_references(name: str, roots: tuple[str, ...]) -> list[str]:
    """Loads the ``file:line: text`` references to ``name`` across ``roots``."""
    present = [root for root in roots if os.path.exists(root)]
    found = subprocess.run(
        [GIT, "grep", "-nw", "--untracked", "-e", name, "--", *present],
        capture_output=True,
        text=True,
        check=False,
    )
    return found.stdout.splitlines()


def is_definition_of(name: str, hit: str) -> bool:
    """Reports whether a grep hit is the definition line of ``name`` itself."""
    text = hit.split(":", 2)[-1].lstrip()
    return bool(
        re.match(rf"(?:async\s+)?(?:def|class)\s+{name}\b|{name}\s*(?::[^=]*)?=", text)
    )


def report(changes: dict[str, FileChange], roots: tuple[str, ...]) -> str:
    """Builds the neighborhood report for the parsed changes."""
    lines = []
    homes = {name: path for path, change in changes.items() for name in change.new}

    for path, change in sorted(changes.items()):
        lines.append(f"== {path}")
        moved = [name for name in change.gone if name in homes]
        lines.extend(f"  moved {name} -> {homes[name]}" for name in moved)
        gone = [name for name in change.gone if name not in homes]

        for label, names in (("removed", gone), ("re-signed", change.resigned)):
            for name in names:
                hits = [
                    hit
                    for hit in grep_references(name, roots)
                    if not is_definition_of(name, hit)
                ]
                lines.append(f"  {label} {name} ({len(hits)} references)")
                lines.extend(f"    {hit}" for hit in hits[:MAX_HITS])

                if len(hits) > MAX_HITS:
                    lines.append(f"    ... {len(hits) - MAX_HITS} more")

        if change.new:
            lines.append(f"  added {', '.join(change.new)}")

    return "\n".join(lines) if lines else "no definition-level changes in the diff"


def load_diff(base: str | None, diff_file: str | None) -> str:
    """Loads the diff from ``--base``, ``--diff-file``, or stdin (or its pointer)."""
    if base is not None:
        text = subprocess.run(
            [GIT, "diff", base], capture_output=True, text=True, check=True
        ).stdout
    elif diff_file is not None:
        with open(diff_file) as handle:
            text = handle.read()
    else:
        text = sys.stdin.read()
        pointer = SAVED_DIFF.search(text)

        if pointer is not None and "diff --git" not in text:
            with open(pointer.group(1)) as handle:
                text = handle.read()

    return text


def main(argv: list[str] | None = None) -> int:
    """Parses the command line and prints the neighborhood report."""
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument("--base", help="git tree-ish to diff the working tree from")
    parser.add_argument(
        "--diff-file", help="read a saved unified diff instead of stdin"
    )
    parser.add_argument("--roots", nargs="*", default=list(ROOTS), help="paths to grep")
    args = parser.parse_args(argv)
    changes = parse_diff(load_diff(args.base, args.diff_file))
    print(report(changes, tuple(args.roots)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
