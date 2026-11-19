"""
Records which gates passed on which tree, so any session can skip a repeat.

Usage:
    python .claude/skills/land/gates.py fingerprint
    python .claude/skills/land/gates.py check GATE
    python .claude/skills/land/gates.py scope GATE [--max-inline BYTES] [--edits-only]
    python .claude/skills/land/gates.py scope tidy --leads [--manage CMD]
    python .claude/skills/land/gates.py record GATE
    python .claude/skills/land/gates.py run GATE [--mutates] [--lock] -- CMD...
    python .claude/skills/land/gates.py summary GATE
    python .claude/skills/land/gates.py all [--codegen | --read-only] [--manage CMD]

A gate's marker is the content tree id of the working tree it passed on: every
tracked and untracked, non-ignored file as ``git write-tree`` would store it, minus
what that gate never reads. Tidy, ``lint``, and ``prettify`` (Ruff and rumdl) read
everything. ``check-types`` and ``verify-types`` (pyright) keep only ``*.py``,
``*.pyi``, ``pyproject.toml``, ``uv.lock``, and ``typings/`` outside ``.claude/``.
``test`` and ``uncovered`` leave out ``.claude/``, ``_docs/``, ``.github/``, and the
root ``*.md`` files (``docs/`` and ``README.rst`` hold doctests, so they stay). Every
other gate, codegen included (it rewrites generated blocks in ``_docs/`` and
``CLAUDE.md``), leaves out ``.claude/`` alone. So a skill edit reruns tidy, lint, and
prettify alone, and a prose edit does not rerun pyright. It ignores
``HEAD`` and the index, so committing, staging, rebasing, or switching sessions
keeps a marker valid while the content is unchanged; any other edit invalidates
it. Markers live in ``.claude/gate-markers.json`` of each worktree.
``fingerprint`` prints the full tree id.

``check`` exits 0 when the gate already passed on this tree (skip it) and 1 when
it must run. ``record`` marks it passed on the current tree. ``run`` does both
around a command: it skips a passed gate, otherwise runs the command and records
a pass only when the command succeeds and the tree id did not change during the
run (``--mutates`` records the tree the command left, for prettify and codegen). The
one change a non-mutating run may make is the coverage ratchet lowering a ceiling:
when every changed line is a ``<key> = <count>`` or ``<key> = <date>`` line of
``pyproject.toml``, ``run`` records the tree the run left. A prettify pass that
runs and is recorded carries tidy's mark to the tree it leaves when tidy was marked
on the tree it started from; a skipped prettify never touches tidy's marker.
``--lock`` takes a non-blocking OS lock on ``riko-gate.lock`` in the git common
directory, so every worktree of the repository shares it; when another session
holds it, ``run`` exits 75 at once instead of waiting. The OS releases the lock when
the process exits, so it never goes stale.

``scope`` resolves what a gate still has to look at, in one call: the base it
diffs from (the tree it last passed on when git still holds it, else the marker's
``HEAD`` when that is an ancestor, else the parent of the oldest unpushed commit,
else ``HEAD``), the ``--stat``, the untracked files, and the diff itself against the
current content tree, so untracked files are inside it. ``uv.lock`` and the
generated files are left out. A diff over ``--max-inline`` bytes (default 25000)
goes to ``.claude/<gate>-scope.diff`` instead, to be read in slices. It exits 0
when the gate already passed on this tree, 2 when the scope is empty, 1 otherwise.
``--edits-only`` prints, in place of the diff, each added line whose text no removed
line carries (``path:line: text``): a change that mostly moves code shrinks to its
real edits.

``scope tidy --leads`` adds tidy's opening checks to the same call. It saves the
raw diff to ``.claude/tidy-scope.diff`` and runs, side by side, the tidy lint
selectors (``--manage`` plus ``lint --terms --literals --docstrings --bindings
--tests``), ``neighborhood.py --context 2``, and ``mistake_scan.py`` over that diff,
plus ``heading_drift.py`` when a ``*.md`` file is touched, ``changelog_widows.py``
when ``docs/CHANGES.rst`` is, and ``overlap_scan.py --files`` over each touched
``tests/<tier>/test_*.py``. Each prints whole under its own ``--- <name>`` header
(with its exit code when non-zero), in that order, after the scope. A diff over
``--max-inline`` bytes first gets a hint to read ``--edits-only``. The exit code
stays the scope's.

``run`` echoes the command's output and keeps its last pytest summary line
(``1851 passed, 62 xfailed in 70s``) in the marker; ``summary`` prints it with
whether the tree has changed since, so a later session can report the suite count
without rerunning it. It exits 1 when the gate has no recorded summary.

``all`` runs ``/land``'s gates through ``run`` in three steps, in the foreground.
First prettify (which carries tidy's mark to the tree it leaves when tidy was marked
on the tree it started from) and, with
``--codegen``, codegen, one at a time. Then lint, check-types, and verify-types side
by side; each gate's output is held back and printed whole under a ``--- <gate>``
header when it finishes. Last the suite (locked), alone, and only when every earlier
gate passed and was recorded. Each command is ``--manage`` (default ``uv run
--active python -m riko.cli.manage``) plus the gate's arguments. It stops after the
first step with a gate that fails, is busy, or passes unrecorded (gates already
running in the same step finish), exits with the first such gate's code in gate
order, and ends with one line per gate: ``skip``, ``pass``, ``pass (unrecorded)``,
``fail (<code>)``, ``busy``, or ``not run``. ``--read-only`` runs the side-by-side
step alone (lint and both type gates), so it never writes the tree; the other gates
report ``not run``.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple, TextIO

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

DESCRIPTION = "Skip gates that already passed on the current tree."
GIT = shutil.which("git") or "git"
BUSY = 75
UNRECORDED = 1
EMPTY = 2
MAX_INLINE = 25_000
SUMMARY = re.compile(r"\b\d+ passed\b")
HUNK_START = re.compile(r"^@@ -\S+ \+(\d+)")
RATCHET_LINE = re.compile(r"^([-+])uncovered(-lowered)? = (\d+|\d{4}-\d{2}-\d{2})\s*$")
RATCHET_FILE = "pyproject.toml"
MARKER_LOCK = threading.Lock()
SKILLS = (".claude",)
TYPE_UNREAD = (".", ":!*.py", ":!*.pyi", ":!pyproject.toml", ":!uv.lock", ":!typings")
SUITE_UNREAD = (".claude", "_docs", ".github", ":(glob)*.md")
DEFAULT_UNREAD = (SKILLS,)
UNREAD: dict[str | None, tuple[tuple[str, ...], ...]] = {
    None: (),
    "tidy": (),
    "lint": (),
    "prettify": (),
    "test": (SUITE_UNREAD,),
    "uncovered": (SUITE_UNREAD,),
    "check-types": (SKILLS, TYPE_UNREAD),
    "verify-types": (SKILLS, TYPE_UNREAD),
}
SCOPE_EXCLUDES = (
    "uv.lock",
    "riko/coercion/_configs.py",
    "riko/modules/_names.py",
    "riko/types/_module_ids.py",
)
MANAGE = "uv run --active python -m riko.cli.manage"
CARRIER = "prettify"
TIDY_DIR = Path(__file__).resolve().parent.parent / "tidy"
TIDY_LINT = ("lint", "--terms", "--literals", "--docstrings", "--bindings", "--tests")
TEST_FILE = re.compile(r"^tests/[^/]+/test_[^/]*\.py$")
CHANGELOG = "docs/CHANGES.rst"
LEAD_NAMES = (
    "lint",
    "neighborhood",
    "mistake_scan",
    "heading_drift",
    "changelog_widows",
    "overlap_scan",
)
GATE_SEQUENCE = (
    ("prettify", ("prettify",), True, False),
    ("codegen", ("codegen", "--all"), True, False),
    ("lint", ("lint", "--all"), False, False),
    ("check-types", ("lint", "--check-types"), False, False),
    ("verify-types", ("lint", "--verify-types"), False, False),
    ("test", ("test", "--ratchet", "--quiet", "--parallel"), False, True),
)


class Outcome(NamedTuple):
    """A gate run's exit code, whether it skipped, and whether its pass is recorded."""

    code: int
    skipped: bool
    recorded: bool
    tree: str | None

    @property
    def exit_code(self) -> int:
        """The code ``all`` stops on: a pass left unrecorded counts as failed."""
        return UNRECORDED if self.code == 0 and not self.recorded else self.code


