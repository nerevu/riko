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

## Idempotency and multiple sessions

Landing may run mid-session after some gates already ran, or in several
sessions on the same tree. Gate passes are recorded per tree, not per session,
by `.claude/skills/land/gates.py` (`G` below):

- **Markers.** A pass is stored in `.claude/gate-markers.json` against the
  working tree's content tree id, minus what the gate never reads: nothing for
  tidy, lint, and prettify (Ruff and rumdl); everything but `*.py`, `*.pyi`,
  `pyproject.toml`, `uv.lock`, and `typings/` outside `.claude/` for the two type
  gates; `.claude/`, `_docs/`, `.github/`, and the root `*.md` files for the suite
  and `uncovered` (`docs/` and `README.rst` hold doctests, so they count); and
  `.claude/` for the rest, codegen included (it rewrites generated blocks in
  `_docs/` and `CLAUDE.md`). Staging, committing, an autosquash, `/clear`, or
  another session leaves it valid; any content edit invalidates it, except
  that a skill edit reruns only tidy, lint, and prettify, and a prose edit never
  reruns the type gates. Run each gate through
  `python $G run <gate> [--mutates] [--lock] -- <command>` (or all of `/land`'s
  in order with `python $G all`, which runs each through `run`): it
  prints `skip <gate>` and exits 0 when the gate already passed on this tree
  (from any session), otherwise runs the command and records a pass only when
  it succeeds and the tree did not change during the run, or the only change is
  the coverage ratchet lowering its ceiling lines in `pyproject.toml` (it prints
  `recorded <gate> on tree … (ratchet lowered a ceiling)`). Mutating gates
  (prettify, codegen) pass `--mutates`, which records the tree they left. A fix
  changes the tree id of every gate that reads the fixed file, so those gates
  rerun on their own. For a gate in `/land`'s sequence, `run` refuses a command
  that does not end with that gate's arguments below: it prints `rejected <gate>`,
  exits 64, and runs and records nothing.
- **No waiting, no deadlocks.** Only the full suite and `diff_uncovered.py` take
  `--lock`, a non-blocking OS lock on `riko-gate.lock` in the git common
  directory (shared by every worktree), which the OS drops when the process exits. When
  another session holds it, `run` exits 75 at once (`busy <gate>`): do not
  wait or retry in a loop; finish the other gates and report the suite as
  "busy in another session, rerun `/land`". Nothing else is locked; two
  sessions running other gates at once only duplicate work.
- **Never trust recollection.** A pass you remember but `gates.py` does not
  record (for example one that ran while the tree changed by more than a ratchet
  lowering) is not a pass.
- Before applying any fix (regenerating a file, adding a missing entry,
  correcting a failure), check the current state first: the fix may already
  be in place from this or another session. Re-applying blindly can duplicate
  entries or clobber newer work.
- Note skipped gates in the report with the marker's time and `HEAD`.

## Gate sequence

