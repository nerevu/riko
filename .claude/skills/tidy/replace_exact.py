"""
Applies checked exact-text replacements to one file.

Usage:
    python .claude/skills/tidy/replace_exact.py FILE SPEC.json [--dry-run]

SPEC.json is a list of ``[old, new, expected_count]`` triples, applied in order. Each
``old`` must occur exactly ``expected_count`` times in the text as it stands when its
turn comes; on any mismatch nothing is written and the script exits 1, naming the
triple. This makes a batch of stale-name fixes (the renames ``neighborhood.py``
reports) safe to apply: a replacement that would also hit an unrelated use of the same
text changes the count and stops the run. ``--dry-run`` checks the counts and reports
without writing.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DESCRIPTION = "Apply checked exact-text replacements to one file."


def apply_replacements(text: str, spec: list[list[object]]) -> tuple[str, list[str]]:
    """Applies each ``[old, new, count]`` triple and identifies mismatches."""
    errors: list[str] = []

    for old, new, count in spec:
        found = text.count(str(old))

        if found == count:
            text = text.replace(str(old), str(new))
        else:
            errors.append(f"expected {count} of {old!r}, found {found}")

    return text, errors


def main(argv: list[str]) -> int:
    """Parses the command line and applies the replacements, or checks them."""
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument("file", type=Path, help="the file to edit")
    parser.add_argument(
        "spec", type=Path, help="JSON list of [old, new, expected_count] triples"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="check the counts without writing"
    )
    args = parser.parse_args(argv)
    path, spec_path, dry_run = args.file, args.spec, args.dry_run
    spec = json.loads(spec_path.read_text())
    text, errors = apply_replacements(path.read_text(), spec)

    if errors:
        print("\n".join(f"{path}: {error}" for error in errors))
        status = 1
    elif dry_run:
        print(f"{path}: {len(spec)} replacements would apply")
        status = 0
    else:
        path.write_text(text)
        print(f"{path}: {len(spec)} replacements applied")
        status = 0

    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