def _git(*args: str, env: dict[str, str] | None = None) -> str:
    return subprocess.run(
        [GIT, *args],
        check=True,
        capture_output=True,
        text=True,
        errors="replace",
        env=env,
    ).stdout.strip()


def get_state_dir() -> Path:
    """Gets the worktree's ``.claude`` folder."""
    return Path(_git("rev-parse", "--show-toplevel")) / ".claude"


def get_lock_path() -> Path:
    """Gets the suite lock file, shared by every worktree of the repository."""
    common = _git("rev-parse", "--path-format=absolute", "--git-common-dir")
    return Path(common) / "riko-gate.lock"


def get_tree_id(gate: str | None = None) -> str:
    """
    Gets the content tree id of the working tree, ignoring HEAD and the index.

    The id leaves out what ``gate`` never reads (``UNREAD``): nothing for tidy and
    the Ruff/rumdl gates, ``.claude/`` for most others, and more for the suite and
    the pyright gates.
    """
    real_index = Path(
        _git("rev-parse", "--path-format=absolute", "--git-path", "index")
    )

    with tempfile.TemporaryDirectory(prefix="gates-") as tmp:
        index = Path(tmp) / "index"

        if real_index.exists():
            shutil.copy2(real_index, index)

        env = {**os.environ, "GIT_INDEX_FILE": str(index)}
        _git("add", "-A", env=env)

        for pathspecs in UNREAD.get(gate, DEFAULT_UNREAD):
            _git(
                "rm",
                "-r",
                "-q",
                "--cached",
                "--ignore-unmatch",
                "--",
                *pathspecs,
                env=env,
            )

        tree = _git("write-tree", env=env)

    return tree


