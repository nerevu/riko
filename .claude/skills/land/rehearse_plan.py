"""
Builds, checks, and rehearses a /land commit plan without touching the user's tree.

Usage: python .claude/skills/land/rehearse_plan.py PLAN [--out DIR] [-U N]
       [--full-checks] [--tests] [--copy]

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
   ``--full-checks`` adds, on a git-initialized copy (several lints call
   ``git ls-files``), ``manage lint --all`` (which carries the import contracts),
   ``manage lint --verify-types``, and full-project pyright with ``import riko``
   resolved to the copy rather than the venv's editable install (bisect-safe
   commits). ``--tests`` then runs ``manage test --ratchet`` on each step, one at a
   time, since the suite must run alone. A step that touches ``.claude/skills/``
   also runs the skill scripts' smoke tests (``pytest .claude/skills``).
3. **Autosquash**: when there are fixups, a throwaway worktree replays
   ``rebase -i --autosquash`` from the oldest target, counting the targets of the
   branch's pending ``fixup!`` commits too (an older one left unmoved would collide
   with the plan's), and confirms the squashed tree.

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

import fixup_map
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
MANAGE = ("-m", "riko.cli.manage")
SKILLS = ".claude/skills/"
RIKO_ENV = '{ root = "riko", '
RIKO_ENV_IN_PLACE = '{ root = "riko", extraPaths = ["."], '
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


def load_branch_commits() -> dict[str, str]:
    """Loads the branch's commits past its merge point, none when it has no base."""
    verify = ("rev-parse", "--verify", "--quiet")
    bases = [b for b in fixup_map.BASE_BRANCHES if fixup_map.git(*verify, b)]
    return fixup_map.branch_commits(fixup_map.merge_point()) if bases else {}


def require_targets(steps: list[Step]) -> None:
    """Requires every fixup target to be in HEAD's history, naming any rewritten one."""
    current = {subject: sha for sha, subject in load_branch_commits().items()}

    for step in (s for s in steps if s.kind == "fixup"):
        cmd = (GIT, "merge-base", "--is-ancestor", step.arg, "HEAD")
        missing = subprocess.run(cmd, capture_output=True, check=False).returncode

        if missing:
            subject = git("log", "-1", "--format=%s", step.arg).strip()
            match = current.get(subject)
            hint = f"; that subject is now {match[:8]}" if match else ""
            sys.exit(f"fixup target {step.arg} is not in HEAD's history{hint}")


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


def extract(step: Step) -> Path:
    """Extracts the step's tree into a fresh git-initialized folder."""
    root = Path(tempfile.mkdtemp(prefix="plan-check-"))
    archive = subprocess.run(
        (GIT, "archive", step.commit), capture_output=True, check=True
    )
    subprocess.run((TAR, "-x", "-C", root), input=archive.stdout, check=True)

    for command in ((GIT, "init", "-q"), (GIT, "add", "-A")):
        subprocess.run(command, cwd=root, capture_output=True, check=True)

    return root


def run_checks(root: Path, commands: list[tuple[str, tuple[str, ...]]]) -> str:
    env = {**os.environ, "PYTHONPATH": str(root)}
    failures = []

    for label, command in commands:
        run = subprocess.run(
            command, cwd=root, env=env, capture_output=True, text=True, check=False
        )

        if run.returncode:
            tail = (run.stdout + run.stderr).strip().splitlines()[-3:]
            failures.append(f"{label}: {' | '.join(tail)}")

    return "; ".join(failures) or "ok"


