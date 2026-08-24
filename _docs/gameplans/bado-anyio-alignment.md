# Gameplan: `bado` ↔ AnyIO 4.14 Alignment & Async Benchmarking

> **Status (2026-08):** **Planned — unsequenced refinement.** Not yet a P-track phase; touches the
> P7 (true async streaming) and P10 (bounded parallelism/backpressure) as-built primitives without
> changing their contract. Purely a cleanup + measurement plan: trim `bado` helpers that AnyIO 4.14
> now subsumes, and stand up an async benchmark/profile harness to justify any primitive change.
>
> **Prerequisite:** AnyIO **4.14** (task return handles, `anyio.functools.reduce`, async
> `itertools`). `pyproject.toml` currently pins `anyio>=4.0.0` — the replacements below require
> bumping the `async` extra to `anyio>=4.14` first; until then they are advisory.
>
> **Provenance.** Folded in from the untracked `_docs/async_eval.md` scratch analysis.
>
> **Ownership boundary.** [execution-semantics.md](execution-semantics.md) Appendix A owns the
> *runtime semantics* of the async primitives (`async_map`/`async_map_stream`/`async_merge`/
> `_pool_stream` — bounded concurrency, ordering, shared budgets, backpressure). **This** gameplan
> owns only the *AnyIO-version alignment audit* (which `bado` helpers to remove/replace/keep) and the
> *async benchmarking/profiling methodology*. It changes no primitive contract.

## 1. AnyIO 4.14 — what changed the calculus

Three additions make several older `bado` compatibility helpers reconsiderable:

- **Task return handles** — `TaskGroup.start_soon()` returns a `TaskHandle`, and
  `TaskGroup.create_task()` returns a handle whose `.return_value` can be retrieved after the group
  exits. Removes hand-rolled index/collector bookkeeping.
- **`anyio.functools.reduce(func, iterable, initial)`** — accepts sync **and** async iterables;
  expects an **async** reducer.
- **A substantial async `itertools`** (`starmap`, `batched`, `chain`, `islice`, `tee`, …) that
  increasingly accepts both sync and async iterables — but **no** bounded-concurrency worker-pool
  equivalent of Riko's `async_map`.

## 2. Helper audit (all confirmed present in the current tree)

Split into **remove/replace now**, **reconsider**, **keep**. Locations: `_util.py` = `riko/bado/_util.py`,
`itertools.py` = `riko/bado/itertools.py`.

