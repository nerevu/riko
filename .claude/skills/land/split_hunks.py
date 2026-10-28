"""
Lists a working-tree change as selectable hunks and builds trees from a selection.

Usage:
    python .claude/skills/land/split_hunks.py list [-U N]
    python .claude/skills/land/split_hunks.py emit SELECTION [-U N]

``list`` prints one line per hunk of ``git diff -U<N> HEAD`` (default ``-U0``, the
finest split) plus untracked files, each with a stable id:

- ``path:N`` is the hunk whose new-side start line is ``N``;
- ``path`` alone (in a selection) takes every hunk of that file, and is the only way
  to take a new, deleted, untracked, binary, or mode-only file.

A selection file holds one id per line (``#`` starts a comment; ``path:N-M`` takes the
hunks starting on lines ``N`` to ``M``). ``emit`` prints the patch against ``HEAD``
that applies exactly the selected hunks, ready for ``git apply --cached``.

Every hunk's old-side range is relative to ``HEAD``, so any subset of hunks splices
onto ``HEAD``'s files exactly and in any order. Trees are built in a temporary index
(``GIT_INDEX_FILE``); the real index and working tree are never touched.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

DESCRIPTION = "List a change's hunks by id, or emit the patch for a selection."
HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
NO_EOL = "\\ No newline at end of file"
NULL_SHA = "0" * 40
GIT = shutil.which("git") or "git"


@dataclass
class Hunk:
    path: str
    old_start: int
    old_count: int
    new_start: int
    added: list[str] = field(default_factory=list)
    removed: int = 0

    @property
    def id(self) -> str:
        return f"{self.path}:{self.new_start}"

    @property
    def summary(self) -> str:
        text = next((t for t in self.added if t.strip()), "").strip()
        return text[:60] or f"(-{self.removed} lines)"


@dataclass
class FileChange:
    """One changed path; ``whole`` paths can only be taken in full."""

    path: str
    status: str = "M"
    hunks: list[Hunk] = field(default_factory=list)

    @property
    def whole(self) -> bool:
        return self.status != "M" or not self.hunks


def git(
    *args: str, data: bytes | None = None, env: dict[str, str] | None = None
) -> str:
    result = subprocess.run(
        (GIT, *args), input=data, capture_output=True, check=False, env=env
    )

    if result.returncode not in (0, 1):
        sys.exit(f"git {' '.join(args)} failed: {result.stderr.decode().strip()}")

    return result.stdout.decode()


def parse_diff(text: str) -> list[FileChange]:
    files: list[FileChange] = []
    current: FileChange | None = None
    hunk: Hunk | None = None

    for line in text.splitlines():
        if line.startswith("diff --git "):
            current = FileChange(line.split(" b/", 1)[1])
            files.append(current)
            hunk = None
        elif current is None:
            continue
        elif match := HUNK_RE.match(line):
            old_count = 1 if match[2] is None else int(match[2])
            hunk = Hunk(current.path, int(match[1]), old_count, int(match[3]))
            current.hunks.append(hunk)
        elif hunk is not None and line == NO_EOL:
            if hunk.added and hunk.added[-1].endswith("\n"):
                hunk.added[-1] = hunk.added[-1][:-1]
        elif hunk is not None and line.startswith("+"):
            hunk.added.append(line[1:] + "\n")
        elif hunk is not None and line.startswith("-"):
            hunk.removed += 1
        elif line.startswith("new file"):
            current.status = "A"
        elif line.startswith("deleted file"):
            current.status = "D"
        elif line.startswith("Binary files"):
            current.status = "B"

    return files


def load_change(context: int = 0) -> list[FileChange]:
    """Loads ``git diff HEAD`` plus untracked files as selectable changes."""
    files = parse_diff(git("diff", "--no-renames", f"-U{context}", "HEAD"))
    untracked = git("ls-files", "--others", "--exclude-standard", "-z").split("\0")
    files.extend(FileChange(path, "?") for path in untracked if path)
    return files


def index_hunks(files: list[FileChange]) -> dict[str, Hunk | FileChange]:
    """Maps every selectable id to its hunk, or to its file for whole-only paths."""
    ids: dict[str, Hunk | FileChange] = {}

    for change in files:
        if change.whole:
            ids[change.path] = change
        else:
            ids.update((h.id, h) for h in change.hunks)

    return ids


def expand(entry: str, files: list[FileChange]) -> list[str]:
    """Expands one selection line (``path``, ``path:N``, ``path:N-M``) into ids."""
    by_path = {f.path: f for f in files}
    path, _, lines = entry.rpartition(":") if ":" in entry else (entry, "", "")
    change = by_path.get(path) if lines else by_path.get(entry)

    if change is None:
        sys.exit(f"unknown selection entry: {entry}")
    elif not lines:
        result = [change.path] if change.whole else [h.id for h in change.hunks]
    elif change.whole:
        sys.exit(f"{path} can only be taken whole; select it as `{path}`")
    else:
        low, _, high = lines.partition("-")
        span = range(int(low), int(high or low) + 1)
        result = [h.id for h in change.hunks if h.new_start in span]

        if not result:
            sys.exit(f"no hunk of {path} starts in {lines}")

    return result


def read_selection(path: Path) -> list[str]:
    raw = (line.split("#", 1)[0].strip() for line in path.read_text().splitlines())
    return [line for line in raw if line]


def splice(head: list[str], hunks: list[Hunk]) -> str:
    """Applies hunks (old ranges relative to ``head``) to ``head``'s lines."""
    out: list[str] = []
    pos = 0

    for hunk in sorted(hunks, key=lambda h: h.old_start):
        start = hunk.old_start if hunk.old_count == 0 else hunk.old_start - 1
        out.extend(head[pos:start])
        out.extend(hunk.added)
        pos = start + hunk.old_count

    out.extend(head[pos:])
    return "".join(out)