Order matters. Run from the repo root; `<manage>` is `uv run --active python -m
riko.cli.manage` (the `manage` entry point can collide with mezmorize's) and
`$G` is `.claude/skills/land/gates.py`. After any change to a gate's command,
`python .claude/skills/land/gate_bench.py` times the read-only gates serially and
side by side.

Steps 2–6 run around tidy (step 1). Prettify (and codegen, per step 3) runs in step 1's
setup call, before tidy; `python $G all --read-only` (lint and both type gates) runs in
the background beside the tidy agent. After tidy's report, one command always:
`python $G record tidy && python $G all [--codegen]` (`--codegen` per step 3), in the
foreground with nothing else running beside it, because it contains the suite. `all`
skips every gate already recorded on the tree, so with no tidy edits only the suite
runs, and with edits only the stale gates rerun before it. On a tree tidy already
covered, run `python $G all [--codegen]` once, the same way. `all` runs every gate
through `$G run`, so each gate already recorded on this tree prints `skip`, in three
steps: prettify (which carries tidy's mark to the tree it leaves when tidy was marked
on the tree it started from) and codegen, one at a time; then lint
and both type gates side by side, each gate's output printed whole under a
`--- <gate>` header when it finishes; then the suite alone, only when every earlier
gate passed and was recorded. It stops after the first step with a gate that fails,
is busy, or passes unrecorded (the tree changed during its run), letting the other
gates of that step finish, and ends with one summary line per gate in the order
prettify, codegen, lint, check-types, verify-types, test (`skip`, `pass`,
`pass (unrecorded)`, `fail (<code>)`, `busy`, or `not run`). When it stops, fix
that gate's failures as its step below describes and rerun `all`, which skips the
gates already recorded. `--read-only` runs only the side-by-side step (the other gates
report `not run`) and refuses `--codegen`. Each step's `$G run` line is the fallback
for iterating on one gate alone.

0. **Upgrade dependencies**: `manage upgrade --daily` (not wrapped: `--daily`
   is its own once-a-day marker). It re-resolves `uv.lock` to the
   newest allowed versions and syncs the active environment, so a new ruff,
   pyright, or runtime release breaks here instead of in CI (CI installs the
   lock with `--locked` and never upgrades). A `uv.lock` diff is part of the
   change — keep it, and name upgraded packages in the report. If an upgrade
   breaks a gate, fixing the code is the default; holding a package back is a
   judgment call for the user. `--daily` makes it a no-op when a full upgrade
   already succeeded today, so always run it; never skip it by recollection.
   **When meza's locked version changed** (`git diff -- uv.lock` shows a new
   meza version, from this step or from the change itself), sync
   `_docs/gameplans/upstream-fixes.md` before moving on; the user never edits
   it by hand. Run `uv run --active pytest -p no:cacheprovider --no-cov
   tests/internal/test_upstream.py -rX`. For each unexpected pass: raise the
   `meza>=` floor in `pyproject.toml` to the locked version (users on an older
   meza still need the workaround), delete the workaround the entry names, its
   canary, and the entry, and re-run that area's tests. Then update the entry
   header's floor line, and set each remaining entry's **Upstream branch/PR**
   line from `git -C ~/Documents/Projects/meza branch -a` and `gh pr list -R
   reubano/meza` (a merged or deleted branch reads "none yet" again). Name
   every deleted workaround in the report. The command itself runs in step 1's setup
   call.

1. **Tidy**: run `.claude/skills/tidy/SKILL.md` over the change in a fresh `implementer`
   subagent (`model: "opus"`, so it never inherits a Fable session's model), never as an
   in-loop grep pass. First, one setup Bash call runs `manage upgrade --daily` (step 0),
   `python .claude/skills/wrapup/repoint_hashes.py`,
   `python $G run prettify --mutates -- <manage> prettify` (step 2), then
   `python $G run codegen --mutates -- <manage> codegen --all` when step 3 applies, then
   `python $G check tidy` and `python .claude/skills/land/require_agents.py`. Prettify
   and codegen go before tidy so they never write a file tidy is editing, and before
   `check tidy` so the check judges the tree they left; nothing records tidy here.
   `repoint_hashes.py` repoints any doc, memory, or `CLASS_HISTORY` citation an
   autosquash or rebase rewrote, so the user never does; its edits join the change. It
   exits 1 only for a citation nothing resolves: resolve that line (rewrite it as an
   `old → new` record, which it keeps, or describe the dropped commit) and rerun the
   setup call. When
   `check tidy` exits 0, skip the agent (tidy already ran on this tree, in any session)
   and run `python $G all [--codegen]` in the foreground; when `require_agents.py`
   fails, stop and report its output (the user-level agent definitions are missing);
   otherwise, in the next response, launch the agent and, in the same response,
   `python $G all --read-only` with `run_in_background`. The brief opens "Follow
   `.claude/skills/tidy/SKILL.md`; `/land` is the caller, so skip its verify and record
   steps; run `python .claude/skills/land/gates.py scope tidy --leads` as your first
   call after reading the skill", and the agent reads that file itself as its first
   action. Never `cat` or `Read` the tidy skill in the main loop: at 200k context that
   costs several times what the agent's own read does, and the measurement tooling
   attributes the agent run by the `Follow` line, not the pasted body. The brief ends
   with the mid-run self-check (past about 10 minutes or 100k tokens with mechanical
   work left: pause, report, and name the helper script; afterwards inspect any scripts
   it wrote for itself and promote, fold, park in `.claude/skills/drafts/`, or drop
   each; a dropped or folded script moves to `.claude/skills/disposed/`, which is
   git-ignored and cleared only by the user, never deleted by an agent). Its mechanical
   fixes join the change while the background lint and type gates run, so those gates
   may end `pass (unrecorded)` or rerun after tidy's edits (a changed tree invalidates
   their markers); that is expected, not a failure. Once tidy has reported, run
   `python $G record tidy && python $G all [--codegen]`: the suite always runs after
   the other gates, and only the gates tidy's edits invalidated rerun before it. Its
   judgment questions go to the user now, and phase-owned findings go through
   `/triage`.

