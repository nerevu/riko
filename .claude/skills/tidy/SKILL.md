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
`python .claude/skills/land/gates.py`. The marker is the working tree's content
tree id, so committing, staging, an autosquash, or another session's earlier
tidy keeps it valid; only a content edit invalidates it.

Resolve the whole scope, and run every opening check over it, with **one call**:

```bash
date && python .claude/skills/land/gates.py scope tidy --leads
```

It prints which base applies (the tidied tree when git still holds it, so work the pass
already covered stays out; else the marker's `head` when it is an ancestor of `HEAD`;
else the parent of the oldest unpushed commit after an autosquash; else `HEAD`), the
`--stat`, the untracked files, and the diff itself with `uv.lock` and the generated
files left out. Untracked files are inside the diff. Then, each under its own
`--- <name>` header (with its exit code when non-zero), the outputs of the checks §1 and
§3 open with, run side by side over that diff: `lint` (§3's lint selectors),
`neighborhood` (the touched neighborhood below, with two lines of context around each
reference), `mistake_scan`, `reuse_scan`, and `reuse_shapes` (§3's leads); plus
`heading_drift` when the scope touches Markdown, `changelog_widows` when it touches
`docs/CHANGES.rst` (check 6), and `overlap_scan --files` over each touched
`tests/<tier>/test_*.py` (check 9). Never rerun any of them by hand on the same tree.
A diff over 25kB lands in `.claude/tidy-scope.diff`, and the output opens with a hint
to read `--edits-only` first; read the saved diff in slices with `Read` offsets, never
whole. Exit 0 means tidy already ran on this exact content: report "nothing to tidy"
and stop. Exit 2 means the scope is empty: under `/land`, just stop and report it
(land records tidy after your report); otherwise run `gates.py record tidy` and stop.
Never reassemble the scope from `git diff` by hand. When the diff is mostly moved code
(test reorganizations, file splits), `gates.py scope tidy --edits-only` lists just the
added lines that no removed line carries, `path:line: text`; read those first and the
moved spans only where an edit sits inside them. When it is mostly a Markdown reflow
(a `rumdl fmt` pass), `python .claude/skills/tidy/reflow_word_diff.py BASE` lists only
each file's wording changes, ignoring line breaks and markup; review those instead of
the reflow. The `heading_drift` section (already in `--leads` when the scope touches
Markdown) lists each heading the change adds, removes, or re-levels and exits 1 on a
re-level or a wrapped issue number turned heading (`## 60:`), the start of a
`rumdl fmt` cascade that demotes every later heading in the file. Restore the levels
and escape the number (`\#60`).

A wholesale run ("tidy the repo") takes every tracked file and fans out one read-only
agent per top-level package, then applies fixes centrally. Every agent brief ends with
the mid-run self-check: past about 10 minutes or 100k tokens with mechanical, repeated
work left, stop at a consistent point, run the gates, and report what is done, what is
left, and the helper script that would speed up the rest (run `date` at the start and
between items). About 10 minutes in, send it a non-stopping status ping; pause one that
is grinding, build the script, then resume it. When an agent finishes, inspect any
scripts it wrote for itself (scratchpad, `/tmp`, new untracked files) and decide for
each: promote it to a shared helper, fold it into an existing one, park it in
`.claude/skills/drafts/` as an unapproved candidate, or drop it. A dropped or folded
script moves to `.claude/skills/disposed/`, which is git-ignored and cleared only by the
user (agents never delete it); report the verdict.

Also pull in the **touched neighborhood**: callers and docs of every symbol the diff
renamed, removed, or changed in meaning. The `neighborhood` section (already in
`--leads`) lists them: it reports each removed or re-signed definition with its
surviving references across `riko/`, `tests/`, `docs/`, `_docs/`, `examples/`,
`README.rst`, and `CONTRIBUTING.rst`, and the names the same file added, so a rename
reads as one; the two lines around each reference usually settle it without opening the
file. Grep by hand only for a term the diff changed in meaning without touching its
definition. Apply the stale names it finds in checked batches with
`python .claude/skills/tidy/replace_exact.py FILE SPEC.json [--dry-run]` (a JSON list of
`[old, new, expected_count]`; any count mismatch writes nothing), so a rename never also
hits an unrelated use of the same text.

## 2. Load the rules (one batch)

- `CLAUDE.md` — cross-cutting invariants, coding style, verb table,
  `StrEnum`/`Literal`, coroutine prefix, `pipeline`/`flow`, workflow type names.
- `_docs/DOCUMENTATION_STANDARD.md` — Reserved terms, no internal jargon,
  doctest rules, docstring rules.
- `_docs/gameplans/implementation-sequence.md` and the topical gameplan for
  the touched area, with their planning TOMLs (`_docs/gameplans/*.toml`: slice
  dates, edges, decisions) — to tell an owned gap from a defect.

Settled exceptions are **not findings**: identifiers the Reserved terms rows
say are kept (callable-sense "pipe",
the `*_key` conf names, `ModuleStore`), wording a pending phase replaces (the
`Sinks` category, send/receive "target"), and gameplans keeping older wording
until touched.

## 3. Check

Open with the lints that already enforce part of this list: the `lint` section (already
in `--leads` output; it ran
`manage lint --terms --literals --docstrings --bindings --tests`). Its output is
findings. It owns: banned phrases and phase codes in shipped text (`--terms`), summary
verbs matching the verb table (`--docstrings`), `pipeline`/`flow` bindings
(`--bindings`), test file/class layout (`--tests`). Do not re-check those by hand; the
hand checks below cover what a regex cannot. Independent probes go in one response as
parallel tool calls, or in one chained Bash command — never one grep per turn — and
`sed -n` ranges of several files go in the same call.

The `mistake_scan` section (already in `--leads` output) scans the added lines for
the defect classes past fix sessions kept repairing (closing, last-wins, truthiness,
sync/async drift, chunk decoding, `next()` without a default, hash-seed order,
frozen-record mutability, unbounded timeouts, `find()` slicing, keywords
shadowing `partial`-bound parameters, unguarded settings casts) and for a second
`return`. Its leads come most-often-fixed class first. They are leads, not findings:
verify each against check 4's bar (truthiness is a finding only when a falsy
value is realistic for that field; a `0` the docstring names as a sentinel is
not) and the rule's own message, then sort into §4's buckets. A lead you rule
safe gets a trailing `# mistake-ok: RMnnn` only when it would recur on every
edit of that line; otherwise just drop it. `mistake_scan.py --classes` prints
each class's rules or audit probe and the shapes ruled safe; /triage adds a
fix's ref to its class when it lands (the count is derived from the refs).

The `reuse_scan` section (also in `--leads`) lists code that restates an existing
helper's body instead of calling it, in both directions: added lines checked against
every helper, and the whole tree checked against each helper the diff added or
changed (old code that predates a new helper). Test helpers (`tests/_*.py` and test
files) are indexed too, for test sites only. Each lead names the helper and what
its wildcards bound. Adopt the helper (check 3), or mark a deliberate copy with a
trailing `# reuse-ok: helper`; a `private: promote?` lead is a private helper wanted
in another file, a `duplicate helper` lead a second definition of the same body.
The `reuse_shapes` section (`reuse_scan.py --shapes`, also in `--leads`; run
`--all --tests --shapes` for a sweep, or name a root such as `examples`) lists each
cluster of near-identical dict, call, and literal constructions a changed line
joins: members that differ only in their values or by one added, missing, or
re-keyed entry. Declaration idioms (attrs `field`/`define`, `dataclass`, the pipe
decorators, `click.option`, `pytest.raises`/`param`/`mark.xfail`/`mark.parametrize`)
are skipped; `--all-callees` shows them. Each cluster prints its skeleton, the
varying slots and their values, and samples: align the arbitrary values and share
one constant or builder, or mark a deliberate member with a trailing `# reuse-ok`.
`--spans SPEC` keeps only the clusters whose members span the named roots, a comma
list of terms: `ROOT` (some member lies there), `only:ROOT` (every member lies in an
`only:` root), `mixed` (two or more roots). `--all --tests --shapes --spans
examples,tests` finds constructions an example and a test both restate;
`--spans riko,mixed` finds test or example code rebuilding a riko construction.

For each file in scope, and only the lines the change introduced or the
neighborhood it affects:

1. **Vocabulary and collisions** — every new identifier, term, heading, error
   message, or concept is checked against the Reserved terms table, the
   supported names in `riko/base/_api_surface.py`, and existing names
   (`grep -rnw`). A collision is a new name that already means something else,
   or an existing riko term used in another sense. The regex-able "say this
   instead" phrases are already `BANNED_TERMS`; the hand check is for a new name
   that reuses a reserved term in another sense.
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
   restating `x.attr is None` that callers cannot narrow through. Before proposing
   to inline a single-use helper, run `.claude/skills/tidy/complexity_scores.sh
   <files>` (each function's McCabe score) so the merged caller stays at C90 ≤ 10;
   keep helpers that hold or sit inside a try/except, are passed by reference, are
   cached, recursive, a per-item-closing generator, or mirror a sync/async twin.
4. **Idioms** — truthiness where `is None` is required, `cast` where narrowing
   works, more than one `return`, comments that restate code, a new `noqa` or
   type ignore with no reason.
5. **Loose ends** — a new TODO with no owner; a new `NotImplementedError` stub
   with no tripwire; a strict xfail whose owning phase has landed; phase codes
   in xfail reasons, test names, docstrings, comments, or runtime messages.
6. **Changelog and journaling** — a `docs/CHANGES.rst` bullet that is not a
   user-visible change against the last release, a "gained/now" delta where the
   unreleased bullet should be edited, a missing bullet for a user-visible
   change (a fix for a 2026-introduced defect needs none: the general Fixes
   bullet covers it, per `_docs/INTERNALS.md`), fix narratives in CLAUDE.md or
   `_docs/`, per-release renames in `docs/MIGRATION.rst`, untracked scratch
   docs cited from stable docs. To check a bullet's "before" claim against the last
   release, run a probe with `python .claude/skills/tidy/release_probe.py VERSION
   PROBE.py --root SCRATCHPAD`, passing the session's scratchpad directory (pre-2026
   releases: `--python 3.8 --build-pin 'setuptools<58' --build-pin 'cython<3'`).
   When the scope touches `docs/CHANGES.rst`, the `changelog_widows` section (already
   in `--leads`, advisory) lists unreleased bullets
   that spill a word or two onto an extra line; reword one only when a word can go
   without losing a backticked name.
7. **Doc drift** — docstrings, RST, README, gameplans, CLAUDE.md, or the
   `_docs/KEY_PATHS.md`/`INTERNALS.md` maps still describing a name or behavior
   the change altered; code blocks that use a name they don't define
   themselves or rebind a name within the block (setup repeated across blocks
   is correct, never dedupe it); docstrings that explain mechanism instead of
   what the caller gets.
8. **Doc hygiene** — duplicated table rows or sections, broken cross-references
   the docs lint does not cover, `_docs/` paths in shipped text. When the scope
   touches `_docs/research/inspiration/`, run
   `python .claude/skills/tidy/inspiration_drift.py`: a snapshot whose body differs
   from its `source:` readme is a finding, and snapshot bodies are never edited.
   `sync_snapshot.py` installs candidates and copies staged snapshots back;
   `removed_content.py` lists dropped-content leads after a readme rewrite.
9. **Test ownership** — for each new or moved test (`manage lint --tests` already holds
   the file to its index row and class layout): is it in the right tier (functional if
   it runs a CLI command, `examples` pipeline, or stored fixture end to end; public if
   it uses only supported names; else internal) and in the file whose index row names
   its subject? Does a collected doctest or an existing test already assert the same
   input and outcome? Would `--check-types`, test collection, or a tox leg already fail
   on the regression it guards (a frozen-field assignment or attrs signature under a
   pyright ignore), and does it assert a riko contract rather than Python or a library
   (`FrozenInstanceError`, a plain `pickle`/`json` round trip)? Then it is not pytest's
   (`testing.md` §1). Doctests show basic usage. An edge or error case in both places
   leaves the doctest when the doctest already shows several other basic use cases. When
   it does not, prefer rewriting the doctest to show basic usage and keeping the edge
   case in pytest. Basic usage lives in its most appropriate doctest: move it into this
   doctest from elsewhere when this is the better home (and follow the move down to the
   doctest it leaves), but never duplicate it just to give a doctest something to run.
   Only when no basic usage belongs in this doctest does the pytest copy go. When you
   add a doctest, grep the tests for each of its inputs and remove a matching test or
   table row in the same pass. A new test with the same setup and assertion as an
   existing one (two is enough) is a row in that test's table, and a regression test
   goes in its subject's class, never a history-named file. Tables follow the
   `tests/__init__.py` layout: module-level constant, one-line `pytest.param` rows with
   ids (an `ids=[...]` list only when values and ids share one line); a fold that grows
   the file needs its rows compacted (`overlap_scan.py`'s `rows` section lists rows a
   few columns too long: shorten the id or `match`, or alias a repeated value; never a
   bare `param` import). A doctest grown past basic usage moves its extra cases into its
   subject's test table. If `manage test --ratchet` reports more uncovered lines, find
   the lines the change stopped executing before anything else. When the change splits
   or merges a test file (a new or deleted `tests/<tier>/test_*.py`, or classes moved
   between files), run this check over every test in the files it touched, not only the
   moved ones: overlaps (same input and outcome in either file, another tier, or a
   doctest), misfits (a class asserting a subject another row owns, or a test in the
   wrong tier), move candidates left behind in the source file, and helpers whose users
   changed (now used by one file → beside its class; by several → `tests/_*.py`). Start
   from the `overlap_scan` section (already in `--leads`, over each touched test file;
   rerun `python .claude/skills/tidy/overlap_scan.py --files <file>...` only for a file
   the change touched indirectly); when the change touched docstring or user-doc
   examples, also run `python .claude/skills/tidy/example_scan.py dups` (≥0.8
   near-duplicate example pairs, about 0.3s; leads only). The overlap scan lists
   candidates (unused or single-user helpers, copied definitions and constants, helper
   bodies inlined in tests, same-shape tests and standalone tests that fit a table,
   `pytest.param` rows a few columns too long for one line, shared literals, doctest
   calls repeated as `pytest.param` rows, doctest errors repeated as `pytest.raises`,
   test messages a doctest also pins, doctests of six or more examples whose callee has
   a table, tests with no assertion or asserts only inside a loop, same-named tests,
   unsupported names in public and supported-only internal classes, out-of-order or
   misplaced classes and helpers, classes that never name their riko-named subject,
   functional classes with no end-to-end marker, tests that start a process without
   saying why). It also lists sync/async twins that check different amounts or lack a
   twin (`twins`), `while True` helpers (`endless`), `once` tests that count nothing
   (`once`), same-process determinism tests (`determinism`), unbounded async teardowns
   (`drains`), and `placement` classes whose subject is not a riko name (a concept class
   belongs in the `tests/__init__.py` list). Read its full output once; never pipe it
   through `head`/`grep` and rerun (`--limit` already caps it). Read and verify only
   those, never whole files. Make the moves with
   `python .claude/skills/tidy/move_tests.py` (`--check` before a move to public,
   `--merge` to fold one class into another, `--sort` for in-class order,
   `--delete`/`--drop-row` for trims, `--place` to put helpers above their user,
   `--with-helpers` so a moved method carries the helpers only it used, `--plan-split`
   for each class's footprint before a split; moves repoint doc citations), and find a
   test's current home with `overlap_scan.py --where NAME`. Usage:
   `move_tests.py DEST SPEC... [--before CLASS] [--rename NEW]` (plus `--with-helpers`,
   `--dry-run`), `SPEC` being `path::Class` or `path::Class::method` and `DEST` a path
   (classes) or `path::Class` (methods); `--rename` with `DEST` equal to the spec's file
   renames the class in place; the mode flags above replace `DEST`
   (`--check`/`--sort`/`--delete SPEC...`, `--merge DEST_CLASS SPEC...`,
   `--drop-row path::TABLE ID...`, `--place path::NAME... --above NAME`,
   `--plan-split FILE`). Module constants that a move strands below code go back to the
   top with `python .claude/skills/tidy/lift_constants.py FILE [FILE ...] [--dry-run]`
   (logger, then `type` aliases, then constants private first, each helper a constant
   calls just above it; it reports what it cannot move). After editing any of these
   scripts, run the smoke tests: `uv run --active pytest .claude/skills/tidy/ --no-cov`.

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

A fix that edits `examples/` is proved behavior-neutral by running
`python .claude/skills/tidy/snapshot_examples.py OUT` before the edit and
`python .claude/skills/tidy/snapshot_examples.py --compare OUT` after it (exit 1 and
the first differing section, log and stderr lines included, on any change; about 6s).

Then check whether any finding class appeared more than once in this run, or matches a
phrase the Reserved terms table already rules out. If it is regex-able, propose adding
it to `riko/cli/_lint_terms.py` (`BANNED_TERMS`, with its Reserved terms ruling) or a
new `manage lint` check, so CI enforces it from then on.

## 5. Verify the fixes

When `/land` called tidy (its brief says so), **skip this step**: land's
prettify, `lint --all`, and test gates follow at once, and running them here
first doubled the work. Report "tidy edits unverified; land's gates follow".

Otherwise prettify, then lint and test only what tidy touched, as one chained
call:

```bash
uv run --active python -m riko.cli.manage prettify && uv run --active python -m riko.cli.manage lint --terms --literals --docstrings --docs --bindings && uv run --active python -m pytest --no-cov -q <test modules for the touched files>
```

When `/wrapup` called it, report "tidy edits not yet through the full suite" so
the handoff carries it to the next `/land`. Nothing to fix means nothing to
verify: go straight to the marker.

## 6. Mark and report

Under `/land`, skip the record: land records tidy after your report. Under `/wrapup`
or a direct run, run `python .claude/skills/land/gates.py record tidy`. It records
the tree as tidy left it, so an untouched tree skips the next run from any session,
and any later edit reopens the range since that `head`.

Report: the scope resolved, each fix applied (file:line, rule), findings sent
to `/triage`, questions asked and their answers, lint promotions proposed, script
candidates (a check you repeated by hand, or a helper script you wrote into the
scratchpad, that a checked-in script could run next time: name, inputs, outputs;
its draft saved in `.claude/skills/drafts/`),
and the verification run. Never commit; the user commits.