def load_markers(path: Path) -> dict[str, dict[str, str]]:
    """Loads the gate markers, or none when the file is missing or unreadable."""
    try:
        markers = json.loads(path.read_text())
    except (OSError, ValueError):
        markers = {}

    return markers if isinstance(markers, dict) else {}


def write_marker(path: Path, gate: str, tree: str, summary: str | None = None) -> None:
    """Writes a pass marker for ``gate`` on ``tree``, with the run's summary line."""
    head = _git("rev-parse", "HEAD")

    with MARKER_LOCK:
        markers = load_markers(path)
        markers[gate] = {
            "tree": tree,
            "head": head,
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
    tree = get_tree_id(gate)
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


def is_ancestor(sha: str) -> bool:
    """Reports whether ``sha`` is an ancestor of ``HEAD``."""
    found = subprocess.run(
        [GIT, "merge-base", "--is-ancestor", sha, "HEAD"],
        capture_output=True,
        check=False,
    )
    return found.returncode == 0


def resolve_base(marker: dict[str, str] | None) -> tuple[str, str]:
    """Resolves the tree-ish a gate's scope diffs from, with the case that chose it."""
    unpushed = _git("log", "HEAD", "--not", "--remotes", "--format=%H").split()

    if marker is not None and has_object(marker["tree"]):
        base, case = marker["tree"], f"edits since the pass at {marker['at']}"
    elif marker is not None and is_ancestor(marker["head"]):
        base, case = (
            marker["head"],
            f"commits and edits since HEAD {marker['head'][:8]}",
        )
    elif unpushed and has_object(f"{unpushed[-1]}^"):
        base, case = (
            f"{unpushed[-1]}^",
            f"{len(unpushed)} unpushed commits and the working tree",
        )
    else:
        base, case = "HEAD", "the working tree"

    return base, case


def gen_edits(diff: str) -> Iterator[str]:
    """Generates each added line no removed line carries, as ``path:line: text``."""
    lines = diff.splitlines()
    removed = Counter(
        line[1:].strip()
        for line in lines
        if line.startswith("-") and not line.startswith("---")
    )
    current, lineno = None, 0

    for line in lines:
        if line.startswith("+++ "):
            current = line[6:] if line.startswith("+++ b/") else None
        elif line.startswith("@@"):
            start = HUNK_START.search(line)
            lineno = 0 if start is None else int(start[1]) - 1
        elif not line.startswith("-"):
            lineno += 1
            text = line[1:].strip()

            if not line.startswith("+") or current is None or not text:
                pass
            elif removed[text] > 0:
                removed[text] -= 1
            else:
                yield f"{current}:{lineno}: {line[1:]}"


def build_lead_prefixes(manage: list[str]) -> dict[str, list[str]]:
    """Builds the default command prefix of each ``--leads`` check."""
    python = [sys.executable]
    return {
        "lint": manage,
        "neighborhood": python,
        "mistake_scan": ["uv", "run", "--active", "--no-sync", "python"],
        "heading_drift": python,
        "changelog_widows": python,
        "overlap_scan": python,
    }


def build_lead_commands(
    prefixes: Mapping[str, list[str]], diff_file: Path, base: str, touched: list[str]
) -> dict[str, list[str]]:
    """Builds the command of each lead that applies to the ``touched`` paths."""
    tests = [name for name in touched if TEST_FILE.match(name)]
    script = {name: str(TIDY_DIR / f"{name}.py") for name in LEAD_NAMES}
    commands = {
        "lint": [*prefixes["lint"], *TIDY_LINT],
        "neighborhood": [
            *prefixes["neighborhood"],
            script["neighborhood"],
            "--diff-file",
            str(diff_file),
            "--context",
            "2",
        ],
        "mistake_scan": [
            *prefixes["mistake_scan"],
            script["mistake_scan"],
            "--diff-file",
            str(diff_file),
        ],
    }

    if any(name.endswith(".md") for name in touched):
        commands["heading_drift"] = [
            *prefixes["heading_drift"],
            script["heading_drift"],
            base,
        ]

    if CHANGELOG in touched:
        commands["changelog_widows"] = [
            *prefixes["changelog_widows"],
            script["changelog_widows"],
        ]

    if tests:
        commands["overlap_scan"] = [
            *prefixes["overlap_scan"],
            script["overlap_scan"],
            "--files",
            *tests,
        ]

    return commands


def _run_captured(command: list[str]) -> tuple[int, str]:
    found = subprocess.run(
        command, capture_output=True, text=True, errors="replace", check=False
    )
    return found.returncode, found.stdout + found.stderr


def run_leads(commands: Mapping[str, list[str]]) -> None:
    """Runs the lead ``commands`` side by side, printing each whole in table order."""
    with ThreadPoolExecutor(max(len(commands), 1)) as pool:
        futures = {
            name: pool.submit(_run_captured, command)
            for name, command in commands.items()
        }

    for name in LEAD_NAMES:
        if name in futures:
            code, output = futures[name].result()
            status = f" (exit {code})" if code else ""
            text = output.rstrip("\n") or "(no output)"
            print(f"--- {name}{status}\n{text}", flush=True)


def scope(
    path: Path,
    gate: str,
    max_inline: int = MAX_INLINE,
    *,
    edits_only: bool = False,
    leads: Mapping[str, list[str]] | None = None,
) -> int:
    """
    Prints everything ``gate`` still has to look at; exit 0 skips, 2 means empty.

    The diff runs from the resolved base to the current content tree, so untracked
    files are part of it; a diff over ``max_inline`` bytes is written to
    ``.claude/<gate>-scope.diff`` instead of printed. With ``leads`` (each lead's
    command prefix), a non-empty scope also runs tidy's opening checks over the
    diff and prints each one's output after it.
    """
    tree = get_tree_id(gate)
    marker = get_passed(path, gate, tree)
    last = load_markers(path).get(gate)

    if marker is not None:
        print(_skip_message(gate, marker))
        code = 0
    else:
        base, case = resolve_base(last)
        pathspec = ["--", ".", *(f":!{exclude}" for exclude in SCOPE_EXCLUDES)]
        stat = _git("diff", "--stat", base, tree, *pathspec)
        diff = _git("diff", base, tree, *pathspec)
        untracked = _git("ls-files", "--others", "--exclude-standard")
        shown = "\n".join(gen_edits(diff)) if edits_only else diff
        label = "edits" if edits_only else "diff"
        print(f"scope {gate}: {case}")
        print(f"base: {base}")

        if leads is not None and not edits_only and len(diff) > max_inline:
            print(
                f"diff of {len(diff.splitlines())} lines is over {max_inline} bytes: "
                f"read `gates.py scope {gate} --edits-only` first"
            )

        print(f"--- stat\n{stat or '(none)'}")
        print(f"--- untracked\n{untracked or '(none)'}")

        if not diff:
            print(f"--- diff\n(empty: record {gate} and stop)")
            code = EMPTY
        elif len(shown) > max_inline:
            target = path.with_name(f"{gate}-scope.{label}")
            target.parent.mkdir(exist_ok=True)
            target.write_text(shown + "\n")
            print(
                f"--- {label} ({len(shown)} bytes) written to {target}; "
                "read it in slices"
            )
            code = 1
        else:
            print(f"--- {label} ({len(shown)} bytes)\n{shown}")
            code = 1

        if leads is not None and diff:
            diff_file = path.with_name(f"{gate}-scope.diff")
            diff_file.parent.mkdir(exist_ok=True)
            diff_file.write_text(diff + "\n")
            touched = _git("diff", "--name-only", base, tree, *pathspec).splitlines()
            run_leads(build_lead_commands(leads, diff_file, base, touched))

    return code


def print_summary(path: Path, gate: str) -> int:
    """Prints the gate's last recorded summary line; exit code 1 means none."""
    marker = load_markers(path).get(gate)
    summary = None if marker is None else marker.get("summary")

    if marker is None or summary is None:
        print(f"no {gate} summary recorded")
    else:
        state = (
            "current" if marker["tree"] == get_tree_id(gate) else "tree changed since"
        )
        print(f"{summary} ({state}; passed at {marker['at']})")

    return 0 if summary is not None else 1


def is_ratchet_change(before: str, after: str) -> bool:
    """
    Reports whether ``before`` to ``after`` only lowers the coverage-ratchet ceiling.

    That is, ``pyproject.toml`` is the only changed file, every changed line is the
    ``uncovered = <count>`` or ``uncovered-lowered = <date>`` line the ratchet writes,
    and a replaced count went down.
    """
    names = _git("diff", "--name-only", before, after).splitlines()
    lines = [
        line
        for line in _git("diff", "--unified=0", before, after).splitlines()
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    ]
    matches = [RATCHET_LINE.match(line) for line in lines]
    counts = {
        match[1]: int(match[3]) for match in matches if match and match[2] is None
    }
    lowered = "-" not in counts or "+" not in counts or counts["+"] < counts["-"]
    return names == [RATCHET_FILE] and None not in matches and lowered


def execute(command: list[str], out: TextIO | None = None) -> tuple[int, str | None]:
    """
    Runs ``command``, echoing its output, and returns its last summary line.

    The output streams to stdout, or goes with stderr into ``out`` when given.
    """
    summary = None
    sink = sys.stdout if out is None else out
    stderr = None if out is None else subprocess.STDOUT

    with subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=stderr, text=True
    ) as process:
        for line in process.stdout or ():
            sink.write(line)

            if SUMMARY.search(line):
                summary = line.strip().strip("=").strip()

    return process.returncode, summary