2. **Prettify first, always**: the gate sequence's first gate, run in step 1's setup
   call before tidy. Alone: `python $G run prettify --mutates -- <manage> prettify`.
   Never hand-fix formatting-class lint errors — formatting is prettify's job, before
   any linter runs. A prettify pass carries tidy's mark to the tree it leaves when tidy
   was marked on the tree it started from (a skipped prettify leaves the mark alone):
   tidy skips its own prettify and record under `/land`, so once land has recorded
   tidy after its report, a format-only change does not reopen tidy's scope for the
   next session, and a prettify before tidy has run marks nothing.

3. **Codegen drift**: if the change touched anything with a generated artifact
   (configs, module names/ids, API surface blocks, pipeline fixtures, the planning
   TOMLs `_docs/gameplans/*.toml` or their Markdown lead-ins, which regenerate the
   `<!-- planning-* -->` blocks), pass
   `--codegen` to `all` (alone:
   `python $G run codegen --mutates -- <manage> codegen --all`) and check `git diff`
   on the generated files. A diff
   there is part of the change, not noise — keep it. Never hand-edit generated
   files.

4. **Lint**: in the gate sequence; alone, `python $G run lint -- <manage> lint --all`.
   It already runs Ruff, rumdl, the RST/docs/docstring/
   terms/literals/deps/bindings/tests/basenames/escapes/helpers/ownership checks,
   actionlint, YAML, and every import contract, so do not rerun `--docs`,
   `--docstrings`, `--terms`, `--literals`, `--deps`, `--bindings`, `--tests`,
   `--basenames`, `--escapes`, `--helpers`, or `--ownership` separately. It does
   **not** run the type gate. When a ratcheted check that prints its sites as
   `path:line:` (the `--tests` ceilings) trips, pipe that check's output to
   `python $G scope lint --new-sites -`: it keeps only the sites on lines added since
   lint last passed, separating the change's new violations from existing ones.

5. **Tests**: targeted tests for the touched area first while iterating, then the full
   suite, in the gate sequence or alone with
   `python $G run test --lock -- <manage> test --ratchet --quiet --parallel`, before
   declaring ready — in the foreground and alone: no other pytest or `manage` gate may
   run beside it: its thread/pool timing tests and the ~25s run degrade under CPU
   contention, and its own data folder isolates only the coverage file. Doctests are
   tests here — doc examples run under pytest. `--ratchet` fails when the run leaves
   more statements uncovered than the ceiling in `pyproject.toml`
   (`[tool.riko.coverage] uncovered`): cover the new or newly-unexecuted lines rather
   than raising the ceiling (raising it is a judgment call for the user). To find them,
   run this alone, like the suite:

   ```bash
   python $G run uncovered --lock -- python .claude/skills/land/diff_uncovered.py --baseline-ref HEAD
   ```

   It lists the change's uncovered lines and each file whose missing count moved, which
   catches a line outside the diff that lost coverage. It exits non-zero when any
   changed line is uncovered. Never read the repo-root `.coverage`; it can be stale.
   When it lowers the ceiling, that `pyproject.toml` diff is part of the change — keep
   it. The ceiling is measured in the full dev environment (`--group dev --all-extras`,
   Python 3.12).