def file_mode(path: str) -> str:
    stat = os.lstat(path)
    executable = stat.st_mode & 0o111
    return "120000" if os.path.islink(path) else ("100755" if executable else "100644")


class TreeBuilder:
    """Builds ``HEAD`` plus a selection of hunks as a tree, in a private index."""

    def __init__(self, files: list[FileChange]) -> None:
        self.files = {f.path: f for f in files}
        self.ids = index_hunks(files)
        self.index = Path(tempfile.mkdtemp(prefix="split-hunks-")) / "index"
        self.env = {**os.environ, "GIT_INDEX_FILE": str(self.index)}
        self._blobs: dict[tuple[str, frozenset[str]], str] = {}

    def _blob(self, data: bytes) -> str:
        return git("hash-object", "-w", "--stdin", data=data).strip()

    def _entry(self, path: str, chosen: frozenset[str]) -> str:
        change = self.files[path]
        key = (path, chosen)

        if key not in self._blobs:
            if change.status == "D" and change.path in chosen:
                self._blobs[key] = f"0 {NULL_SHA}\t{path}"
            elif change.whole or len(chosen) == len(change.hunks):
                data = (
                    os.readlink(path).encode()
                    if os.path.islink(path)
                    else Path(path).read_bytes()
                )
                self._blobs[key] = f"{file_mode(path)} {self._blob(data)}\t{path}"
            else:
                head = git("show", f"HEAD:{path}").splitlines(keepends=True)
                hunks = [h for h in change.hunks if h.id in chosen]
                mode = git("ls-tree", "HEAD", "--", path).split()[0]
                blob = self._blob(splice(head, hunks).encode())
                self._blobs[key] = f"{mode} {blob}\t{path}"

        return self._blobs[key]

    def tree(self, selected: set[str]) -> str:
        """Writes the tree for ``HEAD`` plus the selected ids and returns its sha."""
        by_path: dict[str, set[str]] = {}

        for hid in selected:
            item = self.ids[hid]
            by_path.setdefault(item.path, set()).add(hid)

        git("read-tree", "HEAD", env=self.env)
        lines = [self._entry(p, frozenset(ids)) for p, ids in sorted(by_path.items())]
        git(
            "update-index", "--index-info", data="\n".join(lines).encode(), env=self.env
        )
        return git("write-tree", env=self.env).strip()


def working_tree() -> str:
    """Writes the working tree's tree (tracked plus untracked) via a private index."""
    index = Path(tempfile.mkdtemp(prefix="split-hunks-")) / "index"
    env = {**os.environ, "GIT_INDEX_FILE": str(index)}
    git("read-tree", "HEAD", env=env)
    git("add", "-A", env=env)
    return git("write-tree", env=env).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument("command", choices=("list", "emit"))
    parser.add_argument("selection", nargs="?", type=Path, help="file of ids for emit")
    parser.add_argument("-U", type=int, default=0, dest="context", help="diff context")
    args = parser.parse_args()
    files = load_change(args.context)

    if args.command == "list":
        for change in files:
            if change.whole:
                print(f"{change.path}\t[{change.status}] whole file")
            else:
                for h in change.hunks:
                    print(f"{h.id}\t+{len(h.added)}/-{h.removed}\t{h.summary}")
    elif args.selection is None:
        sys.exit("emit needs a selection file")
    else:
        ids = {i for e in read_selection(args.selection) for i in expand(e, files)}
        tree = TreeBuilder(files).tree(ids)
        sys.stdout.write(git("diff", "--binary", "HEAD", tree))


if __name__ == "__main__":
    main()
