"""
Move an inspiration readme between its candidate, its riko snapshot, and its source.

Purpose: a readme rewrite is drafted as a candidate, installed into the snapshot for
review, and, once staged, copied back to the source repo's readme so the snapshot and
its source stay byte-identical.

Inputs: ``install <snapshot> <candidate>`` keeps the snapshot's ``source:`` header,
appends the candidate with trailing whitespace stripped from every line, and reports
``removed_content.py`` leads for it. ``copyback [snapshot ...]`` writes each snapshot's
STAGED body (the git index, not the working tree) to the readme its ``source:`` line
names; with no names it takes every staged file under ``_docs/research/inspiration/``.
Snapshot names carry their extension (``ams.md``, ``lego.rst``; bare means ``.md``).

Outputs: the rewritten snapshot or readmes, then the removed-content leads (install)
or each ``<snapshot> -> <readme>`` line plus every ``inspiration_drift.py`` result
that is not ``same`` (copyback). Install exits 2 when the snapshot has no header;
copyback exits 1 when a snapshot has no staged header or any drift remains.

Origin: 2026-11-04/05 inspiration-readme rewrite (22 installs, 2 copybacks).
"""

import argparse
import contextlib
import io
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import inspiration_drift
import removed_content


def _git(*args: str) -> subprocess.CompletedProcess[bytes]:
    command = [removed_content._GIT, "-C", str(inspiration_drift._INSPIRATION), *args]
    return subprocess.run(command, capture_output=True, check=False)


def _strip_trailing(data: bytes) -> bytes:
    return b"\n".join(line.rstrip() for line in data.split(b"\n"))


def install(snapshot: Path, candidate: Path) -> int:
    """Installs a candidate readme into a snapshot under its existing header."""
    header, _ = inspiration_drift._split_bytes(snapshot.read_bytes())
    code = 2

    if header is None:
        print(f"{snapshot.name}: no source header", file=sys.stderr)
    else:
        snapshot.write_bytes(header + _strip_trailing(candidate.read_bytes()))
        removed_content.print_leads(snapshot)
        code = 0

    return code


def _staged_names() -> list[str]:
    result = _git(
        "diff", "--cached", "--name-only", "--relative", "--diff-filter=d", "--", "."
    )
    return result.stdout.decode().splitlines()


def _copy_staged(snapshot: Path) -> bool:
    staged = _git("show", f":./{snapshot.name}").stdout
    header, body = inspiration_drift._split_bytes(staged)
    source, _ = inspiration_drift._split(snapshot)

    if header is None or source is None:
        print(f"{snapshot.name}: no staged source header", file=sys.stderr)
    else:
        source.write_bytes(body)
        print(f"{snapshot.name} -> {source}")

    return header is not None and source is not None


def _print_drift() -> int:
    buffer = io.StringIO()

    with contextlib.redirect_stdout(buffer):
        code = inspiration_drift.main([])

    lines = buffer.getvalue().splitlines(keepends=True)
    sys.stdout.writelines(line for line in lines if not line.endswith(": same\n"))
    return code


def copyback(names: list[str]) -> int:
    """Copies each staged snapshot body back to its source readme."""
    snapshots = [removed_content.resolve_snapshot(name) for name in names]
    copied = [_copy_staged(snapshot) for snapshot in snapshots]
    code = _print_drift()
    return 1 if code or not all(copied) else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync inspiration snapshots.")
    commands = parser.add_subparsers(dest="command", required=True)
    install_parser = commands.add_parser("install")
    install_parser.add_argument("snapshot")
    install_parser.add_argument("candidate", type=Path)
    copyback_parser = commands.add_parser("copyback")
    copyback_parser.add_argument("snapshots", nargs="*", metavar="snapshot")
    args = parser.parse_args()

    if args.command == "install":
        code = install(removed_content.resolve_snapshot(args.snapshot), args.candidate)
    else:
        code = copyback(args.snapshots or _staged_names())

    return code


if __name__ == "__main__":
    sys.exit(main())