6. **Types**: the gate sequence's two type gates, run beside lint; alone,
   `python $G run check-types -- <manage> lint --check-types` and
   `python $G run verify-types -- <manage> lint --verify-types`
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

1. **Branch range**: every commit past the branch's merge point, pushed or not: the
   nearest merge-base with `next` or `main` (the mapper finds it; `--base REF`
   overrides). Only these commits can be fixup targets; a commit at or before the merge
   point never is. A pushed target is still a target: the autosquash then rewrites
   published history, so `/wrapup`'s handover ends with a force push
   (`git push --force-with-lease`). "Already pushed" is never a reason for a new commit,
   and never a caveat to raise. A bug fix goes to the commit that introduced the bug,
   with its regression test in the same fixup, even when blame points elsewhere. Take
   the introducing commit from the `/triage` disposition, or find it with
   `git log -S`/`-G`. The fix is a new commit only when that commit is at or before the
   merge point.

   An already-committed fix that belongs to an earlier branch commit becomes a
   `fold <target> <mover>` plan step (or `--fold TARGET:MOVER[@ID,...]`), listing the
   mover's ids from `split_hunks.py list --base M^ --head M` (none for the whole
   commit). `fixup_map.py --fixes` lists leads: the branch commits that wrote the lines
   each `[FIX]` commit removed. A lead is not a verdict (refactor moves show up too), so
   confirm the bug existed at the target first. `rehearse_plan.py` replays the folds and
   the pending fixups in one autosquash pass in a throwaway worktree; a conflict stops
   it unless `--resolve PATH=ours|theirs|max` picks a side. The handover is
   `git reset --keep <tip>` (plus `git push --force-with-lease` when pushed), and
   `/wrapup`'s separate autosquash is then not needed unless the plan also has
   working-tree fixups, which stay pending as usual. A `reword <sha> <msg-file>` step
   (or `--reword SHA=FILE`) rewrites a branch commit's message in the same rehearsal,
   such as a fold target's subject or a trimmed mover's.

2. **Map hunks to targets**: run the mapper instead of blaming by hand, together
   with step 3's hunk list in one Bash call:

   ```bash
   python .claude/skills/land/fixup_map.py --blame-only
   python .claude/skills/land/split_hunks.py list --body 12
   ```

   It blames each hunk of `git diff -U3 HEAD`, follows `fixup!` chains, and
   keeps out of fixups every new, deleted, or untracked file and every hunk
   whose added lines name something absent from its target's tree. With
   `--blame-only` it offers only hunks whose blame points at one branch commit;
   drop the flag to also see `*` latest-touch guesses, worth offering only when
   the target's subject fits. Read each candidate hunk (and only those) before
   offering it, from its `--body` excerpt, and drop one whose meaning still depends
   on the change (an import used only by new code, a doc line describing new
   behavior). Read a hunk with `git diff` only when its excerpt does not settle its
   concept.

