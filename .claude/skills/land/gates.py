"""
Records which gates passed on which tree, so any session can skip a repeat.

Usage:
    python .claude/skills/land/gates.py fingerprint
    python .claude/skills/land/gates.py check GATE
    python .claude/skills/land/gates.py record GATE
    python .claude/skills/land/gates.py run GATE [--mutates] [--lock] -- CMD...
    python .claude/skills/land/gates.py summary GATE

A gate's marker is the content tree id of the working tree it passed on: every
tracked and untracked, non-ignored file as ``git write-tree`` would store it. It
ignores ``HEAD`` and the index, so committing, staging, rebasing, or switching
sessions keeps a marker valid while the content is unchanged; any edit
invalidates it. Markers live in ``.claude/gate-markers.json`` of each worktree.

``check`` exits 0 when the gate already passed on this tree (skip it) and 1 when
it must run. ``record`` marks it passed on the current tree. ``run`` does both
around a command: it skips a passed gate, otherwise runs the command and records
a pass only when the command succeeds and the tree id did not change during the
run (``--mutates`` records the tree the command left, for prettify and codegen).
``--lock`` takes a non-blocking OS lock on ``riko-gate.lock`` in the git common
directory, so every worktree of the repository shares it; when another session
holds it, ``run`` exits 75 at once instead of waiting. The OS releases the lock when
the process exits, so it never goes stale.

``run`` echoes the command's output and keeps its last pytest summary line
(``1851 passed, 62 xfailed in 70s``) in the marker; ``summary`` prints it with
whether the tree has changed since, so a later session can report the suite count
without rerunning it. It exits 1 when the gate has no recorded summary.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

DESCRIPTION = "Skip gates that already passed on the current tree."
GIT = shutil.which("git") or "git"
BUSY = 75
SUMMARY = re.compile(r"\b\d+ passed\b")


def _git(*args: str, env: dict[str, str] | None = None) -> str:
    return subprocess.run(
        [GIT, *args], check=True, capture_output=True, text=True, env=env
    ).stdout.strip()


def get_state_dir() -> Path:
    """Gets the worktree's ``.claude`` folder."""
    return Path(_git("rev-parse", "--show-toplevel")) / ".claude"


def get_lock_path() -> Path:
    """Gets the suite lock file, shared by every worktree of the repository."""
    common = _git("rev-parse", "--path-format=absolute", "--git-common-dir")
    return Path(common) / "riko-gate.lock"


def get_tree_id() -> str:
    """Gets the content tree id of the working tree, ignoring HEAD and the index."""
    index = Path(tempfile.mkdtemp(prefix="gates-")) / "index"
    real_index = Path(
        _git("rev-parse", "--path-format=absolute", "--git-path", "index")
    )

    if real_index.exists():
        shutil.copyfile(real_index, index)

    env = {**os.environ, "GIT_INDEX_FILE": str(index)}
    _git("add", "-A", env=env)
    return _git("write-tree", env=env)


def load_markers(path: Path) -> dict[str, dict[str, str]]:
    """Loads the gate markers, or none when the file is missing or unreadable."""
    try:
        markers = json.loads(path.read_text())
    except (OSError, ValueError):
        markers = {}

    return markers if isinstance(markers, dict) else {}


def write_marker(path: Path, gate: str, tree: str, summary: str | None = None) -> None:
    """Writes a pass marker for ``gate`` on ``tree``, with the run's summary line."""
    markers = load_markers(path)
    markers[gate] = {
        "tree": tree,
        "head": _git("rev-parse", "HEAD"),
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
    }

    if summary is not None:
        markers[gate]["summary"] = summary

    path.parent.mkdir(exist_ok=True)
    temp = path.with_name(f"{path.name}.{os.getpid()}")
    temp.write_text(json.dumps(markers, indent=2, sort_keys=True) + "\n")
    temp.replace(path)


def get_passed(path: Path, gate: str, tree: str) -> dict[str, str] | None:
    """Gets the gate's marker when it passed on ``tree``."""
    marker = load_markers(path).get(gate)
    return marker if marker is not None and marker.get("tree") == tree else None


def _skip_message(gate: str, marker: dict[str, str]) -> str:
    at, head = marker["at"], marker["head"][:8]
    return f"skip {gate}: passed on this tree at {at} (HEAD {head})"