| Helper | Where | Recommendation | Priority | Why |
|---|---|---|---|---|
| `async_partial` | `_util.py` | **Remove** | very high | Only appears in bado's export machinery (`riko/bado/__init__.py`), no production caller; it's just `partial(maybe_deferred, f, **kwargs)`. |
| `gather_results` | `_util.py` | **Replace/delete** | very high | AnyIO 4.14 `TaskHandle` captures results; also has a real bug — `[r for r in results if r is not None]` silently drops a legitimate `None` result ([correctness-audit **R7**](correctness-audit.md#8-open-defect-register--features-branch-audit); `async_map`'s `_missing` sentinel is the fix if it survives). No production caller outside a collection test. |
| `async_json` | `_util.py` | **Remove** | very high | `async def async_json(r): return r.json()` decodes synchronously anyway. One caller (`exchangerate.py`) → inline `r.json()`; if payloads ever get large, `await anyio.to_thread.run_sync(r.json)`. |
| `async_reduce` | `itertools.py` | **Reconsider** | high | AnyIO `functools.reduce` overlaps. Contract diff: Riko accepts `Callable[[T,S], T \| Awaitable[T]]` (sync **or** async reducer); AnyIO expects async. Audit the two callers (`sort`, `regex`) — if neither needs mixed reducers, delegate. |
| `maybe_deferred` | `_util.py` | **Rename → `maybe_await`/`invoke`** | medium-high | Semantics are useful (one API over sync+async callbacks; used by module/decorator machinery) but `deferred` is dead Twisted vocabulary (Twisted gone since v0.72). Rename the private primitive; keep behavior. |
| `async_return` | `_util.py` | **Deprecation candidate** | medium | **In the stable public `__all__`** (`riko/api.py` + `riko/__init__.py`) → SemVer-guaranteed. `async def f(): return value` already does this. Next-major deprecation, not a patch; keep a private `_async_identity` if internally needed. |
| `coop_reduce` | `itertools.py` | **Keep** | low | Distinct semantics: sync reducer + explicit `await checkpoint()` between iterations. Real consumers (`rename`, `regex`, `refind`, `strfind`, `strreplace`, `strtransform`). AnyIO `reduce` wants an awaitable reducer — not a drop-in. |
| `async_iter` | `itertools.py` | **Reduce usage, keep** | low | AnyIO itertools increasingly take sync iterables, cutting adapter need — but Riko's `cooperative=True` (scheduler checkpoints) is a real feature. Shift the model from "convert every sync iterable" to "adapt only when an API needs `AsyncIterable` or cooperative iteration." |
| `async_map`, `async_map_stream`, `async_map_ordered_stream`, `async_merge`, `_pool_stream` | `itertools.py` | **Keep** | — | Encode Riko's concurrency/ordering/shared-budget/streaming/backpressure semantics on top of AnyIO primitives (`create_memory_object_stream`, `create_task_group`) — the layering AnyIO itself recommends, not a reinvention. |

Already-AnyIO, no action: `Path`, `async_sleep`, task groups, memory streams, `CapacityLimiter`, `Semaphore`.

## 2b. Missing async helpers (sync/async parity gaps)

The audit above covers helpers that *exist*. These are capabilities riko's I/O layer is
missing — one a sync/async parity gap, one absent from both paths.

| Gap | Sync today | Async today | Priority |
|---|---|---|---|
| **`async_memoize`** | `_io.get_opener(memoize=True)` wraps the opener in `mezmorize.memoize`; reachable via `Fetch(url, memoize=...)` and the `memoize` conf key | `bado/io.async_url_read`/`async_url_open` take no `memoize`; the key is accepted and dropped | high |
| **`throttle`** | not implemented | not implemented (the removed `delay` was a pre-fetch sleep, not throttling) | medium |

### `async_memoize`

`memoize` is declared in the `Defaults` TypedDict, in `ExchangeRateConf`, and is exercised by
`fetch`'s own doctest — but only the sync path honors it. An async pipeline that re-fetches the
same url pays full cost every time, with no warning.

Design notes:

* The cache belongs at the **fetch** boundary (`async_url_read`/`async_url_open`), not in each
  module, so every async source inherits it the way sync sources inherit `get_opener`'s.
* `mezmorize` is sync-only and is already slated for replacement — see
  [rdp-connect.md](rdp-connect.md) § Milestone 10. **Do these together**: whatever replaces
  `mezmorize` should be async-aware from the start rather than growing a second, divergent cache.
* Keyed on the resolved url plus the arguments that change the payload (`params`, `encoding`);
  `repr_cache` in `riko/_serialize.py` already solves the unhashable-argument problem and
  documents the `_UNSUPPORTED` sentinel behavior.
* Needs an eviction/TTL story that sync memoization currently ducks — a long-lived async service
  is the likely consumer, unlike a one-shot sync script.

### `throttle`

Rate limiting has no implementation on either path. `delay` — removed as of this note — looked
like throttling but was a fixed `await async_sleep(delay)` *before* each fetch, so under
`async_map`/`AsyncCollection` with `connections=N` all N sleep concurrently and then fire
together. It spaced requests only at `connections=1`.

Design notes:

* Belongs alongside `connections` as a **collection/limiter-level** concern, not a per-fetch
  conf key — concurrency and rate are the two axes of the same budget.
* AnyIO `CapacityLimiter` bounds concurrency but not *rate*; a token bucket over
  `anyio.sleep` is the usual shape, and it must be **shared** across the task group to mean
  anything (the same reason `async_map`'s `budget` semaphore is shared).
* Per-host rather than global is what polite crawling actually needs; a single global rate is
  the easy case and probably the right first step.
* Interacts with retry/backoff in
  [execution-semantics.md](execution-semantics.md) — a 429 handler and a throttle want the same
  limiter, so design them together rather than bolting a sleep onto the fetch.

## 2c. Encoding-resolution precedence (sync/async parity)

Four paths decode the same bytes four different ways
([correctness-audit **R15**](correctness-audit.md#8-open-defect-register--features-branch-audit)):

| Path | Uses | Ignores |
|---|---|---|
| sync `_io.opener` | `r.encoding or encoding` | — |
| `async_url_open` (HTTP) | `NamedTextIOWrapper(BytesIO(data), encoding=encoding)` | the HTTP charset |
| `async_url_read` (HTTP) | `response.text` (httpx's own charset guess) | its explicit `encoding` argument |
| `fetchpage.async_parser` | `io.async_url_read(url)` | `objconf.encoding` entirely |

So the same feed can come back mojibake under `async_pipe` and clean under `pipe` — the
`C12` shape in [correctness-audit § 3](correctness-audit.md#c12--syncasync-divergence).

Resolve it once, in `bado/io.py`, with a single documented precedence:

```text
explicit configured encoding  ->  response charset  ->  ENCODING default (utf-8)
```

Notes:

* The order deliberately puts the caller **above** the server: a configured `encoding`
  exists precisely because the server's `Content-Type` was wrong. Sync's
  `r.encoding or encoding` has it backwards and should move to the same helper.
* One helper (`resolve_encoding(explicit, charset)`) shared by `async_url_open`,
  `async_url_read`, and `_io.opener` — the divergence is a missing argument, not a
  different algorithm, so a second copy would drift again.
* `fetchpage` (and any other async source that reads `objconf.encoding`) has to forward
  it; grep for `async_url_read(` / `async_url_open(` call sites when this lands.
* Do this **with** `async_memoize` (§ 2b): encoding is part of the cache key, so both
  changes touch the same signature.

## 3. The replacement decision rule

Do **not** require the AnyIO version to be faster. Replace a `bado` helper when **all** hold:

1. AnyIO now provides the same semantics;
2. cancellation/exception behavior is at least as good;
3. Riko needs no compatibility behavior AnyIO lacks;
4. benchmark performance is not materially worse;
5. the replacement deletes meaningful Riko code/tests.

So `Riko 41.2 µs` vs `AnyIO 42.0 µs` can still favor AnyIO if it removes 60 lines of concurrency
machinery — but `Riko 40 µs` vs `AnyIO 30 µs` does **not** justify replacing `_pool_stream` if the
AnyIO version loses backpressure or nested-budget semantics.

## 4. Async benchmarking & profiling methodology

**Benchmark first, profile second.** A profiler shows where time goes; an A/B benchmark shows
whether swapping a Riko abstraction for an AnyIO primitive actually helps. Today's
`riko/cli/benchmark.py` (`NUMBER=1`, `LOOPS=1`, `time()` timing) is a smoke benchmark.

### The current harness measures less than it appears to

Audited while removing `delay`; **fix these before trusting any sync-vs-async number**:

| Group | Benchmarks | State |
|---|---|---|
| Pure sleep | `baseline*`, pool variants, `baseline_async` | Fine — they call `sleep`/`async_sleep` directly over `iterable`. |
| Collections | `sync_collection`, `par_sync_collection`, `async_collection` | **Inert.** They pass `sleep=DELAY`, but no `sleep` parameter exists anywhere in riko — it lands in `**kwargs` and is dropped. These have never slept. |
| Fetch | `sync_pipeline`, `sync_pipe2`, `async_pipeline`, `async_pipe2` | **Was asymmetric.** `delay` was honored only by `async_url_read`; the sync path never forwarded it (`parse_rss(url, encoding=...)`) and `_io.opener`'s delay was a `logger.debug` stub. Async paid ~0.1 s × 13 feeds that sync did not, so the comparison measured the handicap. |

`delay` is now removed, so the fetch group is at least consistent — but it simulates no latency at
all, and local-file parsing gives async concurrency nothing to win against. Restoring that signal
belongs in the **harness**, not in a pipe's `conf`: a localhost HTTP server, or a sleeping wrapper
applied to *both* callables equally. The same fixture would give the collection benchmarks
something real to do, replacing the dead `sleep=` kwarg.

**Matrix benchmark** (turn `benchmark.py` into this) using `perf_counter_ns`, warmup, and sorted
percentile samples (`min`/`median`/`p95`), varying:

```text
items:        1, 10, 100, 10_000
concurrency:  1, 4, 16, 64
delay/item:   0, 100 µs, 1 ms, 10 ms      # delay=0 exposes framework overhead
result size:  tiny, medium, large
consumer:     fast / slow
ordering:     ordered / arrival-order
```

Plus realistic-I/O shapes (local FS, localhost HTTP, remote HTTP, CPU-heavy transform, mixed). **Do
not** use internet requests to compare schedulers — network variance overwhelms the signal.

**Profilers** — Scalene (async profiler attributes suspended `await` wall time to the line and
reports coroutine concurrency via `sys.monitoring` on 3.12+): `scalene run --cpu-only -m pytest
tests/benchmarks`; Pyinstrument with `async_mode="enabled"` for a call-tree that follows the async
context.

**Instrument `_pool_stream` instead of only CPU-profiling it** — AnyIO memory streams expose
`.statistics()`:

```text
current_buffer_used, tasks_waiting_send, tasks_waiting_receive
```

Buffer full + `tasks_waiting_send` high ⇒ consumer-bound; buffer empty + `tasks_waiting_receive`
high ⇒ producer/I/O-bound. Far more actionable than "`await result_recv.receive()` took 70% of wall
time."

## 5. Sequenced first changes

1. **Delete `async_partial`.**
2. **Delete or rewrite `gather_results`** via AnyIO 4.14 task handles (fixes the `None`-dropping bug regardless).
3. **Delete `async_json`;** use `response.json()` directly.
4. **Audit `async_reduce` callers** (`sort`, `regex`); delegate to `anyio.functools.reduce` if the strict async-reducer contract suffices.
5. **Rename `maybe_deferred` → `maybe_await`/`invoke`** (private; touches decorator machinery).
6. **Mark `async_return`** a next-major deprecation candidate (stable public API).
7. **Leave** `coop_reduce`, `async_map*`, `async_merge`, `_pool_stream` alone unless profiling shows a real problem.
8. **Repair the benchmark harness** (§4) — the dead `sleep=` kwarg and the missing latency
   fixture — before using it to justify any of the above.

The first three remove abstractions **without losing Riko-specific functionality**; `async_map*`/
`_pool_stream` are exactly where Riko *should* own an abstraction over AnyIO.

## 6. Relationship to the P-track

- **Unsequenced** — no phase owns this yet; slot it as refinement alongside P10's async carryovers.
- **`async_return` deprecation is SemVer-gated** (stable surface) → schedule with the P12+ stable-error/
  public-surface work and the migration-shim log tracked in
  [PHASE_CHECKLISTS.md](../PHASE_CHECKLISTS.md), not a patch release.
- **Live status** (done/next/suite count) lives only in the
  [PHASE_CHECKLISTS.md](../PHASE_CHECKLISTS.md) tracker — do not restate it here.
