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
- **Remove `PENDING` records from the data stream.** Waiting is invisible; expose
  `subscription.state`/`.closed`/timeout instead. Simplifies `Item` typing. **Blocking is a
  property of the `Subscription`, not of `receive`** — the in-process sync hub is a buffer you
  drain and never has to wait (`send` pushes on the calling thread, so a blocking wait there
  could only ever be satisfied by the thread already blocked), while a broker-backed subscription
  blocks or polls because it has a real remote producer. The *protocol* is therefore uniform
  across sync and async and the in-process implementation simply never waits; a blocking
  `Condition`/`Queue` primitive belongs to the `Subscription` implementations that need one, not
  to `receive`. Non-blocking is the default everywhere, `blocking=True` + timeout is opt-in.
  (F1/F4/F5a, + P11)
- **Eliminate silent data loss.** Sync `send()` to a missing receiver must raise
  `ReceiverUnavailableError` (async already does); default buffers **lossless** (bounded blocking +
  timeout → typed backpressure/queue-full error); `drop_oldest`/`drop_newest` are explicit opt-ins. (F4)
- **Scope pub/sub to an execution, not the process.** Move `sync_hub`/`async_hub` off module globals
  into a `Context` resource bag; `reset_pubsub()` becomes test-only. (F5, + `Context.resources`)
- **Observable sync/async parity.** Make async `receive` a real async generator (first item before
  sender completion), matching sync's incremental streaming. (F1)
- **A receive `func` is a tap, not a transform.** It runs at push time and its return value is
  discarded; the receiver yields the item that arrived. Today the return is queued *instead of*
  the item, so `func=append`/`print` put `None` on the stream and `func=len` puts an `int` —
  neither an `Item`. Transforms stay `udf`'s job. (F5c)
- **Subscription handles, not hidden id bookkeeping.** Replace `send`'s `ids` dict +
  `_notify_subscribers()` `DONE` sentinel with explicit generation/token ownership; completion =
  `subscription.close()`/channel closure. (F5)

**Vocabulary (P1 of the doc):** `others`→`targets`, `max_len`→`buffer_size`,
`max_wait`→`timeout`/`idle_timeout`, `receive`'s `func`→`tap`/`on_item` (a misnomer once F5c
discards the return), drop the sync-only `wait` interval. **Clean break, no
deprecated aliases** — riko has no external consumers pre-1.0, so rename outright rather than
carry a shim to 1.0. Export `ReceiverUnavailableError`/`DuplicateReceiverError`/the new
backpressure error from `riko`/`riko.api`.

## 3. Configuration correctness

- **Stop silently accepting invalid `Context`.** Remove the catch-all `**kwargs` (`Context(verbsoe=…)`
  must not look successful; migration's `describe_input=True`→`RUN` silent coercion is release
  poison). Unknown/renamed kwargs **raise** an actionable error — no translation shim (clean
  break, pre-1.0, no external consumers).
- **Validate module config early** — unknown keys, invalid enums/operators, conflicting options,
  wrong types — at pipe **construction**, not mid-iteration.

## 4. API-shape compression (the highest-value remaining work)

> **Make streaming, boundedness, ordering, and side-effect semantics properties of the *pipe*, not
> consequences of whether the user picked `SyncPipe` or `AsyncPipe`.**

> **Decisions locked (2026-08).** Clean break, **no deprecated aliases** (pre-1.0, no external
> consumers). Go straight to the full `Pipeline`(definition)/`Execution`(one-shot) split — **no
> interim immutable-`PyPipe`** stepping stone. `Pipeline(source=…)` is the only stream constructor
> (**no `from_sources`**); execution options derive via `with_config(...)`. (Folds in the former
> standalone `_docs/pipeline.md` handoff; its cross-cutting parts route to the owners linked below.)

- **`Pipeline` is the sole public pipeline concept.** A reusable, immutable *definition* lives in
  `riko/pipeline.py`, exported from `riko` and `riko.api`. `Pipeline("fetch", source=…)` or
  `Pipeline(source=…)` (an identity stream until a step is chained). Fluent composition —
  `flow.filter(conf=…)`, `flow.pipe("filter", conf=…)`, value-taking `flow | "filter"` /
  `flow | ("filter", conf)` — each returns a **new** definition and never mutates `flow`. No `.then()`.