def check(root: Path, *, full: bool, skills: bool = False) -> str:
    """Runs the build checks on an extracted copy of the step's tree."""
    py = sys.executable
    ruff = (py, "-m", "ruff", "check", "--no-cache", "-q", "--select", RUFF_RULES)
    build = [("ruff", (*ruff, "riko")), ("import", (py, "-c", IMPORT_SMOKE))]

    if skills:
        pytest = (py, "-m", "pytest", "-q", "--no-cov", "-p", "no:cacheprovider")
        build.append(("skill-tests", (*pytest, "-o", "addopts=", SKILLS)))
    results = [run_checks(root, build)]

    if full:
        lints = [
            ("lint", (py, *MANAGE, "lint", "--all")),
            ("verify-types", (py, *MANAGE, "lint", "--verify-types")),
        ]
        results.append(run_checks(root, lints))
        config = root / "pyproject.toml"
        text = config.read_text()

        if RIKO_ENV not in text:
            sys.exit(
                f"{config} lacks the {RIKO_ENV.strip()} pyright execution environment"
            )

        config.write_text(text.replace(RIKO_ENV, RIKO_ENV_IN_PLACE))
        pyright = str(Path(py).parent / "pyright")
        results.append(
            run_checks(root, [("pyright", (pyright, "-p", "pyproject.toml"))])
        )

    return "; ".join(r for r in results if r != "ok") or "ok"


def run_suite(root: Path) -> str:
    """Runs the full suite with the coverage ratchet on one extracted tree."""
    suite = (sys.executable, *MANAGE, "test", "--ratchet", "--quiet")
    return run_checks(root, [("tests", suite)])


def oldest(shas: list[str]) -> str:
    order = git("rev-list", "--topo-order", "HEAD").split()
    full = [git("rev-parse", s).strip() for s in shas]
    return max(full, key=order.index)


def load_pending_targets() -> list[str]:
    """Loads the targets of the branch's pending ``fixup!`` commits."""
    commits = load_branch_commits()
    fixups = (sha for sha, subject in commits.items() if subject.startswith("fixup! "))
    targets = {fixup_map.resolve_target(sha, commits) for sha in fixups}
    return sorted(t for t in targets if t is not None)


def rehearse_autosquash(steps: list[Step]) -> str:
    targets = [s.arg for s in steps if s.kind == "fixup"]
    result = "no fixups"

    if targets:
        targets.extend(load_pending_targets())
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
    parser.add_argument("--full-checks", action="store_true", help="lint + types")
    parser.add_argument("--tests", action="store_true", help="suite per step, alone")
    parser.add_argument("--copy", action="store_true", help="pbcopy the chain")
    args = parser.parse_args()

    out = args.out or Path(tempfile.mkdtemp(prefix="plan-out-"))
    files = load_change(args.context)
    steps = read_plan(args.plan)
    require_targets(steps)
    assign(steps, files)
    skipped = [s for s in steps if s.kind == "skip"]
    steps = [s for s in steps if s.kind != "skip"]
    build_commits(steps, files, args.plan.parent)
    final_tree = working_tree()

    left_out = {i.split(":")[0] for s in skipped for i in s.ids}
    stray = set(git("diff", "--name-only", steps[-1].tree, final_tree).split())

    if stray != left_out and not stray < left_out:
        sys.exit(f"final tree differs from the working tree outside skip: {stray}")

    roots = [extract(step) for step in steps]
    skills = [any(i.startswith(SKILLS) for i in step.ids) for step in steps]

    def _check(root: Path, touches: bool) -> str:
        return check(root, full=args.full_checks, skills=touches)

    with ThreadPoolExecutor(max_workers=4) as pool:
        checks = list(pool.map(_check, roots, skills))

    suites = [run_suite(root) for root in roots] if args.tests else []
    squash = rehearse_autosquash(steps)
    rows = write_outputs(steps, out, files)

    for n, ((header, details), result) in enumerate(zip(rows, checks, strict=True)):
        tests = f"  tests: {suites[n]}" if suites else ""
        print(f"{header}  check: {result}{tests}")
        print("\n".join(details))

    kept = f"; left uncommitted: {', '.join(sorted(left_out))}" if left_out else ""
    print(f"\ncoverage: every id in exactly one step{kept}")
    print(f"autosquash: {squash}")
    print(f"outputs: {out}/ (NN.patch, NN.msg, commands.txt, chain.txt)")

    if args.copy and PBCOPY:
        subprocess.run((PBCOPY,), input=(out / "chain.txt").read_bytes(), check=True)
        print("chain copied to the clipboard")

    failed = any(c != "ok" for c in (*checks, *suites)) or squash not in {
        "ok",
        "no fixups",
    }
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
