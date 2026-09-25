---
name: triage
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
read the code path. If the cause is not yet diagnosed, that's a /debug job
first; triage consumes diagnosed findings.

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

## 3. Decide the disposition

- **Local repair** — no phase owns the behavior, or the owning phase has
  already landed: fix now at the root cause, add a regression test, add a
  `docs/CHANGES.rst` line if user-observable. No prose journaling.
- **Phase-owned** — a pending phase's goal or exit criteria cover it: do NOT
  fix. Leave a strict-xfail tripwire instead (below) and record the finding
  against the owner in its gameplan if it isn't already captured there.
- **Contradicts the gameplan** — the "obvious fix" builds something a phase's
  exit criteria prohibit (its DELETE list, or an explicit "no X" ruling):
  reject the fix, cite the exact gameplan line, and surface the conflict to
  the user in case the gameplan itself should change.

When a finding splits — part locally repairable, part owned — split it and
handle each part under its own rule.

## 4. Tripwires for owned findings

A tripwire is a strict xfail probing the exact failure mode, so the owning
phase cannot land without tripping it:

```python
@pytest.mark.xfail(
    strict=True, reason="owned by <phase>: <exact probed failure mode>"
)
```

- Probe the *specific* wrong behavior observed (wrong value, wrong exception,
  wrong ordering) — not a vague "this area is broken".
- Name the owning phase in the reason so a future session finds the contract.
- Place it in the existing test module for that area; follow the placements
  already used for tripwires in `tests/internal/`.
- `strict=True` is the point: when the phase lands and behavior corrects, the
  XPASS fails the suite, forcing the tripwire's removal and a real test.

## 5. Report

For each finding: the disposition (local / owned-by-`<phase>` / contradicts),
the evidence line in the gameplan that decides it, and the artifact produced
(fix + regression test, or tripwire + gameplan note). List anything left
undecided with what's needed to decide it.
