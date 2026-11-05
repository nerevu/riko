"""
Run a change's regression tests against the code before the change.

Proves each new or changed test fails without the fix (the /triage and /diagnose
"fails on the old code" step) without stashing, checking out, or touching the
user's tree. It exports ``--ref`` with ``git archive`` into a fresh temp folder,
overlays the test files that differ between ``--ref`` and the working tree
(``tests/``, helpers included, plus the skill scripts'
``test_*.py``/``conftest.py`` under ``.claude/skills/``), and runs pytest there.

Inputs: ``--ref`` (default ``HEAD``) and pytest selectors after ``--`` (test files,
node ids, or ``-k EXPR``). When the fix is uncommitted, ``--old PATH=SOURCE``
(repeatable) builds the old code instead: the working tree with each ``PATH`` swapped
for ``SOURCE`` (a file on disk, or ``REF:PATH``), committed through a private index on
top of ``--ref`` and reachable from no branch.

Outputs: pytest's ``FAILED`` lines and summary from the old code, then a verdict.
Exits 0 when every selected test fails at ``--ref`` (the tests catch the bug) and 1
when any passes there (it guards something else, or does not probe the bug).

Origin: 2026-10-30 audit-triage session, where the same export, copy, and run was
done by hand. The temp folder is left in place (never deleted).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING

from riko.base._paths import ROOT_DIR

if TYPE_CHECKING:
    from collections.abc import Iterable

GIT = shutil.which("git") or "git"
PYTEST_FLAGS = ("-q", "-p", "no:randomly", "-p", "no:cacheprovider", "--no-cov")
TEST_PATHS = (
    "tests",
    ":(glob).claude/skills/**/test_*.py",
    ":(glob).claude/skills/**/conftest.py",
)


def get_changed_tests(ref: str) -> list[str]:
    """Gets the test files that differ from ``ref``, untracked ones included."""
    diff = [GIT, "diff", "--name-only", ref, "--", *TEST_PATHS]
    untracked = [GIT, "ls-files", "--others", "--exclude-standard", "--", *TEST_PATHS]
    names = (
        subprocess.check_output(cmd, cwd=ROOT_DIR, text=True)
        for cmd in (diff, untracked)
    )
    return sorted({name for output in names for name in output.split()})


def _git_bytes(
    *args: str, env: dict[str, str] | None = None, data: bytes | None = None
) -> bytes:
    run = subprocess.run(
        [GIT, *args], cwd=ROOT_DIR, env=env, input=data, check=True, capture_output=True
    )
    return run.stdout


def _git(
    *args: str, env: dict[str, str] | None = None, data: bytes | None = None
) -> str:
    return _git_bytes(*args, env=env, data=data).decode().strip()


def _read_source(source: str) -> bytes:
    path = Path(source)
    exists = path.exists()
    return path.read_bytes() if exists else _git_bytes("show", source)


def build_snapshot(parent: str, swaps: Iterable[str]) -> str:
    """Builds a commit of the working tree with each ``PATH=SOURCE`` swapped in."""
    index = Path(tempfile.mkdtemp(prefix="fail-first-index-")) / "index"
    env = {**os.environ, "GIT_INDEX_FILE": str(index)}
    _git("read-tree", parent, env=env)
    _git("add", "-A", env=env)

    for swap in swaps:
        path, source = swap.split("=", 1)
        blob = _git("hash-object", "-w", "--stdin", data=_read_source(source))
        _git("update-index", "--cacheinfo", f"100644,{blob},{path}", env=env)

    tree = _git("write-tree", env=env)
    return _git("commit-tree", tree, "-p", parent, "-m", "fail-first snapshot")


def build_old_tree(ref: str) -> Path:
    """Builds ``ref``'s tree with the working tree's changed test files on top."""
    folder = Path(tempfile.mkdtemp(prefix="fail-first-"))
    archive = subprocess.run(
        [GIT, "archive", ref], cwd=ROOT_DIR, check=True, capture_output=True
    )

    with tarfile.open(fileobj=BytesIO(archive.stdout)) as tar:
        tar.extractall(folder, filter="data")

    for name in get_changed_tests(ref):
        if (ROOT_DIR / name).exists():
            (folder / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT_DIR / name, folder / name)

    return folder


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(__doc__ or "").strip().splitlines()[0]
    )
    parser.add_argument("--ref", default="HEAD")
    parser.add_argument("--old", action="append", default=[], metavar="PATH=SOURCE")
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    selectors = [arg for arg in args.pytest_args if arg != "--"]
    ref = build_snapshot(args.ref, args.old) if args.old else args.ref
    folder = build_old_tree(ref)
    command = [sys.executable, "-m", "pytest", *PYTEST_FLAGS, "-o", "addopts=", "-rf"]
    env = {**os.environ, "PYTHONPATH": str(folder)}
    run = subprocess.run(
        [*command, *selectors],
        cwd=folder,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    lines = [
        line.replace(f"{folder}/", "")
        for line in run.stdout.splitlines()
        if line.startswith("FAILED") or " passed" in line or " failed" in line
    ]
    summary = lines[-1] if lines else ""
    caught = run.returncode == 1 and " passed" not in summary

    if run.returncode not in {0, 1}:
        verdict = f"no test ran or pytest failed (exit {run.returncode})"
    elif caught:
        verdict = "every selected test fails on the old code"
    else:
        verdict = "some test passes on the old code"

    print(f"old code at {ref} in {folder}", *lines, sep="\n")
    print(f"verdict: {verdict}")
    return 0 if caught else 1


if __name__ == "__main__":
    raise SystemExit(main())
