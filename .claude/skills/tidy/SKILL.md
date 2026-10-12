---
name: tidy
description: Keep riko's repo health from decaying between big cleanups — check everything changed since the last tidy for rule violations, naming/vocabulary collisions, dead weight, loose ends, changelog/journaling slips, and doc drift, then fix the mechanical ones, route phase-owned ones to /triage, and ask about judgment calls. Runs automatically from /land (before the gates) and /wrapup (first step); also use when the user says "tidy", "health check", "check for cruft", "does this follow the rules?", or "check for collisions".
---

# Tidy (conformance and cruft, every session)

Cruft that is caught when it is introduced costs one edit; cruft that piles up
costs a repo-wide audit later. Tidy checks the change against riko's written
rules and fixes what it finds, so the pile never forms.

This file must work for a fresh agent with no session context. Everything it
needs is the diff and the rule files named below.

## 1. Resolve the scope

The marker `.claude/tidy-marker` (untracked, survives `/clear`) holds two
lines from the last tidy: the `HEAD` sha and the working-tree fingerprint
`(git diff HEAD; git ls-files --others --exclude-standard; git ls-files -z --others --exclude-standard | xargs -0 git hash-object) | git hash-object --stdin`
(hashes untracked file names and contents, so a new, renamed, or edited scratch doc re-triggers tidy).
If both still match, report "nothing to tidy" and stop. Otherwise the scope
is everything changed since that sha:

- marker present and an ancestor of `HEAD` (`git merge-base --is-ancestor`):
  `git diff <sha>` plus untracked files (`git ls-files --others --exclude-standard`);
- marker missing or not an ancestor (after an autosquash rebase): the unpushed
  commits (`git log HEAD --not --remotes`, the range `/land` uses) diffed from
  the parent of the oldest one, plus the working tree and untracked files; with
  no unpushed commits, the working tree alone.

If the scope is empty, write the marker and stop. A
wholesale run ("tidy the repo") takes every tracked file and fans out one
read-only agent per top-level package, then applies fixes centrally.

Also pull in the **touched neighborhood**: callers and docs of every symbol the
diff renamed, removed, or changed in meaning (`grep -rn` across `riko/`,
`tests/`, `docs/`, `README.rst`, `CONTRIBUTING.rst`, `examples/`, `_docs/`).

## 2. Load the rules (one batch)

- `CLAUDE.md` — cross-cutting invariants, coding style, verb table,
  `StrEnum`/`Literal`, coroutine prefix, `pipeline`/`flow`, workflow type names.
- `_docs/DOCUMENTATION_STANDARD.md` — Reserved terms, no internal jargon,
  doctest rules, docstring rules.
- `_docs/gameplans/implementation-sequence.md` and the topical gameplan for
  the touched area — to tell an owned gap from a defect.

Settled exceptions are **not findings**: identifiers the Reserved terms rows
say are kept (`catalog_names`, `source=`/`SourceLike`, callable-sense "pipe",
the `*_key` conf names, `ModuleStore`), wording a pending phase replaces (the
`Sinks` category, send/receive "target"), and gameplans keeping older wording
until touched.

## 3. Check

For each file in scope, and only the lines the change introduced or the
neighborhood it affects:

1. **Vocabulary and collisions** — every new identifier, term, heading, error
   message, or concept is checked against the Reserved terms table, the
   supported names in `riko/base/_api_surface.py`, and existing names
   (`grep -rnw`). A collision is a new name that already means something else,
   or an existing riko term used in another sense. A use the "say this instead"
   column rules out is a violation.
2. **Naming conventions** — function names follow the verb table (a `get` that
   loads, a `normalize` that is not idempotent, a precondition not named
   `require_*`); `a`/`_a` prefix only with a sync twin; `StrEnum` vs `Literal`
   per CLAUDE.md; `pipeline` for a `Pipeline`, `flow` only for a `Workflow`.
3. **Structure and dead weight** (riko rules only; `/simplify` owns generic
   quality) — a helper duplicating a shared one (`partition`, `map_values`,
   `maybe_aclosing`, `ROOT_DIR`/`PACKAGE_DIR`); a field, parameter default, or
   type nothing reads; a helper defined below its first caller; a module or
   import in the wrong layer; a parameter narrowed to its one caller's shape.
4. **Idioms** — truthiness where `is None` is required, `cast` where narrowing
   works, more than one `return`, comments that restate code, a new `noqa` or
   type ignore with no reason.
5. **Loose ends** — a new TODO with no owner; a new `NotImplementedError` stub
   with no tripwire; a strict xfail whose owning phase has landed; phase codes
   in xfail reasons, test names, docstrings, comments, or runtime messages.
6. **Changelog and journaling** — a `docs/CHANGES.rst` bullet that is not a
   user-visible change against the last release, a "gained/now" delta where the
   unreleased bullet should be edited, a missing bullet for a user-visible
   change, fix narratives in CLAUDE.md or `_docs/`, per-release renames in
   `docs/MIGRATION.rst`, untracked scratch docs cited from stable docs.
7. **Doc drift** — docstrings, RST, README, gameplans, CLAUDE.md, or the
   `_docs/KEY_PATHS.md`/`INTERNALS.md` maps still describing a name or behavior
   the change altered; doctests that rebind a name or reuse another section's
   state; docstrings that explain mechanism instead of what the caller gets.
8. **Doc hygiene** — duplicated table rows or sections, broken cross-references
   the docs lint does not cover, `_docs/` paths in shipped text.

Verify every finding against the code before acting on it; drop what you
cannot substantiate.

## 4. Act

Sort each verified finding into one bucket:

- **Mechanical** — one right answer under a written rule (a banned phrase, a
  stale reference, a duplicate row, a docstring naming the wrong type, a dead
  default): fix it now.
- **Phase-owned** — a pending gameplan phase owns the behavior: do not fix;
  hand it to `/triage` (tripwire + gameplan note).
- **Judgment** — a rename of a public or released name, a new reserved term,
  a behavior change, deleting something that may be used: ask with one
  batched AskUserQuestion (lists, not tables), recommendation first, each
  option saying what it buys and forecloses. Running as a subagent without
  AskUserQuestion, return these framed questions instead of deciding them.

Then check whether any finding class appeared more than once in this run, or
matches a phrase the Reserved terms table already rules out. If it is regex-able, propose
adding it to `riko/cli/_lint_terms.py` (`BANNED_TERMS`, with its Reserved
terms ruling) or a new `manage lint` check, so CI enforces it from then on.

## 5. Verify the fixes

Prettify, then lint and test only what tidy touched:

```bash
uv run --active python -m riko.cli.manage prettify
uv run --active python -m riko.cli.manage lint --terms --literals --docstrings --docs
uv run --active python -m pytest --no-cov -q <test modules for the touched files>
```

When `/land` called tidy, its full gates follow anyway. When `/wrapup` called
it, report "tidy edits not yet through the full suite" so the handoff carries
it to the next `/land`.

## 6. Mark and report

After the fixes, write the marker: `HEAD`'s sha and the fingerprint of the
tree as tidy left it. An untouched tree then skips the next run; any later
edit re-opens the whole range since that sha.

Report: the scope resolved, each fix applied (file:line, rule), findings sent
to `/triage`, questions asked and their answers, lint promotions proposed, and
the verification run. Never commit; the user commits.
