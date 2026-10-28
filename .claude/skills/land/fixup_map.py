"""
Maps a working-tree change onto fixup targets among the branch's own commits.

Usage: python .claude/skills/land/fixup_map.py [--cached] [--patches DIR] [--base REF]
       [--blame-only]

The branch's own commits are those past its merge point: ``REF..HEAD`` where REF
defaults to the nearest merge-base with ``next`` or ``main`` (local, else ``origin/``).
Pushed or not, any of them can be a fixup target.

Each hunk of ``git diff -U3 HEAD`` (``--cached``: the staged diff only) is blamed
against HEAD. A hunk whose blamed lines all come from one branch commit (after
following ``fixup!`` chains) is a single-target hunk. It is a fixup *candidate*
when every identifier its added lines use already exists in that target commit's
tree; otherwise it depends on the change and stays in the new commit. New and
deleted files also stay in the new commit.

A hunk with mixed or pre-branch blame falls back to its file's *latest touch*: the
newest branch commit (after following ``fixup!`` chains) that edits the file. Squashed
there, the hunk sees the file exactly as HEAD has it. Blame cannot vouch that the
hunk belongs to that commit, so these print marked ``*`` and the caller judges
each by subject. ``--blame-only`` keeps them in the new commit instead, so only
hunks blame vouches for are offered.

Prints a short table, never the hunks themselves. ``--patches DIR`` also writes
one ``<sha>.patch`` per candidate target, ready for the rehearsal worktree.
"""

from __future__ import annotations

import argparse
import ast
import keyword
import re
import subprocess
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

DESCRIPTION = "Map a working-tree change onto fixup targets."
HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,\d+)? @@(.*)$")
PY_IDENT_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]{2,}\b")
DOC_IDENT_RE = re.compile(r"`+([^`\s]+)`+")
DOC_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
DEFINES_RE = re.compile(
    r"\b(?:def|class)\s+(\w+)|^\s*(\w+)\s*(?::[^=]*)?=(?!=)"
    r"|\bfor\s+(\w+)\s+in\b|\bas\s+(\w+)|(\w+)\s*:=|^\s+(\w+)\s*:"
)
STRING_RE = re.compile(r"\"[^\"\n]*\"|'[^'\n]*'")
IGNORED = set(keyword.kwlist) | set(dir(__builtins__)) | {"self", "cls", "None"}


@dataclass
class Hunk:
    path: str
    header: str
    lines: list[str]
    old_start: int
    old_count: int
    new_start: int

    @property
    def added(self) -> list[str]:
        return [line[1:] for line in self.lines if line.startswith("+")]

    @property
    def numbered_added(self) -> list[tuple[int, str]]:
        """Pairs each added line with its line number in the new file."""
        numbered: list[tuple[int, str]] = []
        line_no = self.new_start

        for line in self.lines:
            if line.startswith("+"):
                numbered.append((line_no, line[1:]))

            line_no += line.startswith(("+", " "))

        return numbered

    @property
    def removed(self) -> int:
        return sum(line.startswith("-") for line in self.lines)

    @property
    def summary(self) -> str:
        changed = next((t for t in self.added if t.strip()), "")
        changed = changed or next((t for t in self.lines if t[:1] == "-"), "-")[1:]
        return changed.strip()[:60]


@dataclass
class FileDiff:
    path: str
    header: list[str]
    status: str = "M"
    hunks: list[Hunk] = field(default_factory=list)


def git(*args: str) -> str:
    cmd = ("git", *args)
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)

    if result.returncode not in (0, 1):
        sys.exit(f"git {' '.join(args)} failed: {result.stderr.strip()}")

    return result.stdout


def parse_diff(text: str) -> list[FileDiff]:
    files: list[FileDiff] = []
    current: FileDiff | None = None
    hunk: Hunk | None = None

    for line in text.splitlines():
        if line.startswith("diff --git "):
            current = FileDiff(line.split(" b/", 1)[1], [line])
            files.append(current)
            hunk = None
        elif current is None:
            continue
        elif match := HUNK_RE.match(line):
            old_count = 1 if match[2] is None else int(match[2])
            args = (int(match[1]), old_count, int(match[3]))
            hunk = Hunk(current.path, line, [], *args)
            current.hunks.append(hunk)
        elif hunk is not None:
            hunk.lines.append(line)
        else:
            current.header.append(line)

            if line.startswith("new file"):
                current.status = "A"
            elif line.startswith("deleted file"):
                current.status = "D"
            elif line.startswith("rename from"):
                current.status = "R"

    return files


BASE_BRANCHES = ("next", "main", "origin/next", "origin/main")


