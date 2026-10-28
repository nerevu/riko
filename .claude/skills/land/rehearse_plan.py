"""
Builds, checks, and rehearses a /land commit plan without touching the user's tree.

Usage: python .claude/skills/land/rehearse_plan.py PLAN [--out DIR] [-U N]
       [--full-checks] [--copy]

PLAN is a text file of steps, in order. A step starts with a header line and lists
the ids it takes (from ``split_hunks.py list``; ``path``, ``path:N``, ``path:N-M``):

    fixup 3c2a62bb
    uv.lock

    commit msgs/map-keys.txt     # message file, relative to PLAN
    riko/base/_iterutils.py:312
    riko/coercion/_objectify.py

    commit msgs/rest.txt
    *                            # every id no earlier step took

    skip                         # ids to leave uncommitted (scratch docs)
    _docs/scratch-notes.md

Each step's tree is ``HEAD`` plus the hunks of every step so far, built in a private
index and committed with ``git commit-tree`` (no hooks; the gates already ran). Then:

1. **Coverage**: every id is taken by exactly one step, so the last tree must equal
   the working tree; that equality is confirmed by tree hash.
2. **Build checks** per step, on an extracted copy of its tree: ruff's
   undefined/unused-name rules and ``import riko, riko.cli.manage``.
   ``--full-checks`` adds pyright on the step's Python files and
   ``manage lint imports --all`` (bisect-safe commits).
3. **Autosquash**: when there are fixups, a throwaway worktree replays
   ``rebase -i --autosquash`` from the oldest target and confirms the squashed tree.

Writes ``NN.patch``/``NN.msg`` per step plus ``commands.txt`` (one line per step,
always ``git reset -q`` first, so the chain never depends on what is staged when it
runs) and ``chain.txt`` (all steps joined with ``&&``) to ``--out`` (default: a new
temp folder). ``--copy`` puts the chain on the clipboard. Nothing is ever deleted;
temp folders are left for the OS.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from split_hunks import (
    GIT,
    TreeBuilder,
    expand,
    git,
    index_hunks,
    load_change,
    working_tree,
)

DESCRIPTION = "Build, check, and rehearse a /land commit plan."
RUFF_RULES = "F821,F401,F811"
IMPORT_SMOKE = "import riko, riko.cli.manage"
TAR = shutil.which("tar") or "tar"
PBCOPY = shutil.which("pbcopy")


@dataclass
class Step:
    kind: str
    arg: str
    entries: list[str] = field(default_factory=list)
    ids: list[str] = field(default_factory=list)
    commit: str = ""
    tree: str = ""
    message: str = ""


def read_plan(path: Path) -> list[Step]:
    steps: list[Step] = []

    for raw in path.read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        head, _, rest = line.partition(" ")

        if not line:
            continue
        elif head in {"fixup", "commit"} and rest:
            steps.append(Step(head, rest.strip()))
        elif line == "skip":
            steps.append(Step("skip", ""))
        elif not steps:
            sys.exit(f"selection before any step header: {line}")
        else:
            steps[-1].entries.append(line)

    return steps


def assign(steps: list[Step], files: list) -> None:
    """Expands every step's entries, enforcing that each id is taken exactly once."""
    every = list(index_hunks(files))
    owner: dict[str, int] = {}

    for n, step in enumerate(steps):
        explicit = [e for e in step.entries if e != "*"]

        for hid in (i for e in explicit for i in expand(e, files)):
            if hid in owner:
                sys.exit(f"{hid} is taken by steps {owner[hid] + 1} and {n + 1}")

            owner[hid] = n
            step.ids.append(hid)

    rest = [n for n, s in enumerate(steps) if "*" in s.entries]

    if len(rest) > 1:
        sys.exit("only one step may take the rest (*)")
    elif rest:
        leftover = [h for h in every if h not in owner]
        steps[rest[0]].ids.extend(leftover)
        owner.update(dict.fromkeys(leftover, rest[0]))

    if missing := [h for h in every if h not in owner]:
        shown = ", ".join(missing[:8]) + (" ..." if len(missing) > 8 else "")
        sys.exit(f"{len(missing)} ids are in no step: {shown}")

    if empty := [n + 1 for n, s in enumerate(steps) if not s.ids]:
        sys.exit(f"steps with nothing to commit: {empty}")