def run(path: Path, gate: str, command: list[str], *, mutates: bool, lock: bool) -> int:
    """Runs ``command`` unless ``gate`` passed on this tree, recording a clean pass."""
    return run_gate(path, gate, command, mutates=mutates, lock=lock).code


def run_gate(
    path: Path,
    gate: str,
    command: list[str],
    *,
    mutates: bool,
    lock: bool,
    out: TextIO | None = None,
) -> Outcome:
    """Runs ``gate`` as ``run`` does, writing to ``out``, and returns its outcome."""
    path.parent.mkdir(exist_ok=True)

    with open(get_lock_path(), "a") as handle:
        try:
            if lock:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(
                f"busy {gate}: another session holds the gate lock; rerun later",
                file=out,
            )
            outcome = Outcome(BUSY, skipped=False, recorded=False, tree=None)
        else:
            outcome = _run_unlocked(path, gate, command, mutates=mutates, out=out)

    return outcome


def _run_unlocked(
    path: Path, gate: str, command: list[str], *, mutates: bool, out: TextIO | None
) -> Outcome:
    before = get_tree_id(gate)
    marker = get_passed(path, gate, before)

    if marker is None:
        tidied = (
            get_passed(path, "tidy", get_tree_id("tidy")) if gate == CARRIER else None
        )
        carry = tidied is not None
        code, summary = execute(command, out)
        after = get_tree_id(gate)
        changed = after != before and not mutates
        ratcheted = code == 0 and changed and is_ratchet_change(before, after)
        recorded = code == 0 and (not changed or ratcheted)

        if recorded:
            write_marker(path, gate, after, summary)
            note = " (ratchet lowered a ceiling)" if ratcheted else ""
            print(f"recorded {gate} on tree {after[:12]}{note}", file=out)

        if recorded and carry:
            write_marker(path, "tidy", tidy := get_tree_id("tidy"))
            print(f"recorded tidy on tree {tidy[:12]}", file=out)
        elif code == 0 and not recorded:
            print(f"not recorded {gate}: the tree changed during the run", file=out)

        outcome = Outcome(code, skipped=False, recorded=recorded, tree=after)
    else:
        print(_skip_message(gate, marker), file=out)
        outcome = Outcome(0, skipped=True, recorded=True, tree=before)

    return outcome


