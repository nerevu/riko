---
name: land
description: Run riko's full pre-commit gate and get the working tree ready for the user to commit — dependency upgrade, /tidy, prettify, codegen drift, lint --all (which covers docs and docstrings), tests, check-types — then report a ready/not-ready verdict with a suggested commit message. Use when the user says "land this", "get this ready to commit", "run the gates", "is this ready to commit?", or wants a change finished and validated. This skill NEVER commits; the user commits themselves.
---

# Land (gate everything, commit nothing)

Get the working tree to a state the user can commit with confidence. Run every
gate, fix what the gates find, and report honestly. **Do not run `git commit`,
`git add`, or any other git write operation** on the user's branch, index, or
working tree — the user owns the commit. The only exception is the throwaway
fixup rehearsal worktree described under "Commit plan".

## Idempotency

Landing may be invoked mid-session after some gates already ran — never redo
work, and never trust that earlier work still holds:

- Every gate is safe to rerun (prettify, codegen, lint,
  and tests are all stateless checks; `manage upgrade --daily` is a no-op after
  today's upgrade), so rerunning is never wrong — only sometimes wasteful.
- Skip a gate only when BOTH hold: it passed earlier **in this session**, and
  nothing in its scope has changed since that run (confirm against `git
  status`/`git diff`, not recollection). A gate that passed before subsequent
  edits proves nothing.
- Before applying any fix (regenerating a file, adding a missing entry,
  correcting a failure), check the current state first — the fix may already
  be in place from earlier in the session. Re-applying blindly can duplicate
  entries or clobber newer work.
- When in doubt, rerun the gate: a redundant gate costs seconds; a skipped
  failing gate costs a bad commit. The expensive full test suite is the only
  gate worth a genuine skip decision.
- Note skipped gates in the report with the reason ("passed at <point>, no
  changes since").

## Gate sequence

Order matters. Run from the repo root with `uv run --active python -m
riko.cli.manage` (the `manage` entry point can collide with mezmorize's).

0. **Upgrade dependencies**: `manage upgrade --daily`. It re-resolves `uv.lock` to the
   newest allowed versions and syncs the active environment, so a new ruff,
   pyright, or runtime release breaks here instead of in CI (CI installs the
   lock with `--locked` and never upgrades). A `uv.lock` diff is part of the
   change — keep it, and name upgraded packages in the report. If an upgrade
   breaks a gate, fixing the code is the default; holding a package back is a
   judgment call for the user. `--daily` makes it a no-op when a full upgrade
   already succeeded today, so always run it; never skip it by recollection.
1. **Tidy**: run `.claude/skills/tidy/SKILL.md` over the change in a fresh
   subagent given the skill text, never as an in-loop grep pass (it skips
   itself when its marker says the tree is already tidy). Its mechanical fixes
   join the change before the gates run; its judgment questions go to the user
   now, and phase-owned findings go through `/triage`.
2. **Prettify first, always**: `manage prettify`. Never hand-fix
   formatting-class lint errors — formatting is prettify's job, before any
   linter runs.
3. **Codegen drift**: if the change touched anything with a generated artifact
   (configs, module names/ids, API surface blocks, pipeline fixtures), run
   `manage codegen --all` and check `git diff` on the generated files. A diff
   there is part of the change, not noise — keep it. Never hand-edit generated
   files.
4. **Lint**: `manage lint --all`. It already runs Ruff, the RST/docs/docstring/
   terms/literals/deps/bindings checks, actionlint, YAML, and every import contract, so do not rerun
   `--docs`, `--docstrings`, `--terms`, `--literals`, `--deps`, or `--bindings` separately. It does **not** run the type gate.
5. **Tests**: targeted tests for the touched area first while iterating, then
   the full suite `manage test --ratchet --quiet` before declaring ready.
   Doctests are tests here — doc examples run under pytest. `--ratchet` fails
   when the run leaves more statements uncovered than the ceiling in
   `pyproject.toml` (`[tool.riko.coverage] uncovered`): cover the new or
   newly-unexecuted lines rather than raising the ceiling (raising it is a
   judgment call for the user). When it lowers the ceiling, that `pyproject.toml`
   diff is part of the change — keep it. The ceiling is measured in the full dev
   environment (`--group dev --all-extras`, Python 3.12).
6. **Types**: `manage lint --check-types` (never part of `--all`); add
   `--verify-types` for changes to exported surfaces.

Fix real failures properly (root cause, not suppression), rerun the affected
gate, and repeat until clean. If something cannot be fixed within the change's
scope, stop and report it as a blocker — do not paper over it.

Mechanical fixes (formatting, regenerated files, a missing changelog line, a
stale docstring, an import-order violation) are yours to apply without
asking. A fix that requires a judgment call is not: changing behavior to
satisfy a test, changing or deleting a test to satisfy the code, relaxing a
type, adding an architecture or lint exception, or editing a documented
contract. For those, stop before applying anything and put the choice to the
user with AskUserQuestion — the candidate fixes as options, each with what it
buys and costs, a recommendation listed first, and any option that
contradicts a CLAUDE.md rule or gameplan flagged as such. Do not weaken a gate
on your own judgment.

## Commit plan

Once the gates are clean, split the change into `fixup!` commits for the
unpushed commits it amends, plus at most one new commit for the rest.

1. **Unpushed range**: `git log --oneline HEAD --not --remotes`. Only these
   commits can be fixup targets; a pushed commit never is. If the range is
   empty, skip to the single new-commit suggestion.
2. **Map hunks to targets**: run the mapper instead of blaming by hand; it
   prints a short table however large the diff is:

   ```bash
   python .claude/skills/land/fixup_map.py --patches "$(mktemp -d)"
   ```

   (`--cached` maps only the staged diff.) It blames each hunk of
   `git diff -U3 HEAD`, follows `fixup!` chains, and keeps in the new commit
   every new or deleted file, every untracked file, and every hunk whose added
   lines name something absent from its target's tree (an import of a module
   the change adds, a call to a name it introduces): squashed into an older
   commit, those would leave it unable to build. A hunk whose blame is pushed
   or spread over several commits falls back to its file's **latest touch**,
   the newest unpushed commit editing that file, and is marked `*`. Blame
   doesn't vouch for a `*` hunk, so offer it only when the target's subject
   fits the hunk (a follow-up to that commit's work); otherwise drop it to the
   new commit. What remains are **fixup candidates**, listed per target with
   `file:line`, and one `<sha>.patch` per target in the patches folder.

   The check is by name only, so read each candidate hunk (and only those)
   before offering it: drop one whose meaning still depends on the change,
   such as an import used only by code the change adds, or a doc line
   describing the new behavior. Decide per hunk, never per target or for the
   change as a whole; offer every self-contained one, even inside a large
   structural change. Edit a target's patch to drop a hunk you rejected.
   The mapper always sends new and untracked files to the new commit; move
   one into a fixup when that fixup's hunks reference it (a script a skill
   edit tells the reader to run), so the target never names a missing file.
3. **Rehearse each target**: confirm the grouped hunks rebase cleanly in a
   throwaway detached worktree in a fresh temp folder — never on the user's
   branch:

   ```bash
   wt="$(mktemp -d)/fixup"                       # new folder every run; never reused
   git worktree add --detach "$wt" HEAD
   cd "$wt"
   git apply --index <patches>/<sha>.patch       # from fixup_map.py --patches
   git commit -q --no-verify --fixup=<target>   # hooks already ran as gates
   GIT_SEQUENCE_EDITOR=: git rebase -q -i --autosquash <oldest-target>~1
   cd -
   ```

   Rehearse all fixup targets together in one worktree (one patch and
   `--fixup` commit per target, one rebase), since squashing one can shift
   another. A rebase that refuses to start (unstaged changes, an empty fixup)
   means the rehearsal itself is broken: fix it, don't call that a conflict. If
   the rebase stops on a conflict, run `git rebase --abort`, move
   the conflicting target's hunks to the new commit, and rehearse again with the
   remaining targets. Leave the worktree where it is: never delete it; the OS clears
   its temp folder (git prunes the stale entry once the folder is gone). Afterwards
   `git status` on the user's tree must be unchanged.
4. **Hand over the commands**: check `git diff --cached --name-status` first.
   The user often stages the change before landing, and the fixup patches
   apply to an index at `HEAD`, so when anything is staged the first line
   starts with `git reset -q` (index only; the working tree keeps every edit).
   Copy the rehearsed patches from the temp folder into the scratchpad so the
   lines name files that outlive the run. Give the commands in this order:
   - **Each fixup first.** Stage exactly its rehearsed hunks from the patch,
     never by `git add -p`, and commit it as a fixup of its target:

     ```bash
     git apply --cached <scratchpad>/fixup-<sha>.patch && git commit --fixup=<sha>
     ```

     One line per target, oldest target first.
   - **Then the new commit.** With only its hunks left, stage everything
     except the untracked scratch docs in one `git add`, using long-form
     exclude pathspecs on one line (the short `:!` form misreads a path
     starting with `_` or `.` as magic), and commit from the message file:

     ```bash
     git add -A -- . ':(exclude)_docs/<scratch>.md' && git commit -F <scratchpad>/commit-new.txt
     ```

   - **Last,** `git rebase -i --autosquash <oldest-target>~1`, where the
     oldest target counts any `fixup!` commits already pending on the branch.

   Before each commit, say what `git status --short` should show. A commit
   subject is at most 50 characters, house tag included; the body is at most
   five `-` bullets, one concept each (not one per file or helper), under 72
   characters, never prose.
   The terminal indents and wraps reply text, so never make the user copy
   commands from the reply: write each commit message to a scratchpad file,
   join the step's commands with `&&` into one line using `git commit -F
   <file>`, put that line on the clipboard with `pbcopy`, and show it in the
   reply only for reference. No heredocs, no scripts to run.

## Report

End with:

- **Verdict**: ready to commit, or not — and if not, exactly what blocks it.
- **What changed**: files touched and the shape of the change, briefly.
- **Gate results**: which gates ran and their outcomes, failures verbatim.
- **Commit plan**: each rehearsed `fixup!` target (sha, subject, and the
  hunks it takes) with its commands, then any remaining hunks under one
  suggested commit message using the house tags seen in `git log` (`[NEW]`,
  `[DEV]`, `[DOCS]`, …), its subject at most 50 characters. Mention any hunks
  dropped from a fixup because the rehearsal conflicted. These are commands for the user to run, never executed
  on their branch.