def has_object(sha: str) -> bool:
    """Reports whether the repository still holds ``sha`` (git prunes loose trees)."""
    found = subprocess.run(
        [GIT, "cat-file", "-e", sha], capture_output=True, check=False
    )
    return found.returncode == 0


def check(path: Path, gate: str) -> int:
    """
    Prints whether ``gate`` can be skipped; exit code 0 means skip.

    When the tree it last passed on still exists, also prints the ``git diff`` that
    shows what changed since that pass.
    """
    tree = get_tree_id()
    marker = get_passed(path, gate, tree)
    last = load_markers(path).get(gate)

    if marker is not None:
        print(_skip_message(gate, marker))
    elif last is None:
        print(f"run {gate}: no marker")
    else:
        at, head = last["at"], last["head"][:8]
        print(f"run {gate}: tree changed since the pass at {at} (HEAD {head})")

        if has_object(last["tree"]):
            print(f"changed since: git diff {last['tree']} {tree}")

    return 0 if marker is not None else 1


def print_summary(path: Path, gate: str) -> int:
    """Prints the gate's last recorded summary line; exit code 1 means none."""
    marker = load_markers(path).get(gate)
    summary = None if marker is None else marker.get("summary")

    if marker is None or summary is None:
        print(f"no {gate} summary recorded")
    else:
        state = "current" if marker["tree"] == get_tree_id() else "tree changed since"
        print(f"{summary} ({state}; passed at {marker['at']})")

    return 0 if summary is not None else 1


def execute(command: list[str]) -> tuple[int, str | None]:
    """Runs ``command``, echoing its output, and returns its last summary line."""
    summary = None

    with subprocess.Popen(command, stdout=subprocess.PIPE, text=True) as process:
        for line in process.stdout or ():
            sys.stdout.write(line)

            if SUMMARY.search(line):
                summary = line.strip().strip("=").strip()

    return process.returncode, summary


def run(path: Path, gate: str, command: list[str], *, mutates: bool, lock: bool) -> int:
    """Runs ``command`` unless ``gate`` passed on this tree, recording a clean pass."""
    path.parent.mkdir(exist_ok=True)

    with open(get_lock_path(), "a") as handle:
        try:
            if lock:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(f"busy {gate}: another session holds the gate lock; rerun later")
            code = BUSY
        else:
            code = _run_unlocked(path, gate, command, mutates=mutates)

    return code


def _run_unlocked(path: Path, gate: str, command: list[str], *, mutates: bool) -> int:
    before = get_tree_id()
    marker = get_passed(path, gate, before)

    if marker is None:
        code, summary = execute(command)
        after = get_tree_id()

        if code == 0 and (mutates or after == before):
            write_marker(path, gate, after, summary)
            print(f"recorded {gate} on tree {after[:12]}")
        elif code == 0:
            print(f"not recorded {gate}: the tree changed during the run")
    else:
        print(_skip_message(gate, marker))
        code = 0

    return code


def main(argv: list[str] | None = None) -> int:
    """Parses the command line and runs the chosen subcommand."""
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("fingerprint", help="print the working tree's content tree id")

    for name in ("check", "record", "summary"):
        sub.add_parser(name).add_argument("gate")

    run_parser = sub.add_parser("run")
    run_parser.add_argument("gate")
    run_parser.add_argument("--mutates", action="store_true")
    run_parser.add_argument("--lock", action="store_true")
    argv = sys.argv[1:] if argv is None else argv
    split = argv.index("--") if "--" in argv else len(argv)
    args = parser.parse_args(argv[:split])
    path = get_state_dir() / "gate-markers.json"
    command = argv[split + 1 :]

    if args.action == "fingerprint":
        print(get_tree_id())
        code = 0
    elif args.action == "check":
        code = check(path, args.gate)
    elif args.action == "summary":
        code = print_summary(path, args.gate)
    elif args.action == "record":
        write_marker(path, args.gate, tree := get_tree_id())
        print(f"recorded {args.gate} on tree {tree[:12]}")
        code = 0
    elif command:
        code = run(path, args.gate, command, mutates=args.mutates, lock=args.lock)
    else:
        parser.error("run needs a command after --")

    return code


if __name__ == "__main__":
    sys.exit(main())
