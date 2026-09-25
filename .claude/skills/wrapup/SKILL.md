---
name: wrapup
description: Update riko's internal docs and Claude memory to reflect what landed this session so the user can clear the session without losing state — sweeps _docs/IMPLEMENTED.md, PHASE_CHECKLISTS.md, the owning gameplan, docs/CHANGES.rst, and memory files. Use when the user says "update internal docs", "update the docs so I can clear", "wrap up the session", "prepare for /clear", "sync the docs", or "handoff".
---

# Wrapup (make the session clearable)

Everything durable from this session must survive a `/clear`: as-built docs,
status trackers, changelog, and Claude memory. Sweep each owner exactly once,
respecting what each one is allowed to contain.

## 1. Establish what actually landed

Reconstruct the session's real outcome from evidence, not recollection:
`git status`, `git diff` (staged and unstaged), recent commits, and the
conversation. Distinguish landed work from discussed-but-not-done work —
only the former goes in status docs; the latter may belong in a gameplan or
memory as an open item.

## Idempotency

Wrapup writes, and writes are not safely repeatable — a second pass (or a
mid-session doc edit made while working) means the record may already be
partially current:

- **Check before every write.** Read the target section first: if the fact is
  already recorded, update it in place or leave it — never append a second
  entry saying the same thing. Duplicate CHANGES lines and re-described
  IMPLEMENTED paragraphs are the failure mode.
- **Docs updated during the work count.** If IMPLEMENTED.md, a gameplan, or a
  checklist was already updated as part of the session's work, that owner is
  done — verify it's accurate, don't re-sweep it.
- **Only document this session's work.** If `git diff` shows changes this
  session didn't make (another session's in-flight work), do not describe
  them in status docs and do not "fix" their in-progress doc edits — note the
  overlap in the report instead.
- **Snapshot and memory the same way**: skip the riko-skill snapshot bump if
  the basis is already at HEAD with accurate contents; search existing
  memories (MEMORY.md descriptions) before writing a new file.

A fully-current owner is a valid outcome — report it as "already current",
not as something to re-edit.

## 2. Sweep the owners

Each concept has one semantic owner — update it there and nowhere else:

- **`_docs/IMPLEMENTED.md`** — the as-built companion and single source of
  build completeness. New/changed behavior and mechanism notes go here (this
  is where "how it works" lives; docstrings state only what the caller gets).
- **`_docs/PHASE_CHECKLISTS.md`** — authoritative status. Flip checkboxes and
  status lines only; no prose narratives.
- **The owning gameplan in `_docs/gameplans/`** — update the slice's status
  and any decisions made this session that refine the target. If a decision
  contradicts a gameplan, reconcile explicitly rather than leaving both
  versions standing.
- **`docs/CHANGES.rst`** — user-observable changes only. No private
  implementation-move journaling; internal refactors don't get entries.
- **`_docs/ROADMAP.md`** — only if routing/ownership itself changed.

Hard rules while sweeping:

- **No fix journaling.** A bug fix is a regression test plus a CHANGES line,
  never prose in CLAUDE.md or `_docs/`. An unguarded invariant gets a test,
  not documentation of the trap.
- **No transient references.** Stable UPPERCASE `_docs/` files and CLAUDE.md
  must not cite untracked lowercase scratch docs; gameplans are exempt.
- **CLAUDE.md** changes only for durable cross-cutting invariants or new
  vocabulary — rare.

## 3. Verify

Run `uv run --active python -m riko.cli.manage lint --docs` and fix what it
flags. The docs model is lint-guarded; a wrapup that fails docs lint is not
done.

## 4. Refresh the riko skill snapshot

If the session changed anything described in the riko skill's bundled
references (`~/.claude/skills/riko/references/` — API surfaces, node/edge
families, module locations, invariants, validation commands), update those
snapshot files to match and bump the "Snapshot basis" commit/date line in
`current-state.md` to the current HEAD. A stale snapshot confidently misleads
sessions without live repo access; skip this step only when nothing the
references describe was touched.

## 5. Update Claude memory

Write or refresh memory files (and the `MEMORY.md` index) for durable facts a
fresh session needs: what landed and where, decisions with their why, open
items with their owning gameplan. Update existing memories rather than
duplicating; convert relative dates to absolute; don't record what the repo
already documents.

## 6. Leave the pickup trail

Write the next session's starting point into the rolling handoff memory
(`session-handoff.md` in the memory directory, indexed once in `MEMORY.md`).
Overwrite it each wrapup — it describes only the current frontier, not
history:

- **Where work stopped**: the slice in progress, its owning gameplan/phase,
  and the last completed step.
- **The exact next action**: concrete enough to start cold — the file, the
  function, the command, the failing test. "Continue R4B" is useless;
  "implement `_prepare_execution.build_plan` per execution-semantics §X, then
  unxfail `test_prepare_execution.py::test_plan_ordering`" is a pickup point.
- **Open decisions awaiting the user**, stated as questions with the options
  already framed.
- **Traps discovered but not fixed** — anything the next session would
  otherwise rediscover the hard way.
- Dates absolute, never relative. If everything landed clean with no
  successor work, say exactly that — an empty frontier is also information.

## 7. Report

End with a short manifest: each file updated and the one-line reason, anything
deliberately not updated (and why), and confirmation the session is safe to
clear.
