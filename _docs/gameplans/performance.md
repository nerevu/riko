# Performance measurement gameplan

> **Scope:** An unsequenced refinement — not yet a P-track phase. Owns how riko
> *measures* performance: the `benchmark` console script's harness and output grammar,
> the historical-commit regression runner (`benchmark-commits`), and the profiler
> methodology. It changes no runtime contract; optimizing a measured code path stays
> with the owner of that code.
>
> **Provenance.** The implementation brief and supplied Click runner in
> `_docs/research/inspiration/` (`riko_benchmark_implementation_brief.md`,
> `benchmark-commits-click.py`); the async harness audit and profiler notes that lived
> in [bado-anyio-alignment.md](bado-anyio-alignment.md) §4 until 2026-11-03; the
> profiler landscape notes in `_docs/research/profiling-tools.md`.
>
> **Ownership boundary.** [execution-semantics.md](execution-semantics.md) owns runtime
> semantics. [bado-anyio-alignment.md](bado-anyio-alignment.md) owns the
> helper-replacement decision rule and the `_pool_stream` memory-stream instrumentation
> that specializes this plan to its audit. [testing.md](testing.md) owns
> `test_benchmark`'s test-side knobs (`RIKO_BENCHMARK_DELAY`, `RIKO_BENCHMARK_WORKERS`).
> [cli.md](cli.md) owns the Click command contract any new command uses.
> [release-readiness.md](release-readiness.md) and [extensibility.md](extensibility.md)
> consume benchmark evidence as gates; they do not define how it is produced.

## 1. Vocabulary

| Term | Meaning |
|---|---|
| **benchmark** | A named workload timed under a declared measurement boundary. The name is the workload's identity. |
| **measurement boundary** | What the timer brackets: an in-process call (`native`) or a whole process from exec to exit (`hyperfine`). Numbers from different boundaries are never compared. |
| **engine** | How a sample is taken: `native` parses the timing lines `benchmark.py` prints; `hyperfine` times the whole command externally. |
| **sample** | One full command invocation. Statistics aggregate samples; the inner `NUMBER`/`LOOPS` repetition stays owned by the historical `benchmark.py`. |
| **workload identity** | The git blob of the `benchmark.py` a commit carries, plus the fingerprints of the fixtures it reads. Every commit runs its *own* copy; there is no frozen or injected workload. Two commits whose workload identities differ are timing different code under the same names. |
| **result identity** | The tuple that makes two rows comparable: commit, engine, workload identity, forwarded command, material measurement controls (§3.4), interpreter/dependency environment, host. Any difference that affects comparability yields a distinct identity. |
| **profile** | A diagnostic of *where* time or memory goes in one invocation. Never regression evidence. |

## 2. The benchmark harness (`riko/cli/benchmark.py`)

`benchmark` is a shipped console script (`pyproject.toml` `[project.scripts]`); its
labels are asserted by `tests/functional/test_script.py::test_benchmark`.

### 2.1 What it measures today

Today's harness (`NUMBER=1`, `LOOPS=1`, `time()` timing, `timeit.repeat` with
self-imports in the timed setup) is a smoke benchmark. Audited while removing the
`delay` conf key; **fix these before trusting any sync-vs-async number**:

| Group | Benchmarks | State |
|---|---|---|
| Pure sleep | `baseline*`, pool variants, `baseline_async` | Fine — they call `sleep`/`async_sleep` directly over `iterable`. |
| Collections | `sync_workflow`, `async_workflow` | **Real work, no latency.** One Workflow v2 graph fans a fetch of every feed into a single `union` node and runs it through the v2 execution. The old `sync_collection`/`par_sync_collection`/`async_collection` rows and their dead `sleep=` kwarg are gone; there is no parallel variant because the execution has no concurrency option yet. |
| Fetch | `sync_module`, `sync_pipeline`, `async_module`, `async_pipeline` | **`*_module` is asymmetric.** `async_module` sleeps `RIKO_BENCHMARK_DELAY` (default 0.1 s) before each of the 14 fetches; `sync_module` does not, so the pair measures the handicap. `sync_pipeline`/`async_pipeline` are symmetric, one `Pipeline` run per feed with no delay. |
| Preparation | `sync_module_per_item`, `sync_prepared_per_item` | Fine — isolates per-call preparation cost from the prepared-call cost. |

Apart from `async_module`'s one-sided sleep, the fetch group simulates no latency, and
local-file parsing gives async concurrency nothing to win against. Restoring that signal
belongs in the **harness**, not in a module's `conf`: a localhost HTTP server, or a
sleeping wrapper applied to *both* callables equally. The same fixture gives the
workflow benchmarks a latency signal.

### 2.2 The output line is a contract

Each named test prints exactly one summary line:

```text
<name> - <NUMBER> repetitions/loop, best of <LOOPS> loops: <value> <secs|msecs|usecs>
```

Two consumers depend on it: the `benchmark-commits` native engine parses it (and must
keep parsing the *historical* copies it runs), and `test_benchmark` asserts the label
set. Rules:

1. **The line grammar is frozen.** A richer harness (§2.3) keeps one such line per test
   — its `<value>` stays the best loop's total for `<NUMBER>` repetitions, and the
   consumer derives per-call time by dividing — and prints any extra statistic
   (`median`, `p95`, `p99`, memory high-water mark) on its *own* line or behind an
   opt-in `--json` flag. Nothing is appended to the legacy line; the parser anchors on
   line end.
2. **Labels are identity.** Renaming a test is a new workload, not the same series
   continued; the runner never maps old names onto new ones.
3. **Precision is what the script prints.** The runner keeps the raw string and never
   invents digits beyond it.
4. **One parser reads all history.** Because each commit runs its own `benchmark.py`,
   the parser must accept every line grammar that has ever shipped. A change to the
   grammar adds an alternative to the parser; it never replaces the old one.

### 2.3 Matrix benchmark (turn `benchmark.py` into this)

Use `perf_counter_ns`, a warmup pass outside measurement, and sorted percentile timings
(`min`/`median`/`p95`/`p99`) plus the memory high-water mark (`tracemalloc` for Python
allocations; see §4 for why a sampling profiler's memory mode is not that), varying:

```text
items:        1, 10, 100, 10_000
concurrency:  1, 4, 16, 64
delay/item:   0, 100 µs, 1 ms, 10 ms      # delay=0 exposes framework overhead
result size:  tiny, medium, large
consumer:     fast / slow
ordering:     ordered / arrival-order
```

Plus realistic-I/O shapes (local FS, localhost HTTP, remote HTTP, CPU-heavy transform,
mixed). **Do not** use internet requests to compare schedulers — network variance
overwhelms the signal.

The matrix is additive: today's named tests keep their names and lines (§2.2); matrix
cells get new names. `RIKO_BENCHMARK_DELAY`/`RIKO_BENCHMARK_WORKERS` remain the test
suite's knobs ([testing.md](testing.md)), uncapped by default so numbers stay comparable
across commits.

## 3. The historical regression runner (`benchmark-commits`)

One CLI for reproducible performance comparisons across riko's git history. The supplied
Click runner is the starting point; it is evolved, not rewritten.

### 3.1 Preserved behavior

The runner already: selects first-parent merge commits on a branch; supports
`(start, end]` bounds and a `--since` filter; shuffles in seeded order and samples at a
20-merge threshold unless `--all`; checks each commit out into a detached temporary
worktree and removes it after every outcome; prepares that commit's own `uv` environment
(`--locked`, configurable Python version and extras); forwards a positional
`COMMAND [ARGS]...` verbatim in the `git bisect run` style, with `--benchmark-script`
and `--raw-command` variants; honors a per-invocation timeout; treats exit `125` as an
explicit skip; appends to a CSV and resumes from it.
**The active checkout and git history are never touched.** All of this stays, with the
measurement-repetition changes below.

### 3.2 Engines

| Engine | Boundary | Records | Owns repetition |
|---|---|---|---|
| `native` (default) | the per-call time each named test reports | one row per named test per invocation; `__command__` wall time only when the forwarded command prints no recognized line | the historical `benchmark.py` (`NUMBER`/`LOOPS`); the runner repeats *invocations* |
| `hyperfine` | the whole command, exec to exit | one `__command__` row from Hyperfine's JSON; extra CPU/memory metrics kept with units and scope when the installed version reports them | Hyperfine (warmup, runs, outlier handling) |

Native and Hyperfine numbers have different boundaries and are **never compared**. With
today's `benchmark.py`, Hyperfine times the whole suite including the deliberate `sleep`
baselines, imports and startup; it is not `sync_workflow` latency. For a focused
end-to-end command, forward a different command (pytest's own `-k`/`-m` selectors
included) — there is no `--test` option, tag system, or benchmark registry.

Hyperfine-only options (shell handling, parameter scans, output formats, hardware
counters, outlier algorithms) are not reimplemented. An explicit engine-only passthrough
may come later, not in the core delivery.

### 3.3 Historical workloads

Each commit runs the `benchmark.py` it carries, against the fixtures it carries. There
is no `--benchmark-ref`, and nothing is copied or injected into a checkout.

* The runner records each commit's workload identity (§1): the script's blob, which the
  supplied runner already captures, plus fingerprints of the 14 `riko/data/` feeds the
  script reads.
* A commit without the script is `skipped`, as the supplied runner already does.
* Comparisons are grouped by unchanged workload identity. A comparison across a workload
  change is labelled unverified or omitted, never reported as a speed change: matching
  names alone do not establish equivalence, and old `sync_pipeline` and current
  `sync_pipeline` do not necessarily represent the same work.
* Newer benchmark functions are never retrofitted into older revisions.

### 3.4 Measurement controls

Shared by both engines: `--runs N`, `--warmup N`, `--min-runs N`, `--max-runs N`,
`--prepare CMD`, repeatable `--env KEY=VALUE`, plus the existing `--timeout`. `--runs`
is mutually exclusive with `--min-runs`/`--max-runs`.

* Warmup is **full command invocations** for both engines, never in-process function
  warmups, and never inside measurement.
* With `--runs` absent, Hyperfine chooses its own count; `native` calibrates outer
  samples lightly (at least 10, targeting roughly 3 s total, within the explicit
  min/max). Calibration never changes `NUMBER`/`LOOPS`; an explicit `--runs` disables
  it.
* `--prepare` runs before each sampled invocation and `--env` applies to the benchmark
  process; neither is ever inside timed setup.
* The historical `uv` environment is prepared **before** timing; timed invocations call
  the resolved `.venv` interpreter or console script directly, never `uv sync`.

### 3.5 Results, identity, failure handling

* Rows are keyed by result identity (§1), so changing engine, options, fixtures or
  workload can neither overwrite nor wrongly skip prior rows, and rerunning the same
  invocation resumes without duplicate rows.
* The CSV schema is versioned and migrated deliberately: the supplied schema cannot name
  the engine, so extending it without migration would corrupt resume/comparison. Columns
  at minimum: commit, date, subject, engine, measurement scope, workload blob, fixture
  identity, command identity, status, error, sample count, mean, median, standard
  deviation, min, max, source artifact reference.
* Status taxonomy: `ok`, `skipped` (exit 125 or no script at that commit),
  `incompatible` (the forwarded command or its arguments do not exist at that revision),
  `install-error`, `timeout`, `error`. Raw Hyperfine JSON and any profile are kept
  **outside** the disposable worktree for audit.
* Regressions are reported only within one engine, workload/command identity, fixture
  set and comparable environment. A chronological CSV summary is enough; there is no
  dashboard.

### 3.6 Open decisions

* **Where the runner lives.** `benchmark` is a shipped console script, but a
  git-worktree/`uv` orchestrator is developer tooling: a `manage benchmark-commits`
  command (the Click contract in [cli.md](cli.md), a private
  `riko/cli/_benchmark_commits.py`) or a `.claude/`-side script. The `manage` command is
  the leaning, since `manage test` already is the developer entry point. Hyperfine,
  Scalene and Austin stay external optional tools, never dependencies.
* **Default branch.** The supplied runner defaults to `--branch next`; the default
  should name the branch that carries the experimental mainline at the time it lands.

## 4. Profiling methodology

**Benchmark first, profile second.** A benchmark says *whether* a change helped; a
profile says *where* time goes. Profiled durations are never regression evidence, and
profiling is a follow-on for **one** selected commit and workload (same prepared
worktree and command), never mass profiling of history.

Prior art: `_docs/research/profiling-tools.md` (austin-python README and "The state of
Python profiling in 2026", read 2026-11-03). What riko takes from it:

| Need | Tool | Why / caveat |
|---|---|---|
| Line-level CPU, wall-clock `await` time per line and how many async tasks wait at once, per-line memory; program started under the profiler | **Scalene** (`scalene run --cpu-only -m pytest ...`) | In-process sampling, 10–20 % overhead by its own figures. Its Python/native split is unreliable in multi-threaded code — relevant to `baseline_threads` and any thread-pool path. |
| Attach to a running process without restart (a long-lived pub/sub or orchestration service); lowest overhead; highest sample rate | **Austin** via `austin-python` (`austin2speedscope`, `austin2pprof`, `austin-query`) | Out-of-process sampling, 0–2 % overhead, 10 kHz default; free-threaded builds supported; task-level asyncio attribution on 3.14+ (a supported riko interpreter, so profile there for it). Needs elevated privileges to attach. |
| Native frames interleaved with Python, especially on macOS (the `perf` extra's `lxml`/`fastfeedparser`) | **Austin native mode** | Pauses threads per sample; use a 1 ms interval, development only. |
| A readable call tree that follows async context | **Pyinstrument** with `async_mode="enabled"` | Friendly for first looks; sampling, so no call counts. |
| Allocations and leaks | **memray** (or `tracemalloc` for the matrix's high-water mark, §2.3) | A sampling profiler's memory mode (Austin) reports resident-set deltas — physical memory touched, not bytes requested — so it is not an allocation profiler. |
| Exact call counts | `cProfile` / `profiling.tracing` | Tracing: ~73 % overhead and skewed attribution; never for timing comparisons. |
| Agent-driven loops ("why is this slow?" → profile → fix → profile again) | `austin-query` / `ProfileQuery.top()` diffs before and after a change | Text/JSON output any shell-capable agent can consume; a natural fit for a repo skill once the runner exists. |
| Zero-install default once the floor reaches 3.15 | **Tachyon** (`python -m profiling.sampling`) | Standard library, 1 kHz default, task-aware stacks; profiler and target must share minor version and build type. |

Rules of use:

* **Sampling accuracy grows with √n.** A short benchmark needs a high sample rate or
  more runs before its hot path is trustworthy; prefer more invocations over a longer
  `LOOPS`.
* **Instrument before CPU-profiling a scheduler.** For the `bado` memory-stream pipeline
  the actionable signal is the stream's `.statistics()` (buffer use, tasks waiting to
  send/receive), owned in [bado-anyio-alignment.md](bado-anyio-alignment.md) §4; a flame
  graph of `await receive()` says only that something waited.
* **Keep profiles outside worktrees**, labelled diagnostic, beside the raw engine
  output.

## 5. Explicit non-goals

* a Bash rewrite of the runner, or a Rich-bench / pytest-benchmark dependency;
* `--test`, tags, or a benchmark registry/driver — pytest's selectors and verbatim
  command forwarding are the selection surface;
* a performance dashboard, or any generic benchmarking framework;
* frozen workloads: injecting a `benchmark.py` or fixtures from another ref into a
  checkout (`--benchmark-ref`);
* comparing `native` and `hyperfine` numbers, or same-named tests across a workload
  change;
* profiled durations as regression evidence, or automatic mass profiling of history;
* historical API adapters, backporting new benchmarks to incompatible historical APIs,
  rewriting commits, or replacing pytest;
* internet requests when comparing schedulers;
* profilers or Hyperfine as package dependencies (external optional tools, documented).

## 6. Sequenced changes

1. **Repair the harness** (§2.1, §2.3): the latency fixture, `perf_counter_ns`, warmup,
   percentiles — preserving the output line (§2.2). Prerequisite for
   [bado-anyio-alignment.md](bado-anyio-alignment.md) §5 step 8 and for
   [release-readiness.md](release-readiness.md)'s "benchmark the private sync/async
   adapters and canonical identity encoder before freezing optimization choices".
2. **Runner core**: minimal refactor of the supplied Click runner; stable result
   identity; CSV schema version + migration + tests; workload and fixture fingerprints
   (§3.3, §3.5).
3. **Hyperfine engine** and the shared measurement controls (§3.2, §3.4), keeping native
   per-test parsing.
4. **Validate** comparable historical ranges; document installation
   (Hyperfine/Scalene/Austin as external optional tools), semantics, limitations,
   representative commands and the CSV schema.
5. **Profiler follow-on** (§4) for one commit/workload, only after 1–3 pass.

Acceptance:

1. `native` reproduces today's named output for an eligible commit; an arbitrary
   forwarded command still works and falls back to `__command__` when appropriate.
2. `hyperfine` works with auto repetitions when `--runs` is omitted; explicit
   warmup/runs/prepare/ env work; valid JSON is captured and normalized as
   `__command__`.
3. Each commit's own `benchmark.py` runs in its checkout; a commit without it is
   `skipped`, never given fabricated numbers; a workload change between adjacent commits
   is reported as such.
4. Workload, fixture, and engine changes cannot be silently combined or wrongly skipped
   by resume; rerunning the same invocation adds no duplicate rows.
5. Branch/range, sampling, seed, `--all`, forwarding, exit-125, timeout and cleanup
   behavior stay correct; neither the active checkout nor git history changes.
6. Unit tests mock git/`uv`/Hyperfine; integration tests use a small local repository
   with worktrees and a synthetic benchmark command; a smoke test covers two genuinely
   compatible riko revisions when feasible.
7. The applicable test, lint and typing gates pass.

## 7. Relationship to the P-track

* **Unsequenced** — no phase owns this; its natural slot is before the pre-1.0
  optimization freeze in [release-readiness.md](release-readiness.md) and alongside
  [bado-anyio-alignment.md](bado-anyio-alignment.md), whose helper audit depends on step
  1.
* **Consumers.** [extensibility.md](extensibility.md) lists "benchmark/regression
  evidence" among its exit items; [release-readiness.md](release-readiness.md) wants
  adapter and canonical-encoder benchmarks before freezing optimization choices. Both
  read this plan's output; neither defines it.
* **Live status** (done/next) lives only in
  [PHASE_CHECKLISTS.md](../PHASE_CHECKLISTS.md).