def _get_status(outcome: Outcome) -> str:
    if outcome.code == BUSY:
        status = "busy"
    elif outcome.code != 0:
        status = f"fail ({outcome.code})"
    elif not outcome.recorded:
        status = "pass (unrecorded)"
    else:
        status = "skip" if outcome.skipped else "pass"

    return status


def _run_buffered(
    path: Path, gate: str, command: list[str], *, mutates: bool, lock: bool
) -> tuple[Outcome, str]:
    out = StringIO()
    outcome = run_gate(path, gate, command, mutates=mutates, lock=lock, out=out)
    return outcome, out.getvalue()


def run_side_by_side(
    path: Path,
    manage: list[str],
    entries: list[tuple[str, tuple[str, ...], bool, bool]],
) -> dict[str, Outcome]:
    """
    Runs the gates in ``entries`` at once, printing each one's output when it ends.

    Returns each gate's outcome in ``entries`` order.
    """
    with ThreadPoolExecutor(max(len(entries), 1)) as pool:
        futures = {
            pool.submit(
                _run_buffered, path, gate, [*manage, *args], mutates=mutates, lock=lock
            ): gate
            for gate, args, mutates, lock in entries
        }

        for future in as_completed(futures):
            print(f"--- {futures[future]}\n{future.result()[1]}", end="", flush=True)

    results = {gate: future.result()[0] for future, gate in futures.items()}
    return {gate: results[gate] for gate, *_ in entries}


