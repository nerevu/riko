---
name: wrapup
description: Update riko's internal docs and Claude memory to reflect what landed this session so the user can clear the session without losing state — sweeps _docs/IMPLEMENTED.md, PHASE_CHECKLISTS.md, the owning gameplan, docs/CHANGES.rst, and memory files. Use when the user says "update internal docs", "update the docs so I can clear", "wrap up the session", "prepare for /clear", "sync the docs", or "handoff".
---

# Wrapup (make the session clearable)

Everything durable from this session must survive a `/clear`: as-built docs,
status trackers, changelog, Claude memory, and the pickup trail. Sweep each
owner exactly once, respecting what each one is allowed to contain.

## Turn budget

Wrapup runs at the end of a session, when the context is already several
hundred thousand tokens. Every tool round trip re-reads all of it, so the cost
of this skill is the number of turns, not the size of the files. Budget: **seven
turns** — tidy, evidence, plan, edits, verify, memory, report. Structure the work so
each phase is one response:

- **Never read a whole owner file.** IMPLEMENTED.md, CHANGES.rst,
  PHASE_CHECKLISTS.md, and the gameplans are tens of KB each. Use `grep -n`
  and `sed -n 'A,Bp'` for the section you will touch, inside the evidence batch.
- **Batch, don't serialize.** Independent tool calls go in one response: all
  evidence in one Bash call, all Edit/Write calls together, one lint run.
- **Docs and memory only — except tidy.** Wrapup itself never edits code or
  tests and never runs prettify, the test suite, `lint --all`, or
  `check-types` — that is `/land` and `/go` work. The one exception is step 0:
  the tidy subagent fixes code, docs, and tests and runs its own targeted
  checks. Any other code change that seems necessary becomes an open item in
  the handoff, not an edit.

## 0. Tidy (one subagent)

Every agent brief ends with the mid-run self-check: past about 10 minutes or
100k tokens with mechanical, repeated work left, stop at a consistent point, run
the gates, and report what is done, what is left, and the helper script that
would speed up the rest (run `date` at the start and between items). About 10
minutes in, send it a non-stopping status ping; pause one that is grinding,
build the script, then resume it. When an agent finishes, inspect any scripts it wrote for itself (scratchpad,
`/tmp`, new untracked files) and decide for each: promote it to a shared helper,
fold it into an existing one,
park it in `.claude/skills/drafts/` as an unapproved candidate, or drop it; report the verdict.

Launch one fresh `general-purpose` agent with `model: "opus"` (not a fork — it
needs only the diff, not this session's context; pin the model so it never
inherits a Fable session's) with: "Follow
`.claude/skills/tidy/SKILL.md` in the repo at the current working directory. You
cannot ask the user: apply mechanical fixes, and return phase-owned findings
and framed judgment questions instead of deciding them." Wait for its report
before step 1, so the evidence batch sees the tidied tree. Its judgment
questions join step 2's single AskUserQuestion call; its phase-owned findings
and "tidy edits not yet through the full suite" (when it edited anything) go
in the handoff for the next `/land`. If tidy reports nothing to tidy, move on.

## 1. Gather evidence (one Bash call)

Reconstruct the session's real outcome from evidence, not recollection, in a
single command batch:

- `git status --short`, `git diff --stat` (staged and unstaged), and
  `git log --oneline -8`.
- Pending fixups: `git log --format='%h %s' HEAD --not --remotes`. Each
  `fixup! <subject>` line names its target by subject. A target may already be
  pushed, so find it in `git log --format='%h %s' HEAD`, not in that range; the
  oldest target is the base for step 5's rebase line.
- For each owner you expect to touch, the relevant section only: `grep -n` for
  the slice/phase/feature names in `_docs/IMPLEMENTED.md`,
  `_docs/PHASE_CHECKLISTS.md`, the owning gameplan, `docs/CHANGES.rst`
  (top entry block), and `_docs/ROADMAP.md`.
- The memory index (`MEMORY.md` is already in context — grep the memory
  directory only for the specific file you will update) and the current
  `session-handoff.md`.
- `grep -n` in `~/.claude/skills/riko/references/` for the symbols/paths the
  session changed, plus the "Snapshot basis" line in `current-state.md`.

Distinguish landed work from discussed-but-not-done work — only the former
goes in status docs; the latter belongs in a gameplan or memory as an open item.
If `git diff` shows changes this session didn't make (another session's
in-flight work), do not describe them in status docs and do not "fix" their
in-progress doc edits — note the overlap in the report instead.

## 2. Plan every write (one turn, no tools)

Decide, per owner, one of: **update in place**, **add**, or **already
current**. Writes are not safely repeatable, so the evidence decides:

- If the fact is already recorded, update it in place or leave it — never
  append a second entry saying the same thing. Duplicate CHANGES lines and
  re-described IMPLEMENTED paragraphs are the failure mode.
- Docs updated during the work count. If an owner was already updated as part
  of the session's work, it is done — verify it's accurate, don't re-sweep it.
- A fully-current owner is a valid outcome — report it as "already current".
- Skip the riko-skill snapshot update if the basis is already at HEAD and the
  sections describing what changed are accurate.

Owner semantics — each concept has one owner, update it there and nowhere else:

- **`_docs/IMPLEMENTED.md`** — the as-built companion and single source of
  build completeness. New/changed behavior and mechanism notes go here (this
  is where "how it works" lives; docstrings state only what the caller gets).
