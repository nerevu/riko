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

Tidy's marker is the `tidy` entry of `.claude/gate-markers.json` (untracked,
per worktree, survives `/clear`, shared by every session), written by
`python .claude/skills/land/gates.py`. Run `gates.py check tidy` first: exit 0
means tidy already ran on this exact content, so report "nothing to tidy" and
stop. The marker is the working tree's content tree id, so committing, staging,
an autosquash, or another session's earlier tidy keeps it valid; only a content
edit invalidates it. Otherwise the scope is what changed since the last pass:

- `check` printed a `changed since: git diff <tidied tree> <current tree>` line
  (the tidied tree still exists): that diff plus untracked files. It holds only
  the content edited since the pass, so work the pass already covered stays out,
  including commits made after it;
- otherwise, everything changed since the marker's `head` sha (printed by
  `check`):
  - marker present and an ancestor of `HEAD` (`git merge-base --is-ancestor`):
    `git diff <sha>` plus untracked files (`git ls-files --others --exclude-standard`);
  - marker missing or not an ancestor (after an autosquash rebase): the unpushed
    commits (`git log HEAD --not --remotes`) diffed from
    the parent of the oldest one, plus the working tree and untracked files; with
    no unpushed commits, the working tree alone.

If the scope is empty, run `gates.py record tidy` and stop. A
wholesale run ("tidy the repo") takes every tracked file and fans out one
read-only agent per top-level package, then applies fixes centrally.
Every agent brief ends with the mid-run self-check: past about 10 minutes or
100k tokens with mechanical, repeated work left, stop at a consistent point, run
the gates, and report what is done, what is left, and the helper script that
would speed up the rest (run `date` at the start and between items). About 10
minutes in, send it a non-stopping status ping; pause one that is grinding,
build the script, then resume it. When an agent finishes, inspect any scripts it wrote for itself (scratchpad,
`/tmp`, new untracked files) and decide for each: promote it to a shared helper,
fold it into an existing one,
park it in `.claude/skills/drafts/` as an unapproved candidate, or drop it; report the verdict.

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
say are kept (`catalog_names`, callable-sense "pipe",
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
   **House record shapes:** a field whose only constructor computes it from
   other data (store the input, derive it as a `cached_property`); a private
   init alias or `Factory` carrying a derived value rather than state callers
   may supply; a free function over one record, called only by its owner (make
   it a method or property); a free function that builds `X` (make it an
   `X.from_*` classmethod); a closure factory branching on a union its callers
   already know; an attrs class whose only behavior is a forwarding `__call__`
   (use `functools.partial`); the same filter or narrowing written in two or
   more places (one cached view on the type that owns the data); a check that
   compares a view against its own source (the precondition belongs on the
   source); the same validation run in a classmethod and the constructor;
   `Callable[..., X]` for a fixed signature (a callback `Protocol`); a role
   type spelled out three or more times (a `type` alias); a bool property
   restating `x.attr is None` that callers cannot narrow through.
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
   the change altered; code blocks that use a name they don't define
   themselves or rebind a name within the block (setup repeated across blocks
   is correct, never dedupe it); docstrings that explain mechanism instead of
   what the caller gets.
8. **Doc hygiene** — duplicated table rows or sections, broken cross-references
   the docs lint does not cover, `_docs/` paths in shipped text.
9. **Test ownership** — for each new or moved test (`manage lint --tests` already
   holds the file to its index row and class layout): is it in the right tier
   (functional if it runs a CLI command, `examples` pipeline, or stored fixture end
   to end; public if it uses only supported names; else internal) and in the file
   whose index row names its subject? Does a collected doctest or an existing test
   already assert the same input and outcome? Doctests show basic usage. An edge or
   error case in both places leaves the doctest when the doctest already shows
   several other basic use cases. When it does not, prefer rewriting the doctest to
   show basic usage and keeping the edge case in pytest. Basic usage lives in its
   most appropriate doctest: move it into this doctest from elsewhere when this is
   the better home (and follow the move down to the doctest it leaves), but never
   duplicate it just to give a doctest something to run. Only when no basic usage
   belongs in this doctest does the pytest copy go. When you add a doctest, grep
   the tests for each of its inputs and remove a matching test or table row in the
   same pass.
   A new test with the same setup and assertion as an existing one (two is
   enough) is a row in that test's table, and a regression test goes in its
   subject's class, never a history-named file. Tables follow the
   `tests/__init__.py` layout: module-level constant, one-line `pytest.param`
   rows with ids (an `ids=[...]` list only when values and ids share one line);
   a fold that grows the file needs its rows compacted. A doctest grown past basic
   usage moves its extra cases into its subject's test table. If
   `manage test --ratchet` reports more uncovered lines, find the lines the
   change stopped executing before anything else.
   When the change splits or merges a test file (a new or deleted
   `tests/<tier>/test_*.py`, or classes moved between files), run this check over
   every test in the files it touched, not only the moved ones: overlaps (same
   input and outcome in either file, another tier, or a doctest), misfits (a class
   asserting a subject another row owns, or a test in the wrong tier), move
   candidates left behind in the source file, and helpers whose users changed
   (now used by one file → beside its class; by several → `tests/_*.py`).
   Start from `python .claude/skills/tidy/overlap_scan.py --files <each touched
   file>` (static, about 2s). It lists candidates (unused or single-user helpers,
   copied definitions, same-shape tests, shared literals, same-named tests,
   unsupported names in public, functional classes with no end-to-end marker).
   Read and verify only those, never whole files. Make the moves with
   `python .claude/skills/tidy/move_tests.py` (`--check` before a move to public,
   `--merge` to fold one class into another, `--sort` for in-class order,
   `--delete`/`--drop-row` for trims, `--place` to put helpers above their user;
   moves repoint doc citations), and find a test's current home with
   `overlap_scan.py --where NAME`. After editing either script, run its smoke
   test: `uv run --active pytest .claude/skills/tidy/test_move_tests.py`.

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
uv run --active python -m riko.cli.manage lint --terms --literals --docstrings --docs --bindings
uv run --active python -m pytest --no-cov -q <test modules for the touched files>
```

When `/land` called tidy, its full gates follow anyway. When `/wrapup` called
it, report "tidy edits not yet through the full suite" so the handoff carries
it to the next `/land`.

## 6. Mark and report

After the fixes, run `python .claude/skills/land/gates.py record tidy`. It
records the tree as tidy left it, so an untouched tree skips the next run from
any session, and any later edit reopens the range since that `head`.

Report: the scope resolved, each fix applied (file:line, rule), findings sent
to `/triage`, questions asked and their answers, lint promotions proposed, script
candidates (a check you repeated by hand, or a helper script you wrote into the
scratchpad, that a checked-in script could run next time: name, inputs, outputs;
its draft saved in `.claude/skills/drafts/`),
and the verification run. Never commit; the user commits.
