"""
Builds, checks, and rehearses a /land commit plan without touching the user's tree.

Usage: python .claude/skills/land/rehearse_plan.py [PLAN] [--out DIR] [-U N]
       [--full-checks] [--tests] [--copy] [--fold TARGET:MOVER[@ID,ID...]]
       [--resolve PATH=ours|theirs|max] [--reword SHA=FILE]

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
   also runs the skill scripts' smoke tests (``pytest .claude/skills``). A failing
   check writes its whole output to ``NN.<label>.log`` in ``--out``, and the summary
   quotes its first error-looking lines (a lint's last lines are often a success
   line from another check).
3. **Autosquash**: when there are fixups, a throwaway worktree replays
   ``rebase -i --autosquash`` from the oldest target, counting the targets of the
   branch's pending ``fixup!`` commits too (an older one left unmoved would collide
   with the plan's), and confirms the squashed tree.

Writes ``NN.patch``/``NN.msg`` per step plus ``commands.txt`` (one line per step,
always ``git reset -q`` first, so the chain never depends on what is staged when it
runs) and ``chain.txt`` (all steps joined with ``&&``) to ``--out`` (default: a new
temp folder). ``--copy`` puts the chain on the clipboard. Nothing is ever deleted;
temp folders are left for the OS.

**Folds** move hunks of an already-committed branch commit (the mover) into an
earlier branch commit (the target), so a fix lands in the commit that caused it:

    fold e5448a49b 5052114ad     # target, then mover
    riko/execution/_sync_execution.py
    tests/internal/test_plan_closes.py:681

The ids are the mover's own (``split_hunks.py list --base M^ --head M``); ``*`` or
none folds the whole commit. ``--fold TARGET:MOVER[@ID,ID...]`` (repeatable) adds the
same step without a plan file. Both commits must be past the merge point, the target
older. One throwaway worktree detached at ``HEAD`` replays them from the oldest fold,
plan fixup, or pending ``fixup!`` target:

1. ``rebase -i`` (this script is its sequence editor): a whole mover becomes a
   ``fixup`` line after its target; a partial mover stops as ``edit`` and is split into
   ``fixup! <target subject>`` (the selected hunks) and the rest, which keeps the
   mover's message and author.
2. One ``rebase -i --autosquash`` squashes those and every pending ``fixup!`` together,
   plus the plan's own fixups (built on step 1's tip) when the plan has any.

The squashed tip's tree must equal ``HEAD``'s (or the plan's last step). A conflict in
either pass stops the rehearsal and names the commit, paths, and worktree; with
``--resolve PATH=MODE`` the diff3 blocks of that path take ``ours`` (the commit being
rebased onto), ``theirs`` (the commit being replayed), or the lexically larger side
(``max``) and the rebase continues. Every rewritten commit whose tree changed gets the
build checks (and ``--full-checks``/``--tests``); at a target's rewritten commit, moved
test hunks that name something absent there are reported by id, with the plan line
that keeps them in the mover. The old -> new sha table is printed for
``mistake_scan.py --remap``. With folds only, the chain is ``git reset --keep <tip>``
(plus ``git push --force-with-lease`` when a rewritten commit is on a remote); with
working-tree steps too it is ``git reset --keep <step-1 tip>`` and then the steps, and
the rehearsed autosquash is left to ``/wrapup``.

**Rewords** replace a branch commit's message: ``reword <sha> <msg-file>`` (the file
relative to PLAN, as for ``commit``) or ``--reword SHA=FILE``. Step 1 runs
``git commit --amend -F`` right after the commit (after a partial mover's split, so the
rest takes the new message; after a target's fixups, so the squash keeps it). The
branch's pending ``fixup!`` commits for a reworded commit move to it in step 1, since
their subjects name the old message. The table shows old => new subjects.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from itertools import chain
from pathlib import Path
from subprocess import CompletedProcess
from typing import TYPE_CHECKING

sys.path.insert(0, str(Path(__file__).parent))

import fixup_map
import split_hunks
from split_hunks import (
    GIT,
    TreeBuilder,
    expand,
    git,
    index_hunks,
    load_change,
    working_tree,
)

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator

DESCRIPTION = "Build, check, and rehearse a /land commit plan."
RUFF_RULES = "F821,F401,F811"
IMPORT_SMOKE = "import riko, riko.cli.manage"
MANAGE = ("-m", "riko.cli.manage")
SKILLS = ".claude/skills/"
TAR = shutil.which("tar") or "tar"
PBCOPY = shutil.which("pbcopy")
EDIT_TODO = "--edit-todo"
FOLD_ENV = "REHEARSE_PLAN_FOLDS"
RESOLVE_MODES = ("ours", "theirs", "max")
DIFF3_RE = re.compile(
    r"^<<<<<<< .*?\n(.*?)^\|\|\|\|\|\|\| .*?\n.*?^=======\n(.*?)^>>>>>>> .*?\n",
    re.DOTALL | re.MULTILINE,
)
UNDEFINED_RE = re.compile(r"F821 Undefined name `([^`]+)`")
FAILURE = re.compile(
    r"error|fail|violation|no longer exist|would be reformatted|exceeds|"
    r"\[MD\d+\]|IAR\d+",
    re.IGNORECASE,
)
PASSING = re.compile(
    r"\b0 errors\b|no issues|success|passed|hold the ceiling", re.IGNORECASE
)


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
        elif head in {"fold", "reword"} and len(rest.split()) == 2:
            steps.append(Step(head, " ".join(rest.split())))
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
        cmd = (GIT, "merge-base", "--is-ancestor", step.arg, split_hunks.BASE)
        missing = subprocess.run(cmd, capture_output=True, check=False).returncode

        if missing:
            subject = git("log", "-1", "--format=%s", step.arg).strip()
            match = current.get(subject)
            hint = f"; that subject is now {match[:8]}" if match else ""
            base = "HEAD" if split_hunks.BASE == "HEAD" else split_hunks.BASE[:8]
            sys.exit(f"fixup target {step.arg} is not in {base}'s history{hint}")


def assign(steps: list[Step], files: list) -> None:
    """Expands every step's entries, enforcing that each id is taken exactly once."""
    every = list(index_hunks(files))
    owner: dict[str, int] = {}

    for n, step in enumerate(steps):
        explicit = [e for e in step.entries if e != "*"]

        for hid in chain.from_iterable(expand(e, files) for e in explicit):
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


