---
name: land
description: Run riko's full pre-commit gate and get the working tree ready for the user to commit — prettify, codegen drift, lint --all (which covers docs and docstrings), tests, check-types — then report a ready/not-ready verdict with a suggested commit message. Use when the user says "land this", "get this ready to commit", "run the gates", "is this ready to commit?", or wants a change finished and validated. This skill NEVER commits; the user commits themselves.
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

- Every gate is safe to rerun (prettify, codegen, lint, and tests are all
  stateless checks), so rerunning is never wrong — only sometimes wasteful.
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

1. **Prettify first, always**: `manage prettify`. Never hand-fix
   formatting-class lint errors — formatting is prettify's job, before any
   linter runs.
2. **Codegen drift**: if the change touched anything with a generated artifact
   (configs, module names/ids, API surface blocks, pipeline fixtures), run
   `manage codegen --all` and check `git diff` on the generated files. A diff
   there is part of the change, not noise — keep it. Never hand-edit generated
   files.
3. **Lint**: `manage lint --all`. It already runs Ruff, the RST/docs/docstring
   checks, actionlint, YAML, and every import contract, so do not rerun
   `--docs` or `--docstrings` separately. It does **not** run the type gate.
4. **Tests**: targeted tests for the touched area first while iterating, then
   the full suite `manage test --no-cov --quiet` before declaring ready.
   Doctests are tests here — doc examples run under pytest.
5. **Types**: `manage lint --check-types` (never part of `--all`); add
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
2. **Map hunks to targets**: for each hunk in `git diff -U3 HEAD`, run
   `git blame -l -L <start>,<end> HEAD -- <file>` over the lines it removes or
   modifies (for a pure addition, over its context lines). The hunk's target is
   the commit blame names, when every blamed line comes from the **same
   unpushed** commit. If that commit is itself a `fixup! X`, target `X`. Hunks
   with mixed, pushed, or uncommitted blame belong to the new commit.
3. **Rehearse each target**: confirm the grouped hunks rebase cleanly in a
   throwaway detached worktree under the scratchpad — never on the user's
   branch:

   ```bash
   git worktree add --detach <scratch>/fixup HEAD
   cd <scratch>/fixup
   git apply --index <hunks-for-target>.patch   # split `git diff` at @@ headers
   git commit -q --no-verify --fixup=<target>   # hooks already ran as gates
   GIT_SEQUENCE_EDITOR=: git rebase -q -i --autosquash <oldest-target>~1
   cd - && git worktree remove --force <scratch>/fixup
   ```

   Rehearse all fixup targets together in one worktree (one patch and
   `--fixup` commit per target, one rebase), since squashing one can shift
   another. A rebase that refuses to start (unstaged changes, an empty fixup)
   means the rehearsal itself is broken: fix it, don't call that a conflict. If
   the rebase stops on a conflict, run `git rebase --abort`, move
   the conflicting target's hunks to the new commit, and rehearse again with the
   remaining targets. Remove the worktree whatever the outcome. Afterwards
   `git status` on the user's tree must be unchanged.
4. **Hand over the commands**: for each target that rehearsed cleanly, give the
   user `git add -p <files>` (naming the hunks to stage), `git commit
   --fixup=<sha>`, and finally `git rebase -i --autosquash <oldest-target>~1`.
   Then give the new commit, if any, with its suggested message.

## Report

End with:

- **Verdict**: ready to commit, or not — and if not, exactly what blocks it.
- **What changed**: files touched and the shape of the change, briefly.
- **Gate results**: which gates ran and their outcomes, failures verbatim.
- **Commit plan**: each rehearsed `fixup!` target (sha, subject, and the
  hunks it takes) with its commands, then any remaining hunks under one
  suggested commit message using the house tags seen in `git log` (`[NEW]`,
  `[DEV]`, `[DOCS]`, …). Mention any hunks dropped from a fixup because the
  rehearsal conflicted. These are commands for the user to run, never executed
  on their branch.