def build_commits(steps: list[Step], files: list, plan_dir: Path) -> None:
    builder = TreeBuilder(files)
    parent = git("rev-parse", "HEAD").strip()
    selected: set[str] = set()

    for step in steps:
        selected.update(step.ids)

        if step.kind == "fixup":
            subject = git("log", "-1", "--format=%s", step.arg).strip()
            step.message = f"fixup! {subject}\n"
        else:
            step.message = (plan_dir / step.arg).read_text()

        step.tree = builder.tree(selected)
        args = ("commit-tree", step.tree, "-p", parent, "-F", "-")
        step.commit = git(*args, data=step.message.encode()).strip()
        parent = step.commit


def changed_py(step: Step, parent: str) -> list[str]:
    names = git("diff", "--name-only", "--diff-filter=AMR", parent, step.commit)
    return [n for n in names.split() if n.endswith(".py")]


def check(step: Step, parent: str, *, full: bool) -> str:
    """Runs the build checks on an extracted copy of the step's tree."""
    root = Path(tempfile.mkdtemp(prefix="plan-check-"))
    archive = subprocess.run(
        (GIT, "archive", step.commit), capture_output=True, check=True
    )
    subprocess.run((TAR, "-x", "-C", root), input=archive.stdout, check=True)
    env = {**os.environ, "PYTHONPATH": str(root)}
    py = sys.executable
    commands = [
        (
            "ruff",
            (
                py,
                "-m",
                "ruff",
                "check",
                "--no-cache",
                "-q",
                "--select",
                RUFF_RULES,
                "riko",
            ),
        ),
        ("import", (py, "-c", IMPORT_SMOKE)),
    ]

    if full:
        commands.append(
            ("imports", (py, "-m", "riko.cli.manage", "lint", "imports", "--all"))
        )

        if files := changed_py(step, parent):
            pyright = Path(py).parent / "pyright"
            commands.append(("pyright", (str(pyright), *files)))

    failures = []

    for label, command in commands:
        run = subprocess.run(
            command, cwd=root, env=env, capture_output=True, text=True, check=False
        )

        if run.returncode:
            tail = (run.stdout + run.stderr).strip().splitlines()[-3:]
            failures.append(f"{label}: {' | '.join(tail)}")

    return "; ".join(failures) or "ok"


def oldest(shas: list[str]) -> str:
    order = git("rev-list", "--topo-order", "HEAD").split()
    full = [git("rev-parse", s).strip() for s in shas]
    return max(full, key=order.index)