def build_commits(
    steps: list[Step], files: list, plan_dir: Path, parent: str | None = None
) -> None:
    builder = TreeBuilder(files)
    parent = parent or split_hunks.BASE
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


def extract(sha: str) -> Path:
    """Extracts a commit's tree into a fresh git-initialized folder."""
    root = Path(tempfile.mkdtemp(prefix="plan-check-"))
    archive = subprocess.run((GIT, "archive", sha), capture_output=True, check=True)
    subprocess.run((TAR, "-x", "-C", root), input=archive.stdout, check=True)

    for command in ((GIT, "init", "-q"), (GIT, "add", "-A")):
        subprocess.run(command, cwd=root, capture_output=True, check=True)

    return root


def get_failure_lines(output: str) -> list[str]:
    """Gets a failed check's first three error-looking lines, else its last three."""
    lines = [line.strip() for line in output.strip().splitlines() if line.strip()]
    errors = [
        line for line in lines if FAILURE.search(line) and not PASSING.search(line)
    ]
    return errors[:3] or lines[-3:]


def run_checks(
    root: Path, commands: list[tuple[str, tuple[str, ...]]], log: Path | None = None
) -> str:
    """Runs each check on ``root``, logging a failure to ``<log>.<label>.log``."""
    env = {**os.environ, "PYTHONPATH": str(root)}
    failures = []

    for label, command in commands:
        run = subprocess.run(
            command, cwd=root, env=env, capture_output=True, text=True, check=False
        )

        if run.returncode:
            output = run.stdout + run.stderr
            summary = " | ".join(get_failure_lines(output))

            if log is not None:
                path = log.with_name(f"{log.name}.{label}.log")
                path.write_text(output)
                summary = f"{summary} (log: {path.name})"

            failures.append(f"{label}: {summary}")

    return "; ".join(failures) or "ok"


def check(
    root: Path, *, full: bool, skills: bool = False, log: Path | None = None
) -> str:
    """Runs the build checks on an extracted copy of the step's tree."""
    py = sys.executable
    ruff = (py, "-m", "ruff", "check", "--no-cache", "-q", "--select", RUFF_RULES)
    build = [("ruff", (*ruff, "riko")), ("import", (py, "-c", IMPORT_SMOKE))]

    if skills:
        pytest = (py, "-m", "pytest", "-q", "--no-cov", "-p", "no:cacheprovider")
        build.append(("skill-tests", (*pytest, "-o", "addopts=", SKILLS)))
    results = [run_checks(root, build, log)]

    if full:
        lints = [
            ("lint", (py, *MANAGE, "lint", "--all")),
            ("verify-types", (py, *MANAGE, "lint", "--verify-types")),
        ]
        results.append(run_checks(root, lints, log))
        pyright = str(Path(py).parent / "pyright")
        results.append(
            run_checks(root, [("pyright", (pyright, "-p", "pyproject.toml"))], log)
        )

    return "; ".join(r for r in results if r != "ok") or "ok"