3. **Write the plan**: the `split_hunks.py list --body 12` output from step 2's call
   lists the change's hunks by id (`-U0` by default, so mixed-concept regions split
   finely; `path:N` is the hunk starting on new-side line `N`; new, deleted, untracked,
   and binary files are whole-file ids; `--body N` prints up to `N` of each hunk's lines
   under it, for sorting many hunks without a `git diff` per file). Write a plan file in
   the scratchpad: a `fixup <sha>` or `commit <msg-file>` header per step, oldest fixup
   target first and then the new commits in dependency order, each followed by its ids
   (`path` takes every hunk of a file, `path:N-M` a range, `*` the rest, `skip` a step
   of ids left uncommitted such as untracked scratch docs). For a change of more than a
   few dozen hunks, write a TOML rules file in the scratchpad instead (buckets in plan
   order, each a `message`, a `fixup` sha, or `skip`; ordered
   `ids`/`path`/`body`/`swaps` rules; a `default` bucket; the script's docstring has an
   example) and let
   `python .claude/skills/land/bucket_plan.py <rules> --out <scratchpad>/plan` write
   `plan.txt` and the message files; it takes `--base REF` like `split_hunks.py`. Refine
   the rules and rerun rather than hand-editing `plan.txt`. Either way, group by file
   first and split a file only when its hunks are different concepts. A file that one
   branch commit wholly rewrote is fixed up whole to that commit, its pre-branch-blame
   hunks included. A hunk that names something another hunk introduces goes in or after
   that hunk's step. Generated files (tier indexes, API-surface blocks, verb tables,
   planning blocks) go with the step whose source change regenerates them. The
   coverage-ratchet line in `pyproject.toml` goes with the step whose tests or code
   moved it:
   `diff_uncovered.py --baseline-ref HEAD` names each file whose missing count changed.
   Put it elsewhere only for a stated reason, such as a later branch commit that also
   changes the ceiling, and say why. Message files: subject at most 50 characters, house
   tag included, and true to the step's diff; no body when the subject says it all
   (never a bullet that restates it), else at most five `-` bullets, one concept each,
   under 72 characters, never prose. A bullet for something the subject does not imply
   starts with "Also".

4. **Rehearse it**:

   ```bash
   python .claude/skills/land/rehearse_plan.py <plan> --out <scratchpad>/plan-out --copy
   ```

   It builds every step as a commit in a private index (never touching the
   user's index or tree), refuses a plan where any id is in no step or in two,
   confirms the last tree equals the working tree, runs build checks on each
   step (ruff's undefined/unused names and `import riko`; `--full-checks` adds
   `lint --all`, `--verify-types`, and full-project pyright on the step's own
   tree for bisect-safe commits; `--tests` runs the suite with the ratchet on each
   step, one at a time, and skips every suite after the first that fails, so run
   it alone), and replays the
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
   last step. The exception is a fold: it hands over `git reset --keep <tip>`, whose
   tip already squashes the pending fixups in the same pass.

## Report

End with:

- **Verdict**: ready to commit, or not — and if not, exactly what blocks it.
- **What changed**: files touched and the shape of the change, briefly.
- **Gate results**: which gates ran and their outcomes, failures verbatim,
  and the suite count (`python $G summary test`, recorded even when this
  session skipped the suite).
- **Commit plan**: the rehearsed step table (each `fixup!` target's sha and subject,
  each new commit's subject from the house tags seen in `git log`, `[NEW]`, `[DEV]`,
  `[DOCS]`, …, where `[DOCS]` means user-facing docs only and `_docs/`, CLAUDE.md, and
  skills take `[DEV]`, and the files each step touches with their line counts and
  partial-hunk lines), the check and autosquash results, which chain is on the
  clipboard, any hunk dropped from a fixup and why, and that the autosquash waits for
  `/wrapup` (unless a fold's `git reset --keep <tip>` already squashed it). These are
  commands for the user to run, never executed on their branch.
- **Script candidates**: candidates come from the main loop as much as from subagents:
  any helper script written this session into the scratchpad or `/tmp` (inline heredoc
  scripts included), any scan, count, or cross-check run by hand three or more times,
  and any subagent whose completion notice shows a long run (roughly 10+ minutes or 50+
  tool calls) on mechanical, repeatable work or that wrote its own helper scripts (the
  tidy agent included). Name the task, its duration and tool count, and the script it
  suggests (name, inputs, outputs, home); propose it, never build it unasked. Save each
  candidate's draft (or the agent's own script) in `.claude/skills/drafts/` with a
  header docstring (purpose, inputs, outputs, origin date), and cite that path in the
  report and handoff. Then put every draft saved this session to the user with
  AskUserQuestion — promote (as a skill helper, a pyright/lint gate, or a new lint
  module), defer with a trigger, or drop (a dropped or folded draft moves to
  `.claude/skills/disposed/`, never deleted) — with measured numbers from running it,
  and record the ruling in the handoff; a saved draft is never left undecided.