- **`_docs/PHASE_CHECKLISTS.md`** — authoritative status. Flip checkboxes and
  status lines only; no prose narratives.
- **The owning gameplan in `_docs/gameplans/`** — update the slice's status
  and any decisions made this session that refine the target. If a decision
  contradicts a gameplan, reconcile explicitly rather than leaving both
  versions standing — and the reconciliation is the user's call, not yours:
  ask with AskUserQuestion which side is authoritative (keep the gameplan and
  record the session's deviation as an open item, or amend the gameplan to
  the new decision), with a recommendation listed first. The same applies
  when it is unclear whether something counts as landed or merely discussed:
  ask rather than guess which status doc it belongs in. Batch every such
  question into a single AskUserQuestion call in this phase.
- **`docs/CHANGES.rst`** — user-observable changes only. No private
  implementation-move journaling; internal refactors don't get entries.
- **`_docs/ROADMAP.md`** — only if routing/ownership itself changed.
- **riko skill snapshot** (`~/.claude/skills/riko/references/`) — only if the
  session changed something the references describe (API surfaces, node/edge
  families, module locations, invariants, validation commands). Edit the section
  that describes the changed fact in place — rewrite or delete the stale
  statement — then set the "Snapshot basis" line to HEAD, the date, and the gate
  results. The basis line holds only those three things: never append session
  notes or "supersedes any conflicting statement below" text to it, since a
  reader who jumps to one section then gets the stale version. A stale snapshot
  confidently misleads sessions without live repo access.

Hard rules:

- **No fix journaling.** A bug fix is a regression test plus a CHANGES line,
  never prose in CLAUDE.md or `_docs/`. An unguarded invariant gets a test,
  not documentation of the trap.
- **No transient references.** Stable UPPERCASE `_docs/` files and CLAUDE.md
  must not cite untracked lowercase scratch docs; gameplans are exempt.
- **CLAUDE.md** changes only for durable cross-cutting invariants or new
  vocabulary — rare.

## 3. Apply the doc edits (one response)

Issue every Edit for `_docs/`, `docs/CHANGES.rst`, and the skill snapshot in
one response. Each edit anchors on the exact lines the evidence batch showed;
if an anchor is uncertain, widen the grep in step 1 rather than reading the
file.

## 4. Verify (one Bash call)

Run `uv run --active python -m riko.cli.manage lint --docs` and fix what it
flags. The docs model is lint-guarded; a wrapup that fails docs lint is not
done. A fix here is one extra Edit response followed by one re-run.

## 5. Update memory and leave the pickup trail (one response)

Write or refresh memory files and the `MEMORY.md` index together, in one
response, for durable facts a fresh session needs: what landed and where,
decisions with their why, open items with their owning gameplan. Update
existing memories rather than duplicating; convert relative dates to absolute;
don't record what the repo already documents.

Overwrite the rolling handoff memory (`session-handoff.md`, indexed once in
`MEMORY.md`) in the same response — it describes only the current frontier,
not history:

- **Where work stopped**: the slice in progress, its owning gameplan/phase,
  and the last completed step.
- **The exact next action**: concrete enough to start cold — the file, the
  function, the command, the failing test. "Continue R4B" is useless;
  "implement `_prepare_execution.build_plan` per execution-semantics §X, then
  unxfail `test_prepare_execution.py::test_plan_ordering`" is a pickup point.
- **Open decisions awaiting the user**, stated as questions with the options
  already framed.
- **Traps discovered but not fixed** — anything the next session would
  otherwise rediscover the hard way, including any code change wrapup
  identified but deliberately did not make.
- Dates absolute, never relative. If everything landed clean with no
  successor work, say exactly that — an empty frontier is also information.

If step 1 found pending `fixup!` commits, issue in the same response one Bash
call that puts the autosquash line on the clipboard with `pbcopy`:

```bash
git rebase -i --autosquash --autostash <oldest-target>~1
```

`--autostash` lets it run while wrapup's doc edits are still uncommitted. When
a target was already pushed (`git branch -r --contains <target>` is non-empty),
the rebase rewrites published history: append `&& git push --force-with-lease`
to the clipboard line and say so in the report. In
the handoff, record the fixups as "pending autosquash" with that line, so a
session that starts before the user runs it knows to.

## 6. Report

End with a short manifest: tidy's fixes and open findings, each file updated
and the one-line reason, anything deliberately not updated (and why), the
number of turns used against the seven-turn budget, and confirmation the session
is safe to clear, and any **script candidates**: a subagent this session whose
completion notice shows a long run (roughly 10+ minutes or 50+ tool calls) spent on
mechanical, repeatable work (slicing or replaying diffs, rebuilding tables, bulk
renames, rehearsing commits), or that wrote its own helper scripts into the
scratchpad. Name each one's task, duration, and tool count, and the script it
suggests (name, inputs, outputs, and home, such as beside the skill that launched
the agent). Propose them only; build one when the user agrees.
Save each candidate's draft (or the agent's own script) in `.claude/skills/drafts/` with a header docstring (purpose, inputs, outputs, origin date), and cite that path in the report and handoff. Judgment work
(design, review, triage) is never a candidate. When fixups are pending, the manifest's last line is the
rebase step: the user runs the clipboard line (shown for reference) only now,
after wrapup has finished. `/land` deliberately leaves this step to wrapup.