def run_suite(root: Path, log: Path | None = None) -> str:
    """Runs the full suite with the coverage ratchet on one extracted tree."""
    suite = (sys.executable, *MANAGE, "test", "--ratchet", "--quiet")
    return run_checks(root, [("tests", suite)], log)


def oldest(shas: list[str]) -> str:
    order = git("rev-list", "--topo-order", split_hunks.BASE).split()
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


@dataclass
class Fold:
    """Moves hunks of a branch commit (the mover) into an earlier one (the target)."""

    target: str
    mover: str
    entries: list[str] = field(default_factory=list)
    ids: list[str] = field(default_factory=list)
    whole: bool = True
    added: dict[str, str] = field(default_factory=dict)


@dataclass
class Reword:
    """Replaces a branch commit's message with a message file's text."""

    sha: str
    path: Path

    @property
    def subject(self) -> str:
        return next(iter(self.path.read_text().splitlines()), "")


@dataclass
class Rehearsal:
    """One throwaway worktree replaying the folds, then the autosquash."""

    worktree: Path
    base: str
    first: str = ""
    tip: str = ""
    problem: str = ""
    split: set[str] = field(default_factory=set)
    renames: dict[str, str] = field(default_factory=dict)


def parse_fold(spec: str) -> Fold:
    """Parses ``TARGET:MOVER[@ID,ID...]`` (the ``--fold`` shorthand)."""
    pair, _, ids = spec.partition("@")
    target, sep, mover = pair.partition(":")

    if not (sep and target and mover):
        sys.exit(f"--fold wants TARGET:MOVER[@ID,ID...], got {spec}")

    return Fold(target, mover, [i for i in ids.split(",") if i])


def parse_reword(spec: str) -> Reword:
    """Parses ``SHA=FILE`` (the ``--reword`` shorthand)."""
    sha, sep, path = spec.partition("=")

    if not (sep and sha and path):
        sys.exit(f"--reword wants SHA=FILE, got {spec}")

    return Reword(sha, Path(path).resolve())


def gen_plan_rewords(steps: list[Step], plan_dir: Path) -> Iterator[Reword]:
    for step in (s for s in steps if s.kind == "reword"):
        sha, _, path = step.arg.partition(" ")
        yield Reword(sha, (plan_dir / path.strip()).resolve())


def require_rewords(rewords: list[Reword], folds: list[Fold]) -> None:
    """Requires each reword's commit past the merge point and not folded away."""
    commits = load_branch_commits()
    gone = {f.mover for f in folds if f.whole}

    for reword in rewords:
        reword.sha = git("rev-parse", "--verify", f"{reword.sha}^{{commit}}").strip()

        if reword.sha not in commits:
            sys.exit(f"reword {reword.sha[:9]} is at or before the merge point")
        elif reword.sha in gone:
            sys.exit(f"reword {reword.sha[:9]} is a whole fold's mover")
        elif not reword.path.is_file():
            sys.exit(f"reword message file not found: {reword.path}")

    shas = [r.sha for r in rewords]

    if len(set(shas)) < len(shas):
        sys.exit("a commit may be reworded only once")


def gen_plan_folds(steps: list[Step]) -> Iterator[Fold]:
    for step in (s for s in steps if s.kind == "fold"):
        target, _, mover = step.arg.partition(" ")
        yield Fold(target, mover.strip(), step.entries)


@contextmanager
def at_commit(sha: str) -> Generator[None]:
    """Points ``split_hunks`` at ``sha``'s own diff, restoring the plan's base after."""
    base, head = split_hunks.BASE, split_hunks.HEAD
    split_hunks.set_base(f"{sha}^")
    split_hunks.set_head(sha)

    try:
        yield
    finally:
        split_hunks.BASE, split_hunks.HEAD = base, head


def load_mover_change(sha: str, context: int) -> list:
    """Loads ``sha``'s own diff as selectable hunks, restoring the plan's base."""
    with at_commit(sha):
        files = load_change(context)

    return files


def require_folds(folds: list[Fold], context: int) -> None:
    """Requires each fold's commits past the merge point, in order, and its ids."""
    commits = load_branch_commits()

    for fold in folds:
        fold.target = git("rev-parse", "--verify", f"{fold.target}^{{commit}}").strip()
        fold.mover = git("rev-parse", "--verify", f"{fold.mover}^{{commit}}").strip()
        cmd = (GIT, "merge-base", "--is-ancestor", fold.target, f"{fold.mover}^")
        ordered = not subprocess.run(cmd, capture_output=True, check=False).returncode

        if outside := [s[:9] for s in (fold.target, fold.mover) if s not in commits]:
            sys.exit(f"fold {', '.join(outside)} is at or before the merge point")
        elif not ordered:
            sys.exit(
                f"fold target {fold.target[:9]} is not older than {fold.mover[:9]}"
            )

        files = load_mover_change(fold.mover, context)
        every = index_hunks(files)
        explicit = [e for e in fold.entries if e != "*"]
        fold.ids = list(chain.from_iterable(expand(e, files) for e in explicit))
        fold.whole = not fold.ids or set(fold.ids) == set(every)
        fold.added = {
            hid: "".join(getattr(item, "added", [])) for hid, item in every.items()
        }

    movers = [f.mover for f in folds]

    if len(set(movers)) < len(movers):
        sys.exit("a commit may be the mover of only one fold")


