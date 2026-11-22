---
name: triage
model: fable
description: Decide the disposition of a riko defect or audit finding BEFORE fixing it — find the gameplan phase that owns the behavior, then either fix locally (regression test + CHANGES line) or leave a strict-xfail tripwire for the owning phase. Use when the user asks to triage findings, process an audit, asks "should we fix this now?", "who owns this?", or proposes fixing something that might be owned by planned work.
---

# Triage (ownership before fixes)

The finding is: $ARGUMENTS

riko's gameplans are executable policy: a defect whose correct fix is owned by
a planned phase must NOT be fixed ahead of that phase — an early fix builds an
interim implementation the phase will replace, and may contradict the phase's
exit criteria outright. Triage decides which side of that line each finding is
on. Do not write a fix until the disposition is decided.

## 1. Understand the finding

Confirm the finding is real and understand its mechanism — reproduce it or
read the code path. If the cause is not yet diagnosed, that's a /diagnose job
first; triage consumes diagnosed findings. A CI failure that passes locally usually
belongs to one matrix leg (no extras, or another Python): reproduce it with
`python .claude/skills/triage/ci_legs.py [--legs 3.12-bare,3.13-extras] <targets>`,
which runs pytest in cached scratch venvs synced the way CI syncs each leg.

## 2. Find the owner

Search for the phase that owns the behavior, in authority order:

1. `_docs/gameplans/implementation-sequence.md` — the forward order and each
   phase's goal/exit criteria (ADD/MIGRATE/DELETE). Exit criteria are binding:
   a "DELETE: no X may coexist" line prohibits building X now, even as a fix.
2. The topical gameplan in `_docs/gameplans/` (one semantic owner per
   concept) for the target semantics.
3. `_docs/ROADMAP.md` for routing when the owner isn't obvious;
   `_docs/PHASE_CHECKLISTS.md` for what's already done vs. pending.

Grep the gameplans for the module, concept, and failure vocabulary — owners
are often stated in a phase you wouldn't guess from the file that misbehaves.
Batch, don't serialize: grep all four sources (`implementation-sequence.md`,
the topical gameplans, `ROADMAP.md`, `PHASE_CHECKLISTS.md`) for every term in
one Bash call with `grep -n`, and read only the matching sections with
`sed -n 'A,Bp'` in a second call; one grep per turn is the costliest way to
search.

A defect in a dependency (meza, mezmorize, …) that riko works around belongs to
`_docs/gameplans/upstream-fixes.md`: the local workaround is the repair, and it
ships with an entry there plus a strict-xfail canary in
`tests/internal/test_upstream.py` that calls the dependency directly.

## 3. Decide the disposition

- **Local repair** — no phase owns the behavior, or the owning phase has already landed:
  fix now at the root cause, add a regression test (a row in the subject's existing
  table when one has the same shape; see `tests/__init__.py`), add a `docs/CHANGES.rst`
  line if user-observable. No prose journaling. Prove each new test fails on the old
  code with `python .claude/skills/triage/fail_first.py --ref <commit before the fix>`
  followed by `-- <test files> -k <selectors>` (it never touches the working tree); a
  test that passes there either guards something else or does not probe the bug. When
  the fix is uncommitted, pass `--old <path>=<pre-fix copy>` per fixed file instead of
  `--ref`: it snapshots the working tree with those files swapped back. Name the fix's
  class from `python .claude/skills/tidy/mistake_scan.py --classes`, add the fix's ref
  to that class's `CLASS_HISTORY` refs (or add the class with a probe line), then run
  `mistake_scan.py --rewrap` and `ruff format` on it; the count is derived from the
  refs, where each item before a `;` in a dated group counts, so a note goes after the
  `;`. An uncommitted fix's ref reads `uncommitted (MM-DD <what>)`, and /wrapup swaps in
  the hash once the user commits; never ask the user to. And when the scanner has a rule
  for the class, add the pre-fix line as a row in
  `.claude/skills/tidy/test_mistake_scan.py`.

  **Find the commit that introduced the bug before placing the fix.** Use
  `git log -S`/`-G` on the broken line, or bisect with the regression test. When that
  commit is past the branch's merge point (the merge-base with `next` or `main`), the
  fix and its regression test become a `fixup!` of it, whether or not it was pushed:
  - prove the test with `fail_first.py --ref <introducing commit>`;
  - add no `docs/CHANGES.rst` line and no `CLASS_HISTORY` ref, since the autosquash
    removes the bug from history and nothing would replay or resolve the ref;
  - still add the `test_mistake_scan.py` row when a scanner rule covers the shape;
  - name the introducing commit in the disposition so `/land` targets it.

  Only a bug from a commit at or before the merge point gets a new fix commit with the
  ref and CHANGES line above.
- **Phase-owned** — a pending phase's goal or exit criteria cover it: do NOT
  fix. Leave a strict-xfail tripwire instead (below) and record the finding
  against the owner in its gameplan if it isn't already captured there.
