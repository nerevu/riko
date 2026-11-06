"""
Report drift between inspiration snapshots and their source readmes.

Purpose: each readme-derived file in ``_docs/research/inspiration/`` is a verbatim
snapshot that opens with a ``source:`` line (YAML front matter in Markdown, a
``.. source:`` comment in reStructuredText) giving the readme's path relative to the
snapshot. This compares each snapshot's body, the bytes after that header, with its
source and lists the ones that differ. It never writes.

Inputs: ``--diff`` prints a unified diff for each differing snapshot.

Outputs: one line per file (``same``, ``differs (N lines)``, ``missing source``, or
``no source line``); exit 1 when a snapshot differs or its source is missing.

Origin: 2026-11-04 audit of whether inspiration readmes should be symlinks.
"""

import argparse
import difflib
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_INSPIRATION = _ROOT / "_docs" / "research" / "inspiration"
_HEADER = re.compile(
    rb"\A(?:---\nsource: (?P<md>[^\n]+)\n---\n\n|\.\. source: (?P<rst>[^\n]+)\n\n)"
)


def _split_bytes(data: bytes) -> tuple[bytes | None, bytes]:
    match = _HEADER.match(data)
    end = 0 if match is None else match.end()
    return (None if match is None else data[:end]), data[end:]


def _split_source(path: Path, data: bytes) -> tuple[Path | None, bytes]:
    header, body = _split_bytes(data)
    match = None if header is None else _HEADER.match(header)
    source = None

    if match is not None:
        source = path.parent / (match["md"] or match["rst"]).decode()

    return source, body


def _split(path: Path) -> tuple[Path | None, bytes]:
    return _split_source(path, path.read_bytes())


def _lines(data: bytes) -> list[str]:
    return data.decode("utf-8", "replace").splitlines(keepends=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report inspiration snapshot drift.")
    parser.add_argument("--diff", action="store_true")
    args = parser.parse_args(argv)
    failures = 0

    for snapshot in sorted(_INSPIRATION.iterdir()):
        source, body = _split(snapshot)

        if source is None:
            print(f"{snapshot.name}: no source line")
        elif not source.is_file():
            failures += 1
            print(f"{snapshot.name}: missing source {source}")
        elif body == source.read_bytes():
            print(f"{snapshot.name}: same")
        else:
            failures += 1
            target = str(source.resolve())
            old, new = _lines(body), _lines(source.read_bytes())
            delta = list(difflib.unified_diff(old, new, snapshot.name, target))
            changed = sum(1 for line in delta[2:] if line[:1] in "+-")
            print(f"{snapshot.name}: differs ({changed} lines)")

            if args.diff:
                sys.stdout.writelines(delta)

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