def run_in_turn(
    path: Path,
    manage: list[str],
    entries: list[tuple[str, tuple[str, ...], bool, bool]],
) -> dict[str, Outcome]:
    """
    Runs the gates in ``entries`` one at a time, stopping after the first one to stop.

    Prettify carries tidy's mark to the tree it leaves when tidy was marked on the
    tree it started from.
    """
    outcomes: dict[str, Outcome] = {}

    for gate, args, mutates, lock in entries:
        if all(outcome.exit_code == 0 for outcome in outcomes.values()):
            outcome = run_gate(path, gate, [*manage, *args], mutates=mutates, lock=lock)
            outcomes[gate] = outcome

    return outcomes


def run_all(
    path: Path, manage: list[str], *, codegen: bool, read_only: bool = False
) -> int:
    """
    Runs ``/land``'s gates through ``run`` in three steps, stopping after a failure.

    The mutating gates run first, one at a time; then the read-only gates side by
    side; then the locked suite alone. A gate that exits 0 without a recorded pass
    (the tree changed during its run) stops the sequence too. ``read_only`` runs the
    side-by-side step alone. Prints one status line per gate at the end and returns
    the first stopping gate's exit code, else 0.
    """
    selected = [entry for entry in GATE_SEQUENCE if codegen or entry[0] != "codegen"]
    checks = [entry for entry in selected if not entry[2] and not entry[3]]
    steps = (
        (run_in_turn, [entry for entry in selected if entry[2]]),
        (run_side_by_side, checks),
        (run_in_turn, [entry for entry in selected if entry[3]]),
    )
    chosen = steps[1:2] if read_only else steps
    outcomes: dict[str, Outcome] = {}

    for runner, entries in chosen:
        if all(outcome.exit_code == 0 for outcome in outcomes.values()):
            outcomes.update(runner(path, manage, entries))

    print("--- gates")

    for gate, *_ in selected:
        status = _get_status(outcomes[gate]) if gate in outcomes else "not run"
        print(f"{status} {gate}")

    codes = (outcome.exit_code for outcome in outcomes.values())
    return next((code for code in codes if code != 0), 0)