- **Contradicts the gameplan** — the "obvious fix" builds something a phase's
  exit criteria prohibit (its DELETE list, or an explicit "no X" ruling):
  reject the fix, cite the exact gameplan line, and surface the conflict to
  the user in case the gameplan itself should change.

When a finding splits — part locally repairable, part owned — split it and
handle each part under its own rule.

### Present the dispositions before producing anything

Before writing any fix, test, or tripwire, write the proposed disposition
for every finding as a list (not a table), one line per finding: finding →
disposition → the gameplan line that decides it → the artifact you intend to
produce. Write it as visible text before the questions, where it stays in
the transcript once the dialog closes; a paraphrase or summary sentence does
not count. This is a hard gate: if the list is not yet on screen, write it
before calling AskUserQuestion, even when every finding looks obvious.

Before offering a repair shape, check what else consumes the thing it
changes: every caller, gate, skill, or check that reads it. List each one
the change affects in that option's description as a cost. An absolute claim
such as "nothing reads X" has to come from a search you ran, not from
memory. If you find a cost after the user has answered, stop before applying
anything (or before continuing, if you already have), state the cost, and
ask again. Never report it afterwards as a side note.

Then confirm through AskUserQuestion with **one question per finding**, up to
4 per call (send further calls for more findings). The dialog hides text
written in the same turn and its preview box truncates, so each question must
carry its own disposition: the question names the finding and the proposed
action, the first option is that action marked "(Recommended)", and the other
options are real alternatives (a different shape, defer, skip), each with what
it buys and costs in its description. Keep any `preview` to a two-line
summary. Do nothing until every question is answered. Never word a question
as "above" or "as laid out".

Some findings need more than a confirmation. Ask a dedicated question, with
options that state what each buys, costs, and forecloses and a recommendation
listed first, when:

- ownership is genuinely ambiguous — two phases could plausibly own it, or no
  gameplan text settles it and the choice between local repair and tripwire
  is a judgment call
- a local repair has more than one viable shape, or changes user-visible
  behavior or a public surface
- the finding contradicts the gameplan and the question is whether the
  gameplan itself should change
- the split of a compound finding could reasonably be drawn differently

Ask these in place of that finding's confirmation question, in the same
calls (up to 4 questions per call). Clear-cut dispositions with a single
decisive gameplan line need only the confirmation.

### Apply the decided dispositions in one agent

Once every question is answered, the main loop does not apply the fixes
itself. Run `python .claude/skills/land/require_agents.py` (on failure, stop
and report its output), then launch one fresh `implementer` agent with
`model: "opus"` and a self-contained brief:

- the decided disposition list verbatim (finding → disposition → deciding
  gameplan line → artifact);
- the exact files and tests to touch;
- the tripwire template from §4, and the fail-first proof command above for
  each regression test;
- the rules: apply mechanical fixes; batch independent edits and targeted
  test runs into single turns; and when a repair turns out to touch a caller,
  gate, skill, or check the disposition did not list, stop and report it
  rather than decide, so the main loop can ask again.

Wait for its report, re-run the fail-first proof and the targeted tests once,
and only then report. The main loop's context is several times larger than a
fresh agent's, so every edit→test turn there costs far more. The agent
inherits the rule above on a cost found after the user has answered: it
reports the cost instead of deciding.

## 4. Tripwires for owned findings

A tripwire is a strict xfail probing the exact failure mode, so the owning
phase cannot land without tripping it:

```python
@pytest.mark.xfail(
    strict=True,
    raises=<the exception it fails with today>,
    reason="<the pending capability, in plain English> is not yet implemented",
)
```

- Probe the *specific* wrong behavior observed (wrong value, wrong exception,
  wrong ordering) — not a vague "this area is broken".
- Word the reason as "<the pending capability> is not yet implemented" (e.g.,
  "lazy async fan-out is not yet implemented"); never a phase code like `R5C` or a
  gameplan path, which are banned from shipped text (`manage lint --terms` flags
  them). The phase code goes in the gameplan note, which names the tripwire's test
  id so a future session finds the contract.
- Place it in the existing test module for that area; follow the placements
  already used for tripwires in `tests/internal/`.
- `raises=` names the exception the probe fails with today (`AssertionError` for a
  wrong value, `pytest.fail.Exception` for a `pytest.raises` that does not raise), so
  a typo or setup error cannot pass as the expected failure; run the test with
  `--runxfail` to see it. `manage lint --tests` fails a strict xfail without it.
- `strict=True` is the point: when the phase lands and behavior corrects, the
  XPASS fails the suite, forcing the tripwire's removal and a real test.

## 5. Report

For each finding: the disposition (local / owned-by-`<phase>` / contradicts),
the evidence line in the gameplan that decides it, and the artifact produced
(fix + regression test, or tripwire + gameplan note). List anything left
undecided with what's needed to decide it.