- **Definition vs execution — the full split, now.** `iter(flow)` builds a fresh `SyncExecution`
  (an `Iterator`); `aiter(flow)` builds a fresh `AsyncExecution` (an `AsyncIterator`). The same
  `flow` runs under `for` **or** `async for`; each iteration is an independent execution. The P5
  one-shot lifecycle belongs to the *execution*, not the definition — chaining onto an `EXHAUSTED`
  execution raises `PipelineStateError` (silent empty output is a brutal failure mode). Do not
  memoize an execution on the definition. Target model:
  ```text
  Pipeline  (reusable definition) → SyncExecution (Iterator) / AsyncExecution (AsyncIterator)
  ```
- **`SyncPipe`/`AsyncPipe`/`SyncCollection`/`AsyncCollection` are removed from the public surface**
  (no deprecated aliases). Their mature one-shot execution mechanics are refactored **private**
  into `riko/_execution/` (`SyncExecution`/`AsyncExecution` + adapters), not preserved as parallel
  compat classes. Compiled `pipe_*` pipelines and `run-pipe` keep working through the private
  engines. Migration is a documented hard break (§ Migration below). `PyPipe` never becomes a named
  third pipe concept — it collapses into the private `_execution` engines.
- **`Collection` disappears entirely.** An outer iterable of records already *is* a stream, so
  `Pipeline(source=[…])` covers every multi-source case — there is no `from_sources`. Source
  classification is one boundary (owned by
  [feed-native-streaming.md § 7.1](feed-native-streaming.md)): a `Mapping` is **one** record; a
  `list`/`tuple`/iterator/generator is a stream; `str`/`bytes` are one item; async
  iterables/awaitables resolve through the execution. A `Pipeline` **definition** over a list
  replays across executions; a **generator instance** stays one-shot and is **never** secretly
  buffered to fake replay.
- **Prerequisite — rename the internal type alias.** `riko/types/general.py` has
  `type Pipeline = SyncPipeParser | AsyncPipeParser`; rename it to `PipeCallable` (+ update
  `Resolver` typing / internal imports) before the public `Pipeline` class can land. Do not expose
  adaptation-layer protocol types merely to solve the rename.
- **Explicit terminals** — `flow.collect()`/`first()`/`take(n)`/`write("out.json")` instead of
  inferring `list(sync_pipe)` = collect vs `await async_pipe` = collect. Reserve `.pipe()` for
  transforms; keep `split()`/`export()` out of the inferred-terminal muddle (`export()`'s
  list|tuple|StringIO|int|iterable|None return is hard to type — separate collection from writing).
- **One concurrency vocabulary — `executor=` only.** `flow.with_config(executor="thread"|"process"|
  "inline", workers=…, concurrency=…, ordered=…, prefetch=…)` returns a **new** definition. **No
  `parallel`/`threads`/`pool`/`pool_scope`/`chunksize` shim** — clean break, single vocabulary.
- **Execution-mode adaptation is owned by
  [execution-semantics.md § Execution-mode adaptation](execution-semantics.md).** Native
  implementation always wins; a sync-only module under async execution runs on a worker; an
  async-only module under sync execution runs on **one** persistent portal per execution. The
  `execution=`(`auto`/`inline`/`thread`/`process`) policy is a single `Opts` field (declared on the
  decorator, overridable per call) — not duplicated here. AnyIO/Asyncer stay **private** (never in
  `riko`/`riko.ext`); a sync-only install that needs an async-only module raises an actionable
  `riko[async]` error (§ 6), never a deep `ImportError`.
- **Decorator DX is owned by [callable-pipes.md § Bare decorators](callable-pipes.md).**
  `@processor async def pipe` newly works for single-impl async; `isasync=`/`async_pipe` are
  **retained** (load-bearing for non-introspectable/dual-impl cases, not shims). One-sided
  `ModuleDefinition` registration → [extensibility.md § 24](extensibility.md).
- **Shrink `Context`** — `verbose`→logging, `test`→remove, `submodule`→internal, `mode`→explicit
  introspection (`flow.describe()`/`required_inputs()`/`dependencies()`; `ExecutionMode` stays
  private/compiler-facing). Aim for `Context(inputs=…, resources=…)` — `resources` also carries the
  execution-scoped pub/sub/registry ownership ([fanout-topology.md F5](fanout-topology.md)).
- **Constructor stops being a union of every module's knobs** — move `assign`/`field`/`func`/`targets`/
  `skip_if` to the step boundary (`flow.pipe("foo", conf=…, assign=…)`); typed `SourceSpec`/
  `("fetch", {...})` tuples instead of `{"type": "fetch", …}` dict-encoded behavior.