def main(argv: list[str] | None = None) -> int:
    """Parses the command line and runs the chosen subcommand."""
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("fingerprint", help="print the working tree's content tree id")

    for name in ("check", "record", "summary"):
        sub.add_parser(name).add_argument("gate")

    scope_parser = sub.add_parser("scope")
    scope_parser.add_argument("gate")
    scope_parser.add_argument("--max-inline", type=int, default=MAX_INLINE)
    scope_parser.add_argument("--edits-only", action="store_true")
    scope_parser.add_argument(
        "--leads",
        action="store_true",
        help="also run tidy's opening checks over the diff (tidy only)",
    )
    scope_parser.add_argument(
        "--manage",
        default=MANAGE,
        help=f"the manage command the lint lead runs (default: {MANAGE})",
    )
    run_parser = sub.add_parser("run")
    run_parser.add_argument("gate")
    run_parser.add_argument("--mutates", action="store_true")
    run_parser.add_argument("--lock", action="store_true")
    all_parser = sub.add_parser(
        "all", help="run /land's gates in order, stopping at the first failure"
    )
    all_parser.add_argument(
        "--codegen", action="store_true", help="also run codegen after prettify"
    )
    all_parser.add_argument(
        "--manage",
        default=MANAGE,
        help=f"the manage command each gate runs (default: {MANAGE})",
    )
    all_parser.add_argument(
        "--read-only",
        action="store_true",
        help="run only lint and the type gates, side by side",
    )
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
    elif args.action == "scope" and args.leads and args.gate != "tidy":
        parser.error("--leads applies to the tidy gate only")
    elif args.action == "scope":
        prefixes = build_lead_prefixes(shlex.split(args.manage))
        code = scope(
            path,
            args.gate,
            args.max_inline,
            edits_only=args.edits_only,
            leads=prefixes if args.leads else None,
        )
    elif args.action == "summary":
        code = print_summary(path, args.gate)
    elif args.action == "record":
        write_marker(path, args.gate, tree := get_tree_id(args.gate))
        print(f"recorded {args.gate} on tree {tree[:12]}")
        code = 0
    elif args.action == "all" and args.read_only and args.codegen:
        parser.error("--read-only cannot run codegen, which writes the tree")
    elif args.action == "all":
        code = run_all(
            path,
            shlex.split(args.manage),
            codegen=args.codegen,
            read_only=args.read_only,
        )
    elif command:
        code = run(path, args.gate, command, mutates=args.mutates, lock=args.lock)
    else:
        parser.error("run needs a command after --")

    return code


if __name__ == "__main__":
    sys.exit(main())
