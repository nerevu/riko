"""
Shows which lines of a change the test suite leaves uncovered.

Usage:
    python .claude/skills/land/diff_uncovered.py [--report PATH] [--base REF]
        [--baseline-ref REF | --baseline PATH] [--path DIR]

Without ``--report`` it runs the full suite once (``pytest -n auto``) with its own
coverage data file and JSON report in a temporary folder. The repo-root ``.coverage``
can be stale, so it is never read.

It prints every changed line (``git diff -U0 <base>`` plus untracked files under
``--path``) that the report marks as missing, with its source text, and exits
non-zero when there is any.

A ratchet can also fail on a line outside the diff that lost coverage (a deleted test,
a refactor that stops reaching a branch). ``--baseline-ref REF`` runs the suite on a
``git archive`` of ``REF`` and prints each file whose missing-line count changed;
``--baseline PATH`` reuses a JSON report instead.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from io import BytesIO
from pathlib import Path

DESCRIPTION = "List a change's uncovered lines and per-file coverage drift."
HUNK_RE = re.compile(r"^@@ -\S+ \+(\d+)(?:,(\d+))? @@")
GIT = shutil.which("git") or "git"


def _git(*args: str) -> str:
    return subprocess.run(
        [GIT, *args], check=True, capture_output=True, text=True
    ).stdout


def load_changed_lines(base: str, path: str) -> dict[str, set[int]]:
    """Loads the new-side line numbers each changed or untracked file adds."""
    changed: dict[str, set[int]] = {}
    current = None

    for line in _git("diff", "-U0", base, "--", path).splitlines():
        if line.startswith("+++ "):
            current = None if line == "+++ /dev/null" else line[6:]
        elif current and (match := HUNK_RE.match(line)):
            start, count = int(match[1]), int(match[2] or 1)
            changed.setdefault(current, set()).update(range(start, start + count))

    untracked = _git("ls-files", "--others", "--exclude-standard", "--", path)

    for name in untracked.splitlines():
        if name.endswith(".py"):
            lines = Path(name).read_text().count("\n") + 1
            changed[name] = set(range(1, lines + 1))

    return changed


def run_suite(cwd: Path, folder: Path, *, env: dict[str, str] | None = None) -> Path:
    """Runs the suite in ``cwd`` and returns its JSON coverage report."""
    report = folder / "coverage.json"
    run_env = {**os.environ, **(env or {}), "COVERAGE_FILE": str(folder / ".coverage")}
    cmd = [sys.executable, "-m", "pytest", "-q", "-n", "auto", "-p", "no:cacheprovider"]
    cmd += ["--cov=riko", f"--cov-report=json:{report}"]
    result = subprocess.run(
        cmd, cwd=cwd, env=run_env, capture_output=True, text=True, check=False
    )
    tail = result.stdout.strip().splitlines()[-1:] or ["(no output)"]
    print(f"suite in {cwd}: {tail[0]}", file=sys.stderr)

    if not report.exists():
        sys.exit(f"no coverage report written; pytest exited {result.returncode}")

    return report


def run_baseline(ref: str, folder: Path) -> Path:
    """Runs the suite on a ``git archive`` of ``ref`` and returns its report."""
    tree = folder / "tree"
    tree.mkdir()
    archive = subprocess.run([GIT, "archive", ref], check=True, capture_output=True)

    with tarfile.open(fileobj=BytesIO(archive.stdout)) as tar:
        tar.extractall(tree, filter="data")

    return run_suite(tree, folder, env={"PYTHONPATH": str(tree)})


def load_missing(report: Path) -> dict[str, list[int]]:
    """Loads each file's missing line numbers from a JSON coverage report."""
    files = json.loads(report.read_text())["files"]
    return {name: data["missing_lines"] for name, data in files.items()}


def print_uncovered(missing: dict[str, list[int]], changed: dict[str, set[int]]) -> int:
    """Prints each changed line the report misses and returns how many there are."""
    total = 0

    for name in sorted(changed):
        lines = sorted(set(missing.get(name, ())) & changed[name])

        if lines:
            source = Path(name).read_text().splitlines()
            print(f"{name}:")

            for number in lines:
                print(f"  {number:>5}  {source[number - 1].strip()}")

            total += len(lines)

    print(f"{total} uncovered changed line(s)")
    return total


def print_drift(missing: dict[str, list[int]], baseline: dict[str, list[int]]) -> None:
    """Prints each file whose missing-line count differs from the baseline's."""
    print("\nper-file missing lines (baseline -> now):")

    for name in sorted(set(missing) | set(baseline)):
        before, after = len(baseline.get(name, ())), len(missing.get(name, ()))

        if before != after:
            print(f"  {name}: {before} -> {after} ({after - before:+d})")

    before = sum(map(len, baseline.values()))
    after = sum(map(len, missing.values()))
    print(f"  total: {before} -> {after} ({after - before:+d})")


def main() -> int:
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument("--report", type=Path, help="reuse this JSON coverage report")
    parser.add_argument("--base", default="HEAD", help="diff base (default: HEAD)")
    parser.add_argument("--path", default="riko", help="tree to diff (default: riko)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--baseline-ref", help="run the suite on this ref to compare")
    group.add_argument("--baseline", type=Path, help="baseline JSON coverage report")
    args = parser.parse_args()
    root = Path(_git("rev-parse", "--show-toplevel").strip())
    os.chdir(root)

    with tempfile.TemporaryDirectory(prefix="diff-uncovered-") as tmp:
        folder = Path(tmp)
        if args.report is None:
            (folder / "now").mkdir()
            report = run_suite(root, folder / "now")
        else:
            report = args.report

        missing = load_missing(report)
        uncovered = print_uncovered(missing, load_changed_lines(args.base, args.path))

        if args.baseline_ref:
            (folder / "base").mkdir()
            print_drift(
                missing, load_missing(run_baseline(args.baseline_ref, folder / "base"))
            )
        elif args.baseline:
            print_drift(missing, load_missing(args.baseline))

    return int(uncovered > 0)


if __name__ == "__main__":
    sys.exit(main())
