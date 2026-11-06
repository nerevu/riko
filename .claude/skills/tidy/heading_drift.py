"""
Flags Markdown heading lines a working-tree change added, removed, or re-levelled.

Purpose: after `rumdl fmt`, a reflowed `#NN` at a line start becomes a heading and
MD001 then demotes every later heading in the file. This lists each heading the diff
touches so a cascade shows up before the docs lint trips over a truncated section.

Inputs: optional git base (default `HEAD`) and optional paths (default every changed
`*.md` file).
Outputs: `path: -old` / `path: +new` lines per touched heading, `relevelled` for a
heading whose text survives at another level; exit 1 when any heading was
relevelled or a new heading looks like a wrapped issue number (`## 60:`).

Origin: 2026-11-05 gameplan audit triage, where `rumdl fmt` demoted 18 headings in
implementation-sequence.md and the restore was done by hand.
"""

import re
import shutil
import subprocess
import sys

GIT = shutil.which("git") or "git"
_HEADING = re.compile(r"^(?P<hashes>#{1,6}) (?P<text>.*)$")
_ISSUE_LIKE = re.compile(r"^\d+:")


def _gen_heading_changes(base: str, paths: list[str]):
    """Yields (path, sign, level, text) for each added or removed heading line."""
    diff = subprocess.run(
        [GIT, "diff", "-U0", base, "--", *(paths or ["*.md"])],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    path = ""

    for line in diff.splitlines():
        if line.startswith("+++ "):
            path = line[6:]
        elif (
            line[:1] in {"+", "-"}
            and not line.startswith(("+++", "---"))
            and (match := _HEADING.match(line[1:]))
        ):
            yield path, line[0], len(match["hashes"]), match["text"]


def main() -> int:
    """Prints touched headings and returns 1 on a relevel or issue-like heading."""
    args = sys.argv[1:]
    base = args.pop(0) if args and not args[0].endswith(".md") else "HEAD"
    changes = list(_gen_heading_changes(base, args))
    removed = {
        (path, text): level for path, sign, level, text in changes if sign == "-"
    }
    bad = 0

    for path, sign, level, text in changes:
        old = removed.get((path, text)) if sign == "+" else None
        tag = "relevelled" if old is not None and old != level else ""
        issue = sign == "+" and _ISSUE_LIKE.match(text)
        bad += bool(tag or issue)
        print(
            f"{path}: {sign}{'#' * level} {text}  {tag}{' issue-like' if issue else ''}"
        )

    return int(bad > 0)


if __name__ == "__main__":
    sys.exit(main())
