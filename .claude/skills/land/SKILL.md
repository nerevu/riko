---
name: land
description: Run riko's full pre-commit gate and get the working tree ready for the user to commit — prettify, lint --all, tests, codegen drift, docs lint — then report a ready/not-ready verdict with a suggested commit message. Use when the user says "land this", "get this ready to commit", "run the gates", "is this ready to commit?", or wants a change finished and validated. This skill NEVER commits; the user commits themselves.
---

# Land (gate everything, commit nothing)

Get the working tree to a state the user can commit with confidence. Run every
gate, fix what the gates find, and report honestly. **Do not run `git commit`,
`git add`, or any other git write operation** — the user owns the commit.

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
3. **Lint**: `manage lint --all` (Ruff + import contracts + the standard
   suite), then `manage lint --docs` if `_docs/` or user docs changed, and
   `manage lint --docstrings` if docstrings changed.
4. **Tests**: targeted tests for the touched area first while iterating, then
   the full suite `manage test --no-cov --quiet` before declaring ready.
   Doctests are tests here — doc examples run under pytest.
5. **Types** (when the change touches typed surfaces or public APIs):
   `manage lint --check-types`; add `--verify-types` for changes to exported
   surfaces.

Fix real failures properly (root cause, not suppression), rerun the affected
gate, and repeat until clean. If something cannot be fixed within the change's
scope, stop and report it as a blocker — do not paper over it.

## Report

End with:

- **Verdict**: ready to commit, or not — and if not, exactly what blocks it.
- **What changed**: files touched and the shape of the change, briefly.
- **Gate results**: which gates ran and their outcomes, failures verbatim.
- **Suggested commit message** using the house tags seen in `git log`
  (`[NEW]`, `[DEV]`, `[DOCS]`, `fixup! <target>` for amendments to unpushed
  work) — as text for the user to use, never executed.