def edit_todo(path: Path, specs: dict[str, list[list]]) -> None:
    """Rewrites a rebase todo: whole movers become fixups after their target."""
    lines = path.read_text().splitlines()

    def _sha(line: str) -> str:
        words = line.split()
        return words[1] if len(words) > 1 and not line.startswith("#") else "-"

    for target, mover, whole in specs["folds"]:
        moved = [line for line in lines if mover.startswith(_sha(line))]

        if whole:
            kept = [line for line in lines if line not in moved]
            spot = next(
                n for n, line in enumerate(kept) if target.startswith(_sha(line))
            )
            spot += 1

            while spot < len(kept) and kept[spot].startswith("fixup "):
                spot += 1

            fixups = ["fixup " + line.split(None, 1)[1] for line in moved]
            lines = [*kept[:spot], *fixups, *kept[spot:]]
        else:
            lines = [
                "edit " + line.split(None, 1)[1] if line in moved else line
                for line in lines
            ]

    for sha, message in specs["rewords"]:
        spot = next(n for n, line in enumerate(lines) if sha.startswith(_sha(line)))
        spot += 1

        while spot < len(lines) and lines[spot].startswith("fixup "):
            spot += 1

        amend = f"exec git commit --amend -q --no-verify -F {shlex.quote(message)}"
        lines.insert(spot, amend)

    path.write_text("\n".join(lines) + "\n")