def merge_point() -> str:
    """Finds the nearest merge-base of HEAD with a base branch that resolves."""
    refs = [b for b in BASE_BRANCHES if git("rev-parse", "--verify", "--quiet", b)]
    bases = {git("merge-base", "HEAD", ref).strip() for ref in refs}
    found = [b for b in bases if b]

    if not found:
        sys.exit(f"no merge point with {', '.join(BASE_BRANCHES)}; pass --base REF")

    return min(found, key=lambda b: int(git("rev-list", "--count", f"{b}..HEAD")))


def branch_commits(base: str) -> dict[str, str]:
    log = git("log", "--format=%H%x00%s", f"{base}..HEAD")
    return dict(line.split("\0", 1) for line in log.splitlines() if line)


def resolve_target(sha: str, commits: dict[str, str]) -> str | None:
    seen: set[str] = set()

    while (subject := commits[sha]).startswith("fixup! ") and sha not in seen:
        seen.add(sha)
        ref = subject.removeprefix("fixup! ")
        matches = [k for k, v in commits.items() if v == ref or k.startswith(ref)]
        found = matches[0] if matches else None

        if found is None:
            return None

        sha = found

    return sha


def squashed_ref(target: str, commits: dict[str, str]) -> str:
    """Names the newest commit folding into ``target``: its tree once fixups squash."""
    folds = (sha for sha in commits if resolve_target(sha, commits) == target)
    return next(folds, target)


def latest_touch(path: str, commits: dict[str, str]) -> str | None:
    """Finds the newest branch target that edits ``path``, once fixups squash."""
    log = git("log", "--format=%H", "HEAD", "--", path)
    targets = {resolve_target(sha, commits) for sha in log.split() if sha in commits}
    return next((sha for sha in commits if sha in targets), None)


def blamed_lines(hunk: Hunk) -> list[int]:
    """Lists the old line numbers a hunk removes, else its context for an addition."""
    removed: list[int] = []
    context: list[int] = []
    line_no = hunk.old_start

    for line in hunk.lines:
        if line.startswith("-"):
            removed.append(line_no)
            line_no += 1
        elif line.startswith(" "):
            context.append(line_no)
            line_no += 1

    return removed or context


def blame_shas(hunk: Hunk) -> set[str]:
    spans = [arg for n in blamed_lines(hunk) for arg in ("-L", f"{n},{n}")]
    out = git("blame", "-l", "-s", *spans, "HEAD", "--", hunk.path)
    return {line.split()[0].lstrip("^") for line in out.splitlines() if line}


def defined_names(hunk: Hunk) -> set[str]:
    """Collects the names a hunk's added lines define."""
    return {
        name
        for text in hunk.added
        for groups in DEFINES_RE.findall(text)
        for name in groups
        if name
    }


@cache
def string_lines(path: str, cached: bool) -> frozenset[int]:
    """Lists the new file's lines inside docstrings and other bare string statements."""
    if cached:
        source = git("show", f":{path}")
    else:
        root = Path(git("rev-parse", "--show-toplevel").strip())
        source = (root / path).read_text()

    try:
        tree = ast.parse(source)
    except SyntaxError:
        tree = ast.Module(body=[], type_ignores=[])

    return frozenset(
        line
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
        for line in range(node.lineno, (node.end_lineno or node.lineno) + 1)
    )


def identifiers(hunk: Hunk, *, cached: bool = False) -> set[str]:
    names: set[str] = set()
    is_py = hunk.path.endswith(".py")
    prose = string_lines(hunk.path, cached) if is_py else frozenset()

    lines = [text for line_no, text in hunk.numbered_added if line_no not in prose]

    for text in lines:
        if is_py:
            code = STRING_RE.sub(" ", text.split("#", 1)[0])
            names.update(PY_IDENT_RE.findall(code))
        else:
            for quoted in DOC_IDENT_RE.findall(text):
                if not set(quoted) & set("*<>"):
                    names.update(DOC_NAME_RE.findall(quoted))

    return names - IGNORED - defined_names(hunk)


def missing_at(target: str, names: set[str]) -> set[str]:
    patterns = [arg for name in sorted(names) for arg in ("-e", name)]
    found = git("grep", "-hwoF", *patterns, target, "--") if names else ""
    present = {line.strip().split(":")[-1] for line in found.splitlines()}
    return names - present


