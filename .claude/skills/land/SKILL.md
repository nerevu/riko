---
name: land
description: Run riko's full pre-commit gate and get the working tree ready for the user to commit — dependency upgrade, /tidy, prettify, codegen drift, lint --all (which covers docs and docstrings), tests, check-types, verify-types — then report a ready/not-ready verdict with a suggested commit message. Use when the user says "land this", "get this ready to commit", "run the gates", "is this ready to commit?", or wants a change finished and validated. This skill NEVER commits; the user commits themselves.
---

# Land (gate everything, commit nothing)

Get the working tree to a state the user can commit with confidence. Run every
gate, fix what the gates find, and report honestly. **Do not run `git commit`,
`git add`, or any other git write operation** on the user's branch, index, or
working tree — the user owns the commit. The only exceptions are the private
index and throwaway worktree `rehearse_plan.py` uses (see "Commit plan").

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
   subagent (`model: "opus"`, so it never inherits a Fable session's model)
   given the skill text, never as an in-loop grep pass (it skips
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
   terms/literals/deps/bindings/tests/basenames/escapes checks, actionlint, YAML, and every import contract, so do not rerun
   `--docs`, `--docstrings`, `--terms`, `--literals`, `--deps`, `--bindings`, `--tests`, `--basenames`, or `--escapes` separately. It does **not** run the type gate.
5. **Tests**: targeted tests for the touched area first while iterating, then
   the full suite `manage test --ratchet --quiet` before declaring ready —
   in the foreground and alone: no other pytest or `manage` gate may run
   beside it: its thread/pool timing tests and the ~70s run degrade under CPU
   contention, and its own data folder isolates only the coverage file.
   Doctests are tests here — doc examples run under pytest. `--ratchet` fails
   when the run leaves more statements uncovered than the ceiling in
   `pyproject.toml` (`[tool.riko.coverage] uncovered`): cover the new or
   newly-unexecuted lines rather than raising the ceiling (raising it is a
   judgment call for the user). When it lowers the ceiling, that `pyproject.toml`
   diff is part of the change — keep it. The ceiling is measured in the full dev
   environment (`--group dev --all-extras`, Python 3.12).
6. **Types**: `manage lint --check-types` and `manage lint --verify-types`
   (neither is part of `--all`). Always run both: an internal change (for
   example a base class whose types come only from local `typings/` stubs) can
   drop downstream type completeness without touching an exported surface.

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

Once the gates are clean, split the change by concept: `fixup!` commits for the
branch commits it amends, then one focused new commit per remaining concept
(rename, feature, test move, docs sweep, lockfile, ...), never one catch-all.
Staging is the user's approval, not a grouping hint: user-facing code ends up
staged, tests and internal docs stay unstaged, so never infer concepts from it.
Write and rehearse the plan in the main loop with the scripts below; don't hand it
to an agent, which repeats their work by hand for many minutes.

1. **Branch range**: every commit past the branch's merge point, pushed or
   not: the nearest merge-base with `next` or `main` (the mapper finds it;
   `--base REF` overrides). Only these commits can be fixup targets; a commit
   at or before the merge point never is. A pushed target is still a target:
   the autosquash then rewrites published history, so `/wrapup`'s handover
   ends with a force push (`git push --force-with-lease`).
2. **Map hunks to targets**: run the mapper instead of blaming by hand:

   ```bash
   python .claude/skills/land/fixup_map.py --blame-only
   ```

   It blames each hunk of `git diff -U3 HEAD`, follows `fixup!` chains, and
   keeps out of fixups every new, deleted, or untracked file and every hunk
   whose added lines name something absent from its target's tree. With
   `--blame-only` it offers only hunks whose blame points at one branch commit;
   drop the flag to also see `*` latest-touch guesses, worth offering only when
   the target's subject fits. Read each candidate hunk (and only those) before
   offering it, and drop one whose meaning still depends on the change (an
   import used only by new code, a doc line describing new behavior).
3. **Write the plan**: list the change's hunks by id with

   ```bash
   python .claude/skills/land/split_hunks.py list
   ```

   (`-U0` by default, so mixed-concept regions split finely; `path:N` is the
   hunk starting on new-side line `N`; new, deleted, untracked, and binary
   files are whole-file ids). Write a plan file in the scratchpad: a `fixup
   <sha>` or `commit <msg-file>` header per step, oldest fixup target first
   and then the new commits in dependency order, each followed by its ids
   (`path` takes every hunk of a file, `path:N-M` a range, `*` the rest,
   `skip` a step of ids left uncommitted such as untracked scratch docs).
   Group by file first and split a file only when its hunks are different
   concepts. A hunk that names something another hunk introduces goes in or
   after that hunk's step. Generated files (tier indexes, API-surface blocks,
   verb tables) go with the step whose source change regenerates them; the
   coverage-ratchet line in `pyproject.toml` goes in the last step. Message
   files: subject at most 50 characters, house tag included; at most five
   `-` bullets, one concept each, under 72 characters, never prose.
4. **Rehearse it**:

   ```bash
   python .claude/skills/land/rehearse_plan.py <plan> --out <scratchpad>/plan-out --copy
   ```

   It builds every step as a commit in a private index (never touching the
   user's index or tree), refuses a plan where any id is in no step or in two,
   confirms the last tree equals the working tree, runs build checks on each
   step (ruff's undefined/unused names and `import riko`; `--full-checks` adds
   pyright and the import contracts for bisect-safe commits), and replays the
   autosquash in a throwaway worktree. It writes `NN.patch`/`NN.msg`,
   `commands.txt` (always led by `git reset -q`),
   `chain.txt`, and each step's files with `+added/-removed` line counts (plus
   hunk start lines when a step takes only part of a file). Fix the plan and rerun
   until every check and the autosquash pass. Leave its temp folders and
   worktrees where they are; never delete them.
5. **Hand over the commands**: put `chain.txt` on the clipboard (`--copy`)
   and show the step table for reference; the chain stops at the first step
   that fails. Offer step-by-step lines from `commands.txt` instead only when
   asked, and never leave a single step on the clipboard while also handing
   over a chain that starts with it (the chain would re-apply it and fail).
   Say what `git status --short` should show afterwards. Name any unstaged
   user-facing file as not yet reviewed. The chain never depends on the index:
   its patches come from `git diff HEAD` (working tree against `HEAD`) and it
   always starts with `git reset -q`, so the user may stage or unstage files at
   any time after handover. Only a working-tree edit or a new `HEAD` makes the
   chain stale; staging alone never calls for a re-rehearsal. **No rebase**: the
   `fixup!` commits stay pending; `/wrapup` hands over the autosquash as its very
   last step.

## Report

End with:

- **Verdict**: ready to commit, or not — and if not, exactly what blocks it.
- **What changed**: files touched and the shape of the change, briefly.
- **Gate results**: which gates ran and their outcomes, failures verbatim.
- **Commit plan**: the rehearsed step table (each `fixup!` target's sha and
  subject, each new commit's subject from the house tags seen in `git log`,
  `[NEW]`, `[DEV]`, `[DOCS]`, …, and the files each step touches with their line
  counts and partial-hunk lines), the check and
  autosquash results, which chain is on the clipboard, any hunk dropped from a
  fixup and why, and that the autosquash waits for `/wrapup`. These are
  commands for the user to run, never executed on their branch.
- **Script candidates**: a subagent whose completion notice shows a long run (roughly 10+ minutes or 50+
  tool calls) on mechanical, repeatable work, or that wrote its own helper scripts
  into the scratchpad (the tidy
  agent included). Name the task, its duration and tool count, and the script it
  suggests (name, inputs, outputs, home); propose it, never build it unasked.
  Save each candidate's draft (or the agent's own script) in `.claude/skills/drafts/` with a header docstring (purpose, inputs, outputs, origin date), and cite that path in the report and handoff.
