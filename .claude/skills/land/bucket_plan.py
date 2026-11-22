"""
Sorts every hunk of a working-tree change into commit-plan steps by per-run rules.

Usage:
    python .claude/skills/land/bucket_plan.py RULES --out DIR [--base REF]

It loads the change exactly as ``split_hunks.py list`` does (``-U0`` against
``--base``, default ``HEAD``, plus untracked files), assigns each hunk id to a bucket,
and writes ``DIR/plan.txt`` for ``rehearse_plan.py`` plus a ``<bucket>.msg`` file per
new-commit bucket, then prints each bucket's hunk count. Buckets with no hunk are left
out of the plan.

``RULES`` is a TOML file written for the run. ``[[bucket]]`` tables, in plan order,
each take a ``name`` and one of a ``message`` (a new commit), a ``fixup`` sha, or
``skip = true`` (ids left uncommitted).
``[[rule]]`` tables are tried in order and the first whose conditions all hold names
the hunk's ``bucket``; ``default`` names the bucket of a hunk no rule matches.
Conditions:

- ``ids``: selection entries as in a plan (``path``, ``path:N``, ``path:N-M``);
- ``path``: a regex searched in the hunk's path;
- ``body``: a regex searched (multiline) in the hunk's removed and added lines (an
  untracked file has none, so route it by ``path`` or ``ids``);
- ``swaps``: ``[old, new]`` word pairs that turn the hunk's removed lines into its
  added lines exactly (a pure rename).

Example::

    default = "feature"

    [[bucket]]
    name = "lock"
    message = "[DEV] Upgrade locked dependencies"

    [[bucket]]
    name = "tee"
    fixup = "1e7b5c1ce"

    [[bucket]]
    name = "feature"
    message = '''
    [NEW] Add Pipeline.split

    - Also document split branches
    '''

    [[rule]]
    bucket = "lock"
    path = '^uv\\.lock$'

    [[rule]]
    bucket = "tee"
    ids = ["riko/types/_options.py:65", "riko/bado/_tee.py"]
    body = "auto_close"
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import split_hunks

if TYPE_CHECKING:
    from collections.abc import Iterator

DESCRIPTION = "Sort a change's hunks into commit-plan steps by per-run rules."
BUCKET_KEYS = frozenset({"name", "message", "fixup", "skip"})
RULE_KEYS = frozenset({"bucket", "ids", "path", "body", "swaps"})


@dataclass(frozen=True)
class Bucket:
    """One plan step: a commit with ``message``, a fixup of ``fixup``, or a skip."""

    name: str
    message: str | None = None
    fixup: str | None = None
    skip: bool = False

    @property
    def kinds(self) -> int:
        """The number of step kinds set; a well-formed bucket sets exactly one."""
        return (self.message is not None) + (self.fixup is not None) + self.skip

    @property
    def header(self) -> str:
        """The bucket's plan-file header line."""
        return (
            "skip"
            if self.skip
            else f"commit {self.name}.msg"
            if self.fixup is None
            else f"fixup {self.fixup}"
        )


@dataclass(frozen=True)
class HunkText:
    """A hunk id with its path and its removed and added lines."""

    id: str
    path: str
    removed: tuple[str, ...]
    added: tuple[str, ...]


@dataclass(frozen=True)
class Rule:
    """Conditions that, when all hold, put a hunk in ``bucket``."""

    bucket: str
    ids: frozenset[str] | None = None
    path: re.Pattern[str] | None = None
    body: re.Pattern[str] | None = None
    swaps: tuple[tuple[str, str], ...] | None = None

    def is_swap(self, hunk: HunkText) -> bool:
        """Checks whether the swaps turn the removed lines into the added lines."""
        swapped = list(hunk.removed)

        for old, new in self.swaps or ():
            swapped = [re.sub(rf"\b{re.escape(old)}\b", new, s) for s in swapped]

        return bool(hunk.removed) and tuple(swapped) == hunk.added

    def matches(self, hunk: HunkText) -> bool:
        """Checks whether every condition of the rule holds for ``hunk``."""
        body = "\n".join(hunk.removed + hunk.added)
        return (
            (self.ids is None or hunk.id in self.ids)
            and (self.path is None or self.path.search(hunk.path) is not None)
            and (self.body is None or self.body.search(body) is not None)
            and (self.swaps is None or self.is_swap(hunk))
        )