def classify(
    diff: FileDiff, hunk: Hunk, commits: dict[str, str], *, cached: bool = False
) -> tuple[str, str | None, Hunk, set[str]]:
    """Sorts one hunk: a kept reason, or its single target and missing names."""
    if diff.status != "M" or hunk.old_count == 0:
        result = ("new, deleted, or renamed file", None, hunk, set())
    else:
        shas = blame_shas(hunk)
        targets = {resolve_target(s, commits) if s in commits else None for s in shas}

        reason = "pre-branch blame" if None in targets else "mixed blame"

        if None in targets or len(targets) > 1:
            target = latest_touch(hunk.path, commits)
            label = f"latest touch ({reason})"
        else:
            target = next(t for t in targets if t is not None)
            label = "single"

        if target is None:
            result = (reason, None, hunk, set())
        else:
            missing = missing_at(
                squashed_ref(target, commits), identifiers(hunk, cached=cached)
            )
            result = (label, target, hunk, missing)

    return result


def write_patches(
    directory: Path, candidates: dict[str, list[Hunk]], files: list[FileDiff]
) -> None:
    headers = {f.path: f.header for f in files}
    directory.mkdir(parents=True, exist_ok=True)

    for target, hunks in candidates.items():
        by_file: dict[str, list[Hunk]] = defaultdict(list)

        for hunk in hunks:
            by_file[hunk.path].append(hunk)

        body = [
            line
            for path, path_hunks in by_file.items()
            for line in (
                *headers[path],
                *(x for h in path_hunks for x in (h.header, *h.lines)),
            )
        ]
        (directory / f"{target[:10]}.patch").write_text("\n".join(body) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument(
        "--cached", action="store_true", help="map only the staged diff"
    )
    parser.add_argument(
        "--patches", type=Path, help="write <sha>.patch per candidate target"
    )
    parser.add_argument(
        "--base", help="merge point (default: nearest merge-base with next or main)"
    )
    parser.add_argument(
        "--blame-only", action="store_true", help="offer only single-blame hunks"
    )
    args = parser.parse_args()

    base = args.base or merge_point()
    commits = branch_commits(base)
    # a rename would pair a new path with an old one blame cannot find in HEAD
    diff_args = ("diff", "--no-renames", "-U3", "--cached" if args.cached else "HEAD")
    files = parse_diff(git(*diff_args))
    candidates: dict[str, list[Hunk]] = defaultdict(list)
    dependent: dict[str, list[tuple[Hunk, set[str]]]] = defaultdict(list)
    kept = defaultdict(int)

    pairs: list[tuple[FileDiff, Hunk]] = [
        (diff, hunk) for diff in files for hunk in diff.hunks
    ]
    total = len(pairs)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(
            pool.map(
                lambda pair: classify(pair[0], pair[1], commits, cached=args.cached),
                pairs,
            )
        )

    latest = {id(h) for kind, _, h, _ in results if kind.startswith("latest touch")}

    for kind, target, hunk, missing in results:
        if target is None:
            kept[kind] += 1
        elif args.blame_only and id(hunk) in latest:
            kept["latest touch only (--blame-only)"] += 1
        elif missing:
            dependent[target].append((hunk, missing))
        else:
            candidates[target].append(hunk)

    for target, items in list(dependent.items()):
        moved = True

        while moved:
            provided = {n for h in candidates[target] for n in defined_names(h)}
            joining = [(h, m) for h, m in items if m <= provided]
            items = [(h, m) for h, m in items if not m <= provided]
            candidates[target].extend(h for h, _ in joining)
            moved = bool(joining)

        dependent[target] = items

    candidates = {k: v for k, v in candidates.items() if v}
    dependent = {k: v for k, v in dependent.items() if v}
    print(f"{len(commits)} commits past {base[:10]}, {total} hunks")
    print("\nFIXUP CANDIDATES (read each hunk before offering it)")
    print("  * = latest touch, not blame: offer only if the subject fits the hunk")

    for target, hunks in candidates.items():
        print(f"  {target[:10]} {commits[target][:60]}")

        for h in hunks:
            mark = "*" if id(h) in latest else " "
            where = f"{h.path}:{h.new_start}"
            print(f"   {mark}{where}  +{len(h.added)}/-{h.removed}  {h.summary}")

    if not candidates:
        print("  none")

    print("\nKEPT IN THE NEW COMMIT")
    untracked = git("ls-files", "--others", "--exclude-standard").split()

    if untracked and not args.cached:
        print(f"  {len(untracked):4} untracked files: {', '.join(untracked[:4])}")

    for reason, count in kept.items():
        print(f"  {count:4} {reason}")

    for target, items in dependent.items():
        names = sorted({n for _, missing in items for n in missing})
        shown = ", ".join(names[:6]) + (", ..." if len(names) > 6 else "")
        label = f"single-target on {target[:10]}, need names absent there"
        print(f"  {len(items):4} {label}: {shown}")

    if args.patches is not None and candidates:
        write_patches(args.patches, candidates, files)
        print(f"\npatches written to {args.patches}/")


if __name__ == "__main__":
    main()