def rehearse_autosquash(steps: list[Step]) -> str:
    targets = [s.arg for s in steps if s.kind == "fixup"]
    result = "no fixups"

    if targets:
        worktree = Path(tempfile.mkdtemp(prefix="plan-squash-")) / "wt"
        git("worktree", "add", "-q", "--detach", str(worktree), steps[-1].commit)
        env = {**os.environ, "GIT_SEQUENCE_EDITOR": ":"}
        rebase = subprocess.run(
            (GIT, "rebase", "-q", "-i", "--autosquash", f"{oldest(targets)}~1"),
            cwd=worktree,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        squashed = subprocess.run(
            (GIT, "rev-parse", "HEAD^{tree}"),
            cwd=worktree,
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()

        if rebase.returncode:
            result = f"CONFLICT ({rebase.stderr.strip()[:120]}); worktree {worktree}"
        elif squashed != steps[-1].tree:
            result = f"squashed tree differs; worktree {worktree}"
        else:
            result = "ok"

    return result


def split_id(hid: str) -> tuple[str, str]:
    path, sep, line = hid.rpartition(":")
    return (path, line) if sep and line.isdigit() else (hid, "")


def describe_files(step: Step, parent: str, hunks: dict[str, set[str]]) -> list[str]:
    """Lists the step's files with line counts, and hunk lines when it takes part."""
    taken: dict[str, set[str]] = {}

    for hid in step.ids:
        path, line = split_id(hid)
        taken.setdefault(path, set()).add(line)

    lines = []

    for row in git("diff", "--numstat", parent, step.commit).splitlines():
        added, removed, path = row.split("\t", 2)
        counts = "binary" if added == "-" else f"+{added}/-{removed}"
        mine = taken.get(path, set())
        partial = mine and mine != hunks.get(path, set()) and "" not in mine
        shown = sorted(mine, key=int) if partial else []
        label = "line" if len(shown) == 1 else "lines"
        where = f"  ({label} {', '.join(shown)})" if shown else ""
        lines.append(f"      {path}  {counts}{where}")

    return lines


def write_outputs(
    steps: list[Step], out: Path, files: list
) -> list[tuple[str, list[str]]]:
    out.mkdir(parents=True, exist_ok=True)
    lines = ["git reset -q"]
    parent = git("rev-parse", "HEAD").strip()
    hunks: dict[str, set[str]] = {}
    rows = []

    for hid in index_hunks(files):
        path, line = split_id(hid)
        hunks.setdefault(path, set()).add(line)

    for n, step in enumerate(steps, 1):
        patch, msg = out / f"{n:02}.patch", out / f"{n:02}.msg"
        patch.write_text(git("diff", "--binary", parent, step.commit))
        msg.write_text(step.message)
        commit = (
            f"git commit -q --fixup={step.arg}"
            if step.kind == "fixup"
            else f"git commit -q -F {msg}"
        )
        lines.append(f"git apply --cached {patch} && {commit}")
        header = f"{n:02}  {step.message.splitlines()[0][:60]:<60}"
        rows.append((header, describe_files(step, parent, hunks)))
        parent = step.commit

    (out / "commands.txt").write_text("\n".join(lines) + "\n")
    (out / "chain.txt").write_text(" && ".join(lines))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--out", type=Path, help="output folder (default: temp)")
    parser.add_argument("-U", type=int, default=0, dest="context", help="diff context")
    parser.add_argument("--full-checks", action="store_true", help="pyright + imports")
    parser.add_argument("--copy", action="store_true", help="pbcopy the chain")
    args = parser.parse_args()

    out = args.out or Path(tempfile.mkdtemp(prefix="plan-out-"))
    files = load_change(args.context)
    steps = read_plan(args.plan)
    assign(steps, files)
    skipped = [s for s in steps if s.kind == "skip"]
    steps = [s for s in steps if s.kind != "skip"]
    build_commits(steps, files, args.plan.parent)
    final_tree = working_tree()

    left_out = {i.split(":")[0] for s in skipped for i in s.ids}
    stray = set(git("diff", "--name-only", steps[-1].tree, final_tree).split())

    if stray != left_out and not stray < left_out:
        sys.exit(f"final tree differs from the working tree outside skip: {stray}")

    parents = [git("rev-parse", "HEAD").strip(), *(s.commit for s in steps[:-1])]

    with ThreadPoolExecutor(max_workers=4) as pool:
        checks = list(
            pool.map(
                lambda pair: check(pair[0], pair[1], full=args.full_checks),
                zip(steps, parents, strict=True),
            )
        )

    squash = rehearse_autosquash(steps)
    rows = write_outputs(steps, out, files)

    for (header, details), result in zip(rows, checks, strict=True):
        print(f"{header}  check: {result}")
        print("\n".join(details))

    kept = f"; left uncommitted: {', '.join(sorted(left_out))}" if left_out else ""
    print(f"\ncoverage: every id in exactly one step{kept}")
    print(f"autosquash: {squash}")
    print(f"outputs: {out}/ (NN.patch, NN.msg, commands.txt, chain.txt)")

    if args.copy and PBCOPY:
        subprocess.run((PBCOPY,), input=(out / "chain.txt").read_bytes(), check=True)
        print("chain copied to the clipboard")

    failed = any(c != "ok" for c in checks) or squash not in {"ok", "no fixups"}
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