def run_in(worktree: Path, *args: str, env: dict | None = None) -> CompletedProcess:
    config = (
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "merge.conflictStyle=diff3",
        "-c",
        "maintenance.auto=false",
    )
    return subprocess.run(
        (GIT, *config, *args),
        cwd=worktree,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def pick_side(path: Path, mode: str) -> int:
    """Resolves the diff3 conflict blocks in ``path`` to one side; counts them."""
    text, count = DIFF3_RE.subn(
        lambda m: {"ours": m[1], "theirs": m[2], "max": max(m[1], m[2])}[mode],
        path.read_text(),
    )
    path.write_text(text)
    return count


def split_mover(r: Rehearsal, fold: Fold, context: int) -> str:
    """Splits the stopped mover into its fold's ``fixup!`` and the rest."""
    stopped = run_in(r.worktree, "rev-parse", "HEAD").stdout.strip()
    files = load_mover_change(stopped, context)
    known = index_hunks(files)
    problem = ""

    if missing := [hid for hid in fold.ids if hid not in known]:
        problem = f"fold ids not in the replayed {fold.mover[:9]}: {', '.join(missing)}"
    else:
        with at_commit(stopped):
            tree = TreeBuilder(files).tree(set(fold.ids))

        subject = git("log", "-1", "--format=%s", fold.target).strip()
        message = f"fixup! {r.renames.get(fold.target, subject)}\n".encode()
        args = ("commit-tree", tree, "-p", f"{stopped}^", "-F", "-")
        picked = git(*args, data=message).strip()
        author = git("log", "-1", "--format=%an%n%ae%n%aI", stopped).splitlines()
        keys = ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_AUTHOR_DATE")
        env = {**os.environ, **dict(zip(keys, author, strict=True))}
        body = git("log", "-1", "--format=%B", stopped).encode()
        args = ("commit-tree", f"{stopped}^{{tree}}", "-p", picked, "-F", "-")
        rest = git(*args, data=body, env=env).strip()
        run_in(r.worktree, "reset", "-q", "--soft", rest)
        r.split.add(fold.mover)

    return problem


def drive_rebase(
    r: Rehearsal,
    command: tuple[str, ...],
    env: dict[str, str],
    resolve: dict[str, str],
    folds: dict[str, Fold],
    context: int,
) -> str:
    """Runs a rebase through its stops: splits partial movers, resolves conflicts."""
    run = run_in(r.worktree, *command, env=env)
    state = Path(run_in(r.worktree, "rev-parse", "--git-path", "rebase-merge").stdout)
    state = r.worktree / state.as_posix().strip()
    problem = ""

    while state.exists() and not problem:
        status = ("diff", "--name-only", "--diff-filter=U")
        conflicted = run_in(r.worktree, *status).stdout.split()
        done = (state / "done").read_text().splitlines()
        action, _, rest = (done[-1] if done else "").partition(" ")
        stopped = rest.split(" ", 1)[0]
        fold = next((f for m, f in folds.items() if m.startswith(stopped)), None)
        unresolved = [p for p in conflicted if p not in resolve]

        if unresolved:
            head = run_in(r.worktree, "log", "-1", "--format=%h %s", "REBASE_HEAD")
            shown = ", ".join(unresolved)
            problem = f"CONFLICT applying {head.stdout.strip()} in {shown}"
        elif conflicted:
            blocks = [pick_side(r.worktree / p, resolve[p]) for p in conflicted]
            run_in(r.worktree, "add", "--", *conflicted)
            problem = "" if all(blocks) else f"no diff3 blocks in {conflicted}"
        elif action == "edit" and fold is not None and fold.mover not in r.split:
            problem = split_mover(r, fold, context)
        else:
            problem = f"rebase stopped: {run.stderr.strip()[:160]}"

        if not problem:
            run = run_in(r.worktree, "rebase", "--continue", env=env)

    if not problem and run.returncode:
        problem = f"rebase failed: {run.stderr.strip()[:160]}"

    return f"{problem}; worktree {r.worktree}" if problem else ""


def rehearse_folds(
    folds: list[Fold],
    resolve: dict[str, str],
    *,
    targets: list[str] | None = None,
    rewords: list[Reword] | None = None,
    context: int = 0,
) -> Rehearsal:
    """Replays the folds and rewords (pass 1) in a worktree detached at ``HEAD``."""
    rewords = rewords or []
    every = [f.target for f in folds] + [r.sha for r in rewords]
    every += (targets or []) + load_pending_targets()
    base = git("rev-parse", f"{oldest(every)}~1").strip()
    worktree = Path(tempfile.mkdtemp(prefix="plan-fold-")) / "wt"
    git("worktree", "add", "-q", "--detach", str(worktree), "HEAD")
    renames = {w.sha: w.subject for w in rewords}
    r = Rehearsal(worktree, base, renames=renames)
    commits = load_branch_commits()
    pending = [
        [target, sha, True]
        for sha, subject in reversed(commits.items())
        if subject.startswith("fixup! ")
        and (target := fixup_map.resolve_target(sha, commits)) in renames
    ]
    specs = {
        "folds": [*pending, *([f.target, f.mover, f.whole] for f in folds)],
        "rewords": [[w.sha, str(w.path)] for w in rewords],
    }
    editor = f"{shlex.quote(sys.executable)} {shlex.quote(__file__)} {EDIT_TODO}"
    env = {
        **os.environ,
        FOLD_ENV: json.dumps(specs),
        "GIT_SEQUENCE_EDITOR": editor,
        "GIT_EDITOR": "true",
    }
    command = ("rebase", "-q", "-i", "--no-autosquash", "--no-update-refs", base)
    by_mover = {f.mover: f for f in folds}
    r.problem = drive_rebase(r, command, env, resolve, by_mover, context)
    unsplit = [f.mover[:9] for f in folds if not f.whole and f.mover not in r.split]

    if unsplit and not r.problem:
        r.problem = f"partial folds not split: {', '.join(unsplit)}"

    r.first = run_in(worktree, "rev-parse", "HEAD").stdout.strip()
    return r


def rehearse_squash(r: Rehearsal, start: str, resolve: dict[str, str]) -> None:
    """Replays the one combined autosquash (pass 2) from ``start``."""
    run_in(r.worktree, "checkout", "-q", "--detach", start)
    env = {**os.environ, "GIT_SEQUENCE_EDITOR": ":", "GIT_EDITOR": "true"}
    command = ("rebase", "-q", "-i", "--autosquash", "--no-update-refs", r.base)
    r.problem = drive_rebase(r, command, env, resolve, {}, 0)
    r.tip = run_in(r.worktree, "rev-parse", "HEAD").stdout.strip()


def map_commits(
    base: str, old: str, new: str, renames: dict[str, str] | None = None
) -> list[tuple[str, str]]:
    """Pairs ``base..old`` with ``base..new`` by (reworded) subject, oldest first."""

    def _log(tip: str) -> list[tuple[str, str]]:
        log = git("log", "--reverse", "--format=%H%x00%s", f"{base}..{tip}")
        return [tuple(line.split("\0", 1)) for line in log.splitlines() if line]

    fresh = _log(new)
    pairs = []

    for sha, subject in _log(old):
        subject = (renames or {}).get(sha, subject)
        match = next((n for n, (_, s) in enumerate(fresh) if s == subject), None)
        pairs.append((sha, "" if match is None else fresh.pop(match)[0]))

    pairs.extend(("", sha) for sha, _ in fresh)
    return pairs


def describe_pairs(pairs: list[tuple[str, str]], folds: list[Fold]) -> list[str]:
    """Lists old sha/subject -> new sha/subject, naming where a dropped one went."""
    into = {f.mover: f.target for f in folds if f.whole}
    rows = []

    for old, new in pairs:
        subject = git("log", "-1", "--format=%s", old or new).strip()[:56]
        renamed = git("log", "-1", "--format=%s", new).strip()[:56] if new else ""

        if old and new and renamed != subject:
            rows.append(f"  {old[:9]} -> {new[:9]}  {subject}  =>  {renamed}")
        elif old and new:
            mark = "  " if old == new else "->"
            rows.append(f"  {old[:9]} {mark} {new[:9]}  {subject}")
        elif old in into:
            rows.append(f"  {old[:9]} -> folded into {into[old][:9]}  {subject}")
        elif old:
            rows.append(f"  {old[:9]} -> squashed  {subject}")
        else:
            rows.append(f"  {'new':>9} -> {new[:9]}  {subject}")

    return rows


def check_moved_tests(root: Path, folds: list[Fold]) -> str:
    """Names the moved hunks outside ``riko/`` whose names the target lacks."""
    moved = {
        hid: fold
        for fold in folds
        for hid in (fold.ids or fold.added)
        if not hid.startswith("riko/") and split_id(hid)[0].endswith(".py")
    }
    paths = sorted({split_id(h)[0] for h in moved if (root / split_id(h)[0]).exists()})
    py = sys.executable
    ruff = (py, "-m", "ruff", "check", "--no-cache", "-q", "--select", "F821")
    command = (*ruff, "--output-format", "concise", *paths)
    run = subprocess.run(command, cwd=root, capture_output=True, text=True, check=False)
    names = set(UNDEFINED_RE.findall(run.stdout)) if paths else set()
    hits = sorted(
        h for h in moved if any(n in moved[h].added.get(h, "") for n in names)
    )
    hints = []
    define = lambda name: re.compile(
        rf"\b(?:def|class)\s+{re.escape(name)}\b|^{re.escape(name)}\s*=", re.MULTILINE
    )

    for fold in {id(moved[h]): moved[h] for h in hits}.values():
        mine = [h for h in hits if moved[h] is fold]
        keep = [h for h in (fold.ids or fold.added) if h not in mine]
        header = f"fold {fold.target[:9]} {fold.mover[:9]}"
        line = f"plan `{header}` + {' '.join(keep)}" if keep else "drop the fold"
        defining = [
            hid
            for hid, text in fold.added.items()
            if hid not in moved and any(define(n).search(text) for n in names)
        ]
        take = f"; or also fold {' '.join(defining)}, which define them" * bool(
            defining
        )
        hints.append(
            f"undefined {', '.join(sorted(names))} from {', '.join(mine)}; "
            f"to keep those in the mover, {line}{take}"
        )

    return "; ".join(hints) or "ok"


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
    steps: list[Step],
    out: Path,
    files: list,
    lead: list[str] | None = None,
    parent: str | None = None,
) -> list[tuple[str, list[str]]]:
    """Writes each step's patch and message, ``commands.txt``, and ``chain.txt``."""
    out.mkdir(parents=True, exist_ok=True)
    head = git("rev-parse", "HEAD").strip()
    base = split_hunks.BASE
    reset = "git reset -q" if base == head or parent else f"git reset -q {base}"
    lines = [*(lead or []), *([reset] if steps else [])]
    parent = parent or base
    hunks: dict[str, set[str]] = {}
    rows = []

    for hid in index_hunks(files):
        path, line = split_id(hid)
        hunks.setdefault(path, set()).add(line)

    for n, step in enumerate(steps, 1):
        patch, msg = out / f"{n:02}.patch", out / f"{n:02}.msg"
        patch.write_text(git("diff", "--binary", parent, step.commit))
        msg.write_text(step.message)

        if step.kind == "fixup":
            commit = f"git commit -q --fixup={step.arg}"
        else:
            commit = f"git commit -q -F {msg}"

        lines.append(f"git apply --cached {patch} && {commit}")
        header = f"{n:02}  {step.message.splitlines()[0][:60]:<60}"
        rows.append((header, describe_files(step, parent, hunks)))
        parent = step.commit

    (out / "commands.txt").write_text("\n".join(lines) + "\n")
    (out / "chain.txt").write_text(" && ".join(lines))
    return rows


