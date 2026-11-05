"""
Audits the Claude memory directory for size, staleness, and link health.

Usage:
    python .claude/skills/wrapup/memory_audit.py [--memory DIR] [--top N]

It reports the index against Claude Code's load limits (200 lines or 25KB, a warning
from 140 lines or 18KB), index links that dangle, topic files the index misses or
lists twice, dangling ``[[wikilinks]]``, broken frontmatter, leftover "Index summary"
sections, and the largest topic files with counts of status notes, supersession
markers, and distinct dates, the signs a memory holds history rather than rulings.

It exits 1 when the index is over a hard limit, an index link dangles, or a topic
file is unindexed, else 0. `/wrapup` step 5 runs it after writing memory.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

_DEFAULT_MEMORY = (
    Path.home() / ".claude/projects/-Users-reubano-Documents-Projects-riko/memory"
)
_HARD_LINES = 200
_HARD_BYTES = 25_000
_WARN_LINES = 140
_WARN_BYTES = 18_000
_INDEX_LINK = re.compile(r"^- \[.*?\]\(([^)]+\.md)\)")
_WIKILINK = re.compile(r"\[\[([^\]]+)\]\]")
_STATUS = re.compile(
    r"uncommitted|at wrapup|LANDED|SHIPPED|COMMITTED|committed as|gates? green|passed",
    re.IGNORECASE,
)
_SUPERSEDED = re.compile(
    r"supersed|historical|no longer|update 20\d\d|reversed", re.IGNORECASE
)
_DATE = re.compile(r"20\d\d-\d\d-\d\d")
_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)


def get_frontmatter_problems(text: str) -> list[str]:
    """Gets what a topic file's frontmatter lacks: block, name, description, type."""
    match = _FRONTMATTER.match(text)
    block = "" if match is None else f"\n{match[1]}"
    checks = {
        "no frontmatter": match is not None,
        "no name": "\nname:" in block,
        "no description": "\ndescription:" in block,
        "no type": "type:" in block,
    }
    return [problem for problem, present in checks.items() if not present]


def get_index_status(text: str) -> str:
    """Gets the index size line with its standing against the load limits."""
    lines = len(text.splitlines())
    size = len(text.encode())
    if lines > _HARD_LINES or size > _HARD_BYTES:
        standing = "OVER HARD LIMIT"
    elif lines >= _WARN_LINES or size >= _WARN_BYTES:
        standing = "near limit"
    else:
        standing = "ok"
    return f"index: {lines} lines, {size} bytes ({standing})"


def get_link_report(index_text: str, files: dict[str, str]) -> dict[str, list[str]]:
    """Gets dangling, unindexed, doubled, and broken links between index and files."""
    indexed = [
        match[1]
        for line in index_text.splitlines()
        if (match := _INDEX_LINK.match(line))
    ]
    slugs = {name.removesuffix(".md") for name in files}
    wikis = {
        f"{name} -> {link}"
        for name, text in files.items()
        for link in _WIKILINK.findall(text)
        if link not in slugs
    }
    return {
        "dangling index links": sorted(set(indexed) - set(files)),
        "unindexed files": sorted(set(files) - set(indexed)),
        "indexed twice": sorted({name for name in indexed if indexed.count(name) > 1}),
        "dangling wikilinks": sorted(wikis),
    }


def gen_ranking(files: dict[str, str], top: int) -> Iterator[str]:
    """Generates ranking rows for the largest topic files with their history counts."""
    yield f"{'bytes':>6} {'stat':>4} {'supr':>4} {'date':>4}  file"
    ranked = sorted(files.items(), key=lambda item: -len(item[1].encode()))
    for name, text in ranked[:top]:
        status = len(_STATUS.findall(text))
        superseded = len(_SUPERSEDED.findall(text))
        dates = len(set(_DATE.findall(text)))
        size = len(text.encode())
        yield f"{size:>6} {status:>4} {superseded:>4} {dates:>4}  {name}"


def main() -> int:
    """Prints the audit and returns the exit status."""
    parser = argparse.ArgumentParser(description="Audit the Claude memory directory.")
    parser.add_argument("--memory", type=Path, default=_DEFAULT_MEMORY)
    parser.add_argument("--top", type=int, default=15)
    args = parser.parse_args()
    index_text = (args.memory / "MEMORY.md").read_text()
    files = {
        path.name: path.read_text()
        for path in sorted(args.memory.glob("*.md"))
        if path.name != "MEMORY.md"
    }
    status = get_index_status(index_text)
    links = get_link_report(index_text, files)
    total = sum(len(text.encode()) for text in files.values())
    print(status)
    print(f"live: {len(files)} files, {total} bytes")
    for label, items in links.items():
        print(f"{label}: {', '.join(items) if items else 'none'}")
    for name, text in files.items():
        if problems := get_frontmatter_problems(text):
            print(f"frontmatter: {name}: {', '.join(problems)}")
        if "\n## Index summary" in text:
            print(f"leftover index summary: {name}")
    print()
    print("\n".join(gen_ranking(files, args.top)))
    failed = (
        "OVER HARD LIMIT" in status
        or bool(links["dangling index links"])
        or bool(links["unindexed files"])
    )
    return int(failed)


if __name__ == "__main__":
    sys.exit(main())
