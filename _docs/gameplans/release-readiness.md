# Gameplan: Pre-1.0 DX Polish & Release Gate

## 1. Mission

Treat the last mile to a public 1.0 as a **release-gate pass on semantics**, not cosmetic cleanup.
Riko's core is mature; the remaining rough edges are places where implementation mechanics leak into
the user model. This plan owns the cross-cutting **DX/API-shape** decisions and the **release/package
fidelity** gate; it routes the parts owned elsewhere to their owners.

> **Status (2026-08):** **Planned — release gate.** Not a single P-phase; it *pulls forward and
> sequences* items across P9/P11/P12/P13 plus new API-shape decisions. Guiding triage in § 8.
>
> **Provenance.** Folded in from the untracked `_docs/ux_polish.md` scratch analysis.
>
> **Ownership boundary.** This is **internal API-shape + release readiness**. It is distinct from
> [extensibility.md](extensibility.md) **E7 "1.0 readiness"**, which owns the *ecosystem* side
> (conformance badges, stable-API publication, deprecation/migration windows, "ship 1.0 only after
> ≥1 external plugin"). Owned-elsewhere clusters this plan only *sequences*:
> - **Pub/sub 1.0 contract** → [fanout-topology.md](fanout-topology.md) **F1/F4/F5** + P11;
> - **Fluent discoverability** → [module-enums.md](module-enums.md) (P9);
> - **Error hierarchy** → P12 ([MILESTONES.md](../MILESTONES.md));
> - **Execution semantics** → [execution-semantics.md](execution-semantics.md);
> - **Unified CLI** → [cli.md](cli.md).

## 2. Pub/sub: the minimum 1.0-caliber contract (owned by fanout-topology.md)

The sync pub/sub priming requirement is the clearest mechanics-leak. The **target contract**:
creating a receiver makes it ready immediately; receiving yields **only** user items; unknown
receivers fail with a typed exception; buffers never lose data unless a lossy policy was explicitly
requested; channel state belongs to one execution; sender completion cleanly terminates receivers;
and the **same rules apply to sync and async**. Concretely (each maps to a topology phase):

- **Eager sync subscriptions — eliminate `next(receiver)` priming.** A `SyncSubscription`
  registered synchronously at construction; `SyncPipe("receive", …)` keeps working over it. (F5)
- **Remove `PENDING` records from the data stream.** Replace poll-sleep-yield-`PENDING` with a
  blocking `Condition`/`Queue` primitive; waiting is invisible; expose `subscription.state`/
  `.closed`/timeout instead. Simplifies `Item` typing. (F1/F4)
- **Eliminate silent data loss.** Sync `send()` to a missing receiver must raise
  `ReceiverUnavailableError` (async already does); default buffers **lossless** (bounded blocking +
  timeout → typed backpressure/queue-full error); `drop_oldest`/`drop_newest` are explicit opt-ins. (F4)
- **Scope pub/sub to an execution, not the process.** Move `sync_hub`/`async_hub` off module globals
  into a `Context` resource bag; `reset_pubsub()` becomes test-only. (F5, + `Context.resources`)
- **Observable sync/async parity.** Make async `receive` a real async generator (first item before
  sender completion), matching sync's incremental streaming. (F1)
- **Subscription handles, not hidden id bookkeeping.** Replace `send`'s `ids` dict +
  `_notify_subscribers()` `DONE` sentinel with explicit generation/token ownership; completion =
  `subscription.close()`/channel closure. (F5)

**Vocabulary (P1 of the doc):** `others`→`targets`, `max_len`→`buffer_size`,
`max_wait`→`timeout`/`idle_timeout`, drop the sync-only `wait` interval; keep old names as
deprecated aliases ≥1 minor. Export `ReceiverUnavailableError`/`DuplicateReceiverError`/the new
backpressure error from `riko`/`riko.api`.

## 3. Configuration correctness

- **Stop silently accepting invalid `Context`.** Remove the catch-all `**kwargs` (`Context(verbsoe=…)`
  must not look successful; migration's `describe_input=True`→`RUN` silent coercion is release
  poison). Deprecated kwargs translate with `DeprecationWarning` or raise actionable errors.
- **Validate module config early** — unknown keys, invalid enums/operators, conflicting options,
  wrong types — at pipe **construction**, not mid-iteration.

## 4. API-shape compression (the highest-value remaining work)

> **Make streaming, boundedness, ordering, and side-effect semantics properties of the *pipe*, not
> consequences of whether the user picked `SyncPipe` or `AsyncPipe`.**

- **`Collection` stops being a first-class abstraction.** It is effectively a multi-source
  constructor for a pipe (`SyncCollection.pipe()`/`AsyncCollection.async_pipe()` literally convert to
  a pipe). Replace with `SyncPipe.from_sources(sources, …)` / `AsyncPipe.from_sources(…)`; keep
  `SyncCollection(...)` as a deprecated alias for one cycle. Shrinks the stable surface from four
  concepts to two. Private source strategies (`_IterableSource`/`_MultiSource`/`_AsyncMultiSource`/
  `_ModuleSource`) own ingestion; the pipe owns composition/lifecycle. **Do not** merge into a giant
  `PyFlow` — that compresses inheritance while leaving four user-visible objects.
- **`PyPipe` becomes private/structural** (`_PipeBase`/`_PipeDefinition`+`_ExecutionConfig`+
  `_Lifecycle`), never a named third pipe concept.
- **Definition vs execution.** Highest-value architectural change: separate a reusable immutable
  `Pipeline`/`PipeSpec` from a one-shot `Execution`. Interim: make post-construction config
  immutable, remove mutable `PyPipe.__call__` (derivation → `with_config(...)` returns a **new**
  object), and reject chaining `EXHAUSTED` with `PipelineStateError` (silent empty output is a
  brutal failure mode). Target model:
  ```text
  Pipeline  (reusable definition) → SyncExecution (Iterator) / AsyncExecution (AsyncIterator)
  ```
- **Explicit terminals** — `flow.collect()`/`first()`/`take(n)`/`write("out.json")` instead of
  inferring `list(sync_pipe)` = collect vs `await async_pipe` = collect. Reserve `.pipe()` for
  transforms; reconsider `split()`/`export()` as special methods (`export()`'s list|tuple|StringIO|
  int|iterable|None return is hard to type — separate collection from writing).
- **One concurrency vocabulary.** Promote `executor=` (`"thread"`/`"process"`/`"inline"`) + `workers`/
  `concurrency`/`ordered`/`prefetch`; demote `parallel`/`threads`/`pool`/`pool_scope`/`chunksize` to
  expert-only. Finish the tracked `threads → executor` shim before freezing 1.0.
- **Shrink `Context`** — `verbose`→logging, `test`→remove, `submodule`→internal, `mode`→explicit
  introspection (`flow.describe()`/`required_inputs()`/`dependencies()`; `ExecutionMode` stays
  private/compiler-facing). Aim for `Context(inputs=…, resources=…)` — `resources` also solves the
  process-global pub/sub/registry ownership.
- **Constructor stops being a union of every module's knobs** — move `assign`/`field`/`func`/`others`/
  `skip_if` to the step boundary (`flow.pipe("foo", conf=…, assign=…)`); typed `SourceSpec`/
  `("fetch", {...})` tuples instead of `{"type": "fetch", …}` dict-encoded behavior.
- **Collapse the runtime-utility surface** — de-emphasize `backend`/`isasync`/`issync`/`async_return`/
  `async_sleep`/`run` from the stable API into an advanced/internal namespace; users write normal
  Python iteration.
- **Rename `collections.py`** once `Sync/AsyncCollection` go (→ `pipe.py`/`runtime.py`/`execution.py`);
  users import only from `riko`.

## 5. Error UX (owned by P12)

Pull P12 forward before declaring the API stable — today the code mixes typed Riko exceptions with
bare `ValueError`/`RuntimeError`/`ImportError`/logging/silence (the registry raises plain `ValueError`
for duplicate registrations). Land the `RikoError` tree (`ConfigurationError`/`PipelineStateError`/
`ModuleResolutionError`/`ModuleRegistrationError`/`MissingOptionalDependencyError`/`PublishError`/
`SubscriptionError`); every message carries the offending value + likely correction.

## 6. Optional-dependency UX

Calling something that needs an extra must produce an actionable message, never a deep
`ModuleNotFoundError` or a `backend == "empty"` puzzle:

```text
Async support is not installed.
Install it with: pip install "riko[async]"
```

Same for `ijson`/`lxml` (`perf`) and OFX/QIF (`finance`).

## 7. Release & package fidelity

- **Built-wheel smoke gate** (not just editable-install testing). Before publish: `uv build` →
  `twine check dist/*` → install the **wheel** into a pristine venv → smoke-test `import riko`,
  `py.typed`, bundled data, core CLI (`riko --help`), `riko[async]` (and preferably `[all]`), and one
  sync + one async pipeline. **Publish only that exact tested artifact.**
- **CI enforces formatting** — `ruff check` + `ruff format --check`, not `ruff … --fix` in an
  ephemeral runner (which fixes locally then discards while still passing).
- **Public dependency-graph lane** — `pyproject.toml` declares `meza>=0.42.5` but
  `[tool.uv.sources]` resolves meza from a git commit; add a job that ignores workspace/source
  overrides (installs the PyPI graph users actually get), plus one min-supported and one
  latest-compatible dependency lane.

## 8. Surface & doc hygiene

- **Shrink `riko.modules.__all__`** — it still exposes implementation types/functions despite the
  architecture saying module-author APIs live under `riko.ext`. (Largely addressed by the narrowed
  10-name facade — verify nothing implementation-level remains before release.)
- **Resolve doc/spec drift** — keep one authoritative "what ships" doc ([IMPLEMENTED.md](../IMPLEMENTED.md)),
  one roadmap, generated API docs; banner/archive the rest. (This four-doc consolidation pass is part
  of that effort.)
- **Docs teach only public imports** — no `riko.modules.*` in user-facing pub/sub examples; give
  pub/sub a first-class public entry point. Rewrite the first-five-minutes quickstart around an
  in-memory three-step pipeline understood in 15 seconds; network/RSS follow.

## 9. Pre-public-release triage (the gate)

**Must land:** P9 discoverability/stubs · strict configuration validation · `executor=` cleanup ·
P12 errors · unified CLI ([cli.md](cli.md)) · wheel/PyPI-dependency smoke tests · the § 2 pub/sub
fixes (F1/F4/F5).

**Strongly preferred:** explicit terminals · remove mutable post-construction config · shrink
`riko.modules` · resolve doc drift.

**Can wait:** new modules · branching/routing primitives · connector packages · richer orchestration ·
most roadmap expansion.

**Biggest open question:** do `SyncPipe`/`AsyncPipe` remain *both* pipeline definition and running
cursor for 1.0? If yes → tighten one-shot semantics aggressively. If no → separate `Pipeline` from
`Execution` now (§ 4); doing it after public adoption is far more expensive.

## 10. Relationship to the P-track

- **Sequences, not replaces, the P-track** — § 2 = P11 + fanout-topology F1/F4/F5; § 5 = P12; § 8's
  `riko.modules` shrink = P3/P9 surface work; § 4 config-immutability tightens P5 one-shot lifecycle.
- **Live status** (done/next/suite count) lives only in the
  [PHASE_CHECKLISTS.md](../PHASE_CHECKLISTS.md) tracker — do not restate it here.