def parse_resolve(entries: list[str]) -> dict[str, str]:
    """Parses ``PATH=ours|theirs|max`` conflict picks."""
    picks = dict(entry.rpartition("=")[::2] for entry in entries)

    if bad := [f"{k}={v}" for k, v in picks.items() if not k or v not in RESOLVE_MODES]:
        sys.exit(f"--resolve wants PATH=ours|theirs|max, got {', '.join(bad)}")

    return picks


def is_pushed(pairs: list[tuple[str, str]]) -> bool:
    """Tells whether a remote branch holds any commit the folds rewrite."""
    rewritten = [old for old, new in pairs if old and old != new]
    return bool(rewritten and git("branch", "-r", "--contains", rewritten[0]).strip())


def check_folds(
    args: argparse.Namespace, out: Path, pairs: list[tuple[str, str]], folds: list[Fold]
) -> list[tuple[str, str]]:
    """Checks every rewritten commit whose tree changed; hints at moved test hunks."""
    tree = lambda sha: git("rev-parse", f"{sha}^{{tree}}").strip()
    changed = [(o, n) for o, n in pairs if o and n and tree(o) != tree(n)]
    targets = {f.target for f in folds}
    roots = [extract(new) for _, new in changed]
    results = []

    def _check(pair: tuple[str, str], root: Path) -> str:
        old, new = pair
        touched = git("diff", "--name-only", old, new).split()
        skills = any(path.startswith(SKILLS) for path in touched)
        log = out / f"fold-{new[:9]}"
        result = check(root, full=args.full_checks, skills=skills, log=log)
        suite = run_suite(root, log) if args.tests else "ok"
        hint = check_moved_tests(root, folds) if old in targets else "ok"
        tested = [
            h for f in folds for h in (f.ids or f.added) if h.startswith("tests/")
        ]

        if suite != "ok" and old in targets and tested:
            hint = f"{hint}; suite fails at the target with test hunks {tested}"

        return "; ".join(r for r in (result, suite, hint) if r != "ok") or "ok"

    with ThreadPoolExecutor(max_workers=1 if args.tests else 4) as pool:
        checked = list(pool.map(_check, changed, roots))

    for (_, new), result in zip(changed, checked, strict=True):
        subject = git("log", "-1", "--format=%s", new).strip()[:56]
        results.append((f"  {new[:9]}  {subject}", result))

    return results