- **Collapse the runtime-utility surface** — de-emphasize `backend`/`isasync`/`issync`/`async_return`/
  `async_sleep`/`run` from the stable API into an advanced/internal namespace; users write normal
  Python iteration.
- **Rename `collections.py`** once `Sync/AsyncCollection` go (→ `pipe.py`/`runtime.py`/`execution.py`);
  users import only from `riko`.

**Migration (hard break, pre-1.0 — no aliases).**

```text
SyncPipe(mod, …)           → Pipeline(mod, source=…)
AsyncPipe(mod, …)          → Pipeline(mod, source=…)
SyncCollection(mod, srcs)  → Pipeline(mod, source=srcs)
AsyncCollection(mod, srcs) → Pipeline(mod, source=srcs)
```

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

**Strongly preferred:** explicit terminals · remove mutable post-construction config
([**R2** below is the concrete bug it removes](#91-merge-gate-features--main)) · shrink
`riko.modules` · resolve doc drift.

**Can wait:** new modules · branching/routing primitives · connector packages · richer orchestration ·
most roadmap expansion.

**Resolved (2026-08):** `SyncPipe`/`AsyncPipe` do **not** survive as a public definition+cursor.
Separate `Pipeline` (definition) from `Execution` now (§ 4), clean break, no deprecated aliases —
far cheaper before public adoption than after. File map · sequence · exit tests · DoD:
[MILESTONES.md § Pipeline/Execution split](../MILESTONES.md).

### 9.1 Merge gate (`features` → `main`)

A gate *before* the release gate. The
[correctness-audit register](correctness-audit.md#8-open-defect-register--features-branch-audit)
(17 confirmed defects, verified against `d8d3c02`) is not a release blocker as a whole —
but its **P0** rows are, because each one is silent: it changes laziness, drains an
iterator, or drops a value without failing an import or a happy-path test.

**Status (2026-08-24):** R1 fixed; R2 folded into the § 4 split and no longer blocking;
**R3 fixed** (both the keyed *and* the keyless branch — see the register row).
**No P0 row now stands between `features` and `main`;** the remaining rows are P1–P3 and
belong to the release gate, not the merge gate.

| Row | Blocks the merge because |
|---|---|
| ~~**R1** `_io.opener`~~ **fixed** | remote non-memoized **text** fetch raised `StopIteration` out of `Fetch` — the most-used source in the library |
| **R2** `PyPipe.__call__` | **No longer blocks the merge — folded into the split (decided 2026-08-24).** A call that omits `conf` erases the constructor's, and `p.conf` disagrees with what executed; but § 4 deletes the class, so a sentinel patch would be discarded. Consequence, stated plainly: **the defect ships to `main` and stays live until the split lands** ([MILESTONES § Pipeline/Execution split](../MILESTONES.md) owns the two rules that discharge it). Workaround meanwhile: pass every setting at construction and treat calling an existing pipe as a full reconfiguration, not a partial one |
| ~~**R3** `join`~~ **fixed** | join materialized the primary stream, so an unbounded primary emitted nothing. Both branches were affected — the keyless one via `meza.process.join`, which is itself `map(merge, product(…))` |

Fix order (the audit's, and it is dependency-shaped — each later row is easier once the
earlier one is settled), with R2 lifted out into the split:
~~`_io.opener`~~ → ~~`PyPipe.__call__`~~ → ~~`join`~~ → **async `send`** → `repr_cache` →
compiler identifiers → `gather_results` → `Reencoder` → `fetchtable`/`fetchdata` →
date/parser edges.

Each fix lands with the matching regression test from
[testing.md § 2b](testing.md#2b-regression-batch-from-the-branch-audit), *verified failing
first*, and a `docs/CHANGES.rst` entry — every P0 row is a behaviour change.

## 10. Relationship to the P-track

- **Sequences, not replaces, the P-track** — § 2 = P11 + fanout-topology F1/F4/F5; § 5 = P12; § 8's
  `riko.modules` shrink = P3/P9 surface work; § 4 Pipeline/Execution split tightens P5 one-shot
  lifecycle and sequences across P9/P11/P12/P13 — its file map + exit tests live in
  [MILESTONES.md § Pipeline/Execution split](../MILESTONES.md).
- **Live status** (done/next/suite count) lives only in the
  [PHASE_CHECKLISTS.md](../PHASE_CHECKLISTS.md) tracker — do not restate it here.
