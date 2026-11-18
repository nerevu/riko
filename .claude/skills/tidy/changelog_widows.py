"""
Lists changelog bullets whose last wrapped line is short (a "widow").

Purpose: find bullets in the unreleased section of ``docs/CHANGES.rst`` that spill
onto an extra line by only a word or two, so a small rewording saves a line.

Inputs: ``MAX_CHARS`` (optional, default 24): flag a bullet whose last line, stripped,
is at most this long. Reads ``docs/CHANGES.rst`` from the repository root and stops at
the second version heading (``vX.Y.Z (``), the first released one.

Outputs: one line per flagged bullet: ``start-end: last=<chars> words=<n> :: <text>``.

Origin: 2026-11-18 changelog audit (widow-line dimension); promoted to /tidy the
same day.
"""

import argparse
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_CHANGES = _ROOT / "docs" / "CHANGES.rst"
_VERSION = re.compile(r"^v\d+\.\d+\.\d+ \(")
_BULLET = re.compile(r"^\s*- ")


def _gen_bullets(lines: list[str]):
    """Yields each bullet's line indexes, its first line through its last."""
    current: list[int] | None = None

    for i, line in enumerate(lines):
        if _BULLET.match(line):
            if current is not None:
                yield current

            current = [i]
        elif current is not None and line.strip() and line[:1] == " ":
            current.append(i)
        elif current is not None:
            yield current
            current = None

    if current is not None:
        yield current


def main() -> None:
    parser = argparse.ArgumentParser(description="List short changelog last lines.")
    parser.add_argument("max_chars", nargs="?", type=int, default=24)
    args = parser.parse_args()
    lines = _CHANGES.read_text().splitlines()
    heads = [i for i, line in enumerate(lines) if _VERSION.match(line)]
    end = heads[1] if len(heads) > 1 else len(lines)

    for bullet in _gen_bullets(lines[:end]):
        last = lines[bullet[-1]].strip()

        if len(bullet) > 1 and len(last) <= args.max_chars:
            span = f"{bullet[0] + 1}-{bullet[-1] + 1}"
            print(f"{span}: last={len(last)} words={len(last.split())} :: {last}")


if __name__ == "__main__":
    main()