def finish_folds(
    args: argparse.Namespace,
    out: Path,
    rehearsal: Rehearsal,
    start: str,
    folds: list[Fold],
    resolve: dict[str, str],
) -> tuple[str, list[tuple[str, str]], list[str]]:
    """Squashes from ``start``, confirms the tree, checks, and prints the sha map."""
    rehearse_squash(rehearsal, start, resolve)
    stray = sorted(
        {
            *git("diff", "--name-only", "HEAD", rehearsal.first).split(),
            *git("diff", "--name-only", start, rehearsal.tip).split(),
        }
    )

    if stray:
        differs = (
            f"squashed tree differs in {', '.join(stray)}; "
            f"worktree {rehearsal.worktree}"
        )
    else:
        differs = "ok"

    squash = rehearsal.problem or differs
    folded: list[tuple[str, str]] = []
    lead: list[str] = []

    if squash == "ok":
        pairs = map_commits(rehearsal.base, "HEAD", rehearsal.tip, rehearsal.renames)
        folded = check_folds(args, out, pairs, folds)
        push = " && git push --force-with-lease" if is_pushed(pairs) else ""
        steps = start != rehearsal.first

        if steps:
            reset = f"git reset --keep {rehearsal.first}"
        else:
            reset = f"git reset --keep {rehearsal.tip}{push}"

        lead = [reset]
        print("rewritten (old -> new; => marks a reworded subject):")
        print("\n".join(describe_pairs(pairs, folds)))

        for row, result in folded:
            print(f"{row}  check: {result}")

    return squash, folded, lead


def require_final_tree(steps: list[Step], left_out: set[str]) -> None:
    """Requires the last step's tree to match the working tree outside skipped ids."""
    if steps:
        stray = set(git("diff", "--name-only", steps[-1].tree, working_tree()).split())

        if stray != left_out and not stray < left_out:
            sys.exit(f"final tree differs from the working tree outside skip: {stray}")


def rehearse_rewrites(
    folds: list[Fold],
    rewords: list[Reword],
    resolve: dict[str, str],
    targets: list[str],
    context: int,
) -> Rehearsal | None:
    """Rehearses the folds and rewords, if any, and exits on a rehearsal problem."""
    if folds or rewords:
        rehearsal = rehearse_folds(
            folds, resolve, targets=targets, rewords=rewords, context=context
        )
    else:
        rehearsal = None

    if rehearsal is not None and rehearsal.problem:
        sys.exit(f"fold rehearsal: {rehearsal.problem}")

    return rehearsal