def gen_hunks(files: list[split_hunks.FileChange]) -> Iterator[HunkText]:
    """Generates every selectable id of the change with its removed and added lines."""
    for hid, entry in split_hunks.index_hunks(files).items():
        parts = entry.hunks if isinstance(entry, split_hunks.FileChange) else [entry]
        removed = tuple(line for h in parts for line in h.deleted)
        added = tuple(line.rstrip("\n") for h in parts for line in h.added)
        yield HunkText(hid, entry.path, removed, added)


def _require_keys(table: dict[str, Any], keys: frozenset[str]) -> dict[str, Any]:
    extra = set(table) - keys

    if extra:
        sys.exit(f"unknown keys {sorted(extra)} in {table}")

    return table


def build_rule(raw: dict[str, Any], files: list[split_hunks.FileChange]) -> Rule:
    """Builds a rule from its TOML table, expanding its ids against the change."""
    table = _require_keys(raw, RULE_KEYS)
    ids = (split_hunks.expand(entry, files) for entry in table.get("ids", ()))
    path, body, swaps = table.get("path"), table.get("body"), table.get("swaps")
    return Rule(
        bucket=table["bucket"],
        ids=frozenset(i for found in ids for i in found) if "ids" in table else None,
        path=None if path is None else re.compile(path),
        body=None if body is None else re.compile(body, re.MULTILINE),
        swaps=None if swaps is None else tuple((old, new) for old, new in swaps),
    )


def load_rules(
    path: Path, files: list[split_hunks.FileChange]
) -> tuple[list[Bucket], list[Rule], str]:
    """Loads the buckets, rules, and default bucket, exiting on a malformed file."""
    data = tomllib.loads(path.read_text())
    tables = (_require_keys(raw, BUCKET_KEYS) for raw in data.get("bucket", []))
    buckets = [Bucket(**table) for table in tables]
    rules = [build_rule(raw, files) for raw in data.get("rule", [])]
    names = {bucket.name for bucket in buckets}
    default = data.get("default")
    unknown = {rule.bucket for rule in rules} - names
    steps = [bucket.name for bucket in buckets if bucket.kinds != 1]

    if default not in names:
        sys.exit(f"default {default!r} is not a bucket name")
    elif unknown:
        sys.exit(f"rules name unknown buckets: {', '.join(sorted(unknown))}")
    elif steps:
        sys.exit(f"buckets need exactly one of message/fixup/skip: {', '.join(steps)}")

    return buckets, rules, default


def resolve_bucket(hunk: HunkText, rules: list[Rule], default: str) -> str:
    """Resolves the bucket of the first rule that matches ``hunk``, else ``default``."""
    return next((r.bucket for r in rules if r.matches(hunk)), default)


def write_plan(
    out: Path, buckets: list[Bucket], assigned: dict[str, list[str]]
) -> list[str]:
    """Writes ``plan.txt`` and the message files; returns one count line per step."""
    out.mkdir(parents=True, exist_ok=True)
    lines, counts = [], []

    for bucket in buckets:
        ids = assigned.get(bucket.name, [])

        if ids and bucket.message is not None:
            message = bucket.message.strip("\n") + "\n"
            (out / f"{bucket.name}.msg").write_text(message)

        if ids:
            lines.extend([bucket.header, *ids])
            counts.append(f"{bucket.name:12} {len(ids):5}  {bucket.header}")

    (out / "plan.txt").write_text("\n".join(lines) + "\n")
    return counts


def main(argv: list[str] | None = None) -> int:
    """Parses the command line, sorts the hunks, and writes the plan."""
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument("rules", type=Path, help="the run's TOML rules file")
    parser.add_argument("--out", type=Path, required=True, help="plan folder")
    parser.add_argument("--base", default="HEAD", help="ref the hunks apply to")
    args = parser.parse_args(argv)
    split_hunks.set_base(args.base)
    files = split_hunks.load_change()
    buckets, rules, default = load_rules(args.rules, files)
    assigned: dict[str, list[str]] = {}

    for hunk in gen_hunks(files):
        assigned.setdefault(resolve_bucket(hunk, rules, default), []).append(hunk.id)

    print("\n".join(write_plan(args.out, buckets, assigned)))
    print(f"plan: {args.out / 'plan.txt'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