def main() -> None:
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument("plan", type=Path, nargs="?", help="plan file")
    parser.add_argument("--out", type=Path, help="output folder (default: temp)")
    parser.add_argument("-U", type=int, default=0, dest="context", help="diff context")
    parser.add_argument("--full-checks", action="store_true", help="lint + types")
    parser.add_argument("--tests", action="store_true", help="suite per step, alone")
    parser.add_argument("--copy", action="store_true", help="pbcopy the chain")
    parser.add_argument("--base", default="HEAD", help="commit the chain resets to")
    parser.add_argument(
        "--fold", action="append", default=[], help="TARGET:MOVER[@ID,ID...]"
    )
    parser.add_argument(
        "--resolve", action="append", default=[], help="PATH=ours|theirs|max"
    )
    parser.add_argument("--reword", action="append", default=[], help="SHA=FILE")
    args = parser.parse_args()
    split_hunks.set_base(args.base)

    out = args.out or Path(tempfile.mkdtemp(prefix="plan-out-"))
    steps = read_plan(args.plan) if args.plan else []
    plan_dir = args.plan.parent if args.plan else Path()
    folds = [*gen_plan_folds(steps), *map(parse_fold, args.fold)]
    rewords = [*gen_plan_rewords(steps, plan_dir), *map(parse_reword, args.reword)]
    steps = [s for s in steps if s.kind not in {"fold", "reword"}]
    resolve = parse_resolve(args.resolve)
    rewrites = bool(folds or rewords)

    if not (steps or rewrites):
        sys.exit("nothing to rehearse: pass a PLAN, --fold, or --reword")
    elif rewrites and split_hunks.BASE != git("rev-parse", "HEAD").strip():
        sys.exit("folds and rewords rewrite HEAD's history; they cannot take --base")

    require_targets(steps)
    require_folds(folds, args.context)
    require_rewords(rewords, folds)
    fixup_targets = [s.arg for s in steps if s.kind == "fixup"]
    rehearsal = rehearse_rewrites(folds, rewords, resolve, fixup_targets, args.context)
    files = load_change(args.context) if steps else []
    assign(steps, files)
    skipped = [s for s in steps if s.kind == "skip"]
    steps = [s for s in steps if s.kind != "skip"]
    first = rehearsal.first if rehearsal else None
    build_commits(steps, files, plan_dir, first)
    left_out = {i.split(":")[0] for i in chain.from_iterable(s.ids for s in skipped)}

    require_final_tree(steps, left_out)
    out.mkdir(parents=True, exist_ok=True)
    roots = [extract(step.commit) for step in steps]
    skills = [any(i.startswith(SKILLS) for i in step.ids) for step in steps]
    logs = [out / f"{n:02}" for n in range(1, len(steps) + 1)]

    def _check(root: Path, touches: bool, log: Path) -> str:
        return check(root, full=args.full_checks, skills=touches, log=log)

    with ThreadPoolExecutor(max_workers=4) as pool:
        checks = list(pool.map(_check, roots, skills, logs))

    if args.tests:
        suites = [run_suite(root, log) for root, log in zip(roots, logs, strict=True)]
    else:
        suites = []

    lead: list[str] = []
    folded: list[tuple[str, str]] = []

    if rehearsal is None:
        squash = rehearse_autosquash(steps)
    else:
        start = steps[-1].commit if steps else rehearsal.first
        squash, folded, lead = finish_folds(args, out, rehearsal, start, folds, resolve)

    rows = write_outputs(steps, out, files, lead, first if steps else None)

    if rehearsal is not None and squash != "ok":
        (out / "commands.txt").write_text("")
        (out / "chain.txt").write_text("")

    for n, ((header, details), result) in enumerate(zip(rows, checks, strict=True)):
        tests = f"  tests: {suites[n]}" if suites else ""
        print(f"{header}  check: {result}{tests}")
        print("\n".join(details))

    kept = f"; left uncommitted: {', '.join(sorted(left_out))}" if left_out else ""
    print(f"\ncoverage: every id in exactly one step{kept}" if steps else "")
    print(f"autosquash: {squash}")
    ok = squash in {"ok", "no fixups"}
    listed = "NN.patch, NN.msg, NN.*.log, commands.txt, chain.txt"
    chained = bool((out / "chain.txt").read_text())
    shown = listed if chained else "NN.*.log; no chain was produced"
    print(f"outputs: {out}/ ({shown})")

    if rehearsal is not None and steps:
        print("the fixup! commits stay pending: /wrapup runs the rehearsed autosquash")

    if args.copy and PBCOPY and ok and chained:
        subprocess.run((PBCOPY,), input=(out / "chain.txt").read_bytes(), check=True)
        print("chain copied to the clipboard")

    results = (*checks, *suites, *(r for _, r in folded))
    failed = any(c != "ok" for c in results) or not ok
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    if sys.argv[1:2] == [EDIT_TODO]:
        edit_todo(Path(sys.argv[2]), json.loads(os.environ[FOLD_ENV]))
    else:
        main()
