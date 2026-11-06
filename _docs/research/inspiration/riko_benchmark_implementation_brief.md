# Riko Historical Performance Benchmarking — Implementation Brief

**Status:** Corrected implementation specification; the additions below are proposed,
not shipped. **Decision:** Do not implement `--benchmark-ref`, frozen benchmark
injection, or historical API adapters. **Target:** `nerevu/riko`, most progressed `next`
branch. **Starting point:** The existing Click-based `benchmark_commits_click.py`
supplied with this brief, plus `riko/cli/benchmark.py` on `next`.

## Objective

Evolve `benchmark-commits` into the single CLI for reproducible performance comparisons
across Riko's Git history. Keep historical orchestration in Python/Click; use Riko's
existing `benchmark.py` for native in-process measurements, Hyperfine for process-level
measurements, and Scalene separately to diagnose hotspots. Do **not** rewrite the tool
in Bash or integrate Rich-bench.

## Preserve existing behavior

The supplied runner already selects first-parent merge commits on `next`; supports
`(start, end]` bounds, a `--since` filter, seeded randomized order, a 20-merge sampling
threshold unless `--all` is set, detached temporary worktrees, historical `uv`
environments, Git-bisect-style positional command forwarding, `--benchmark-script`, a
configurable Python version and extras, timeouts, exit-125 skips, CSV output, and
resume. Preserve these capabilities and defaults except where this brief explicitly
changes measurement repetition.

The current `riko/cli/benchmark.py` has sync and async workloads, uses `timeit.repeat`
internally for sync tests, prints one timing line per test, and sets
`NUMBER = LOOPS = 1`. It performs self-imports (`from riko.cli.benchmark import ...`)
inside its timed setup. Do not assume historical copies accept new CLI arguments.

## Architecture and boundaries

1. **Orchestrator — `benchmark-commits`:** selects commits, creates/removes worktrees,
   prepares historical dependencies, invokes the measurement engine, records provenance,
   and aggregates results.
2. **Historical workload:** each selected commit uses its own checked-out
   `riko/cli/benchmark.py` and bundled fixtures. Do not overwrite benchmark files or
   inject newer code into older commits. Record the executed benchmark Git blob hash
   (`benchmark_blob`) and fixture fingerprints to identify comparable measurements.
3. **Native engine:** executes the benchmark command normally and parses its existing
   individual timing lines. Each full command invocation supplies one sample per named
   test; statistics aggregate repeated invocations. The inner `NUMBER` and `LOOPS`
   remain owned by historical `benchmark.py`.
4. **Hyperfine engine:** runs the same supplied command as an external command
   benchmark, with Hyperfine controlling subprocess warmups, repetitions, and
   measurement statistics. Record one **whole-command** timing result (`__command__`),
   even when `benchmark.py` prints internal timings. Never treat its aggregate wall time
   as a per-test timing.
5. **Scalene:** diagnostic follow-on for one selected commit/workload command, executed
   separately from timed runs; preserve its profiling report outside temporary
   worktrees.

**Important:** Native and Hyperfine measurements have different boundaries and must
never be compared directly. With the existing `benchmark.py`, Hyperfine times the entire
suite, including deliberate `sleep` baselines, imports, and startup. Do not interpret it
as `sync_workflow` latency. For a focused end-to-end command, users can forward a
different command (including pytest's existing `-k`/`-m` selectors); do not invent
`--test` or a new benchmark registry/driver.

## CLI contract (proposed additions)

- `--engine native|hyperfine`: default `native`.
- Common measurement options: `--runs N` (explicit sample count), `--warmup N`,
  `--min-runs N`, `--max-runs N`, `--prepare CMD`, and repeatable `--env KEY=VALUE`.
  Keep `--timeout` and existing historical-selection options.
- When `--runs` is absent, let Hyperfine choose its run count natively. For native,
  implement lightweight outer-process sample calibration (at least 10 samples, targeting
  roughly 3 seconds of total measurement, subject to explicit minimum/maximum limits).
  Do **not** change `NUMBER`/`LOOPS` automatically. If an explicit `--runs N` is
  supplied, disable auto calibration. Keep any warmup outside measurement and define it
  as **full command invocations** for both engines (not as in-process function warmups).
- `--prepare` executes before each sampled command invocation; `--env` applies to the
  benchmark process. Neither option may be silently included in timed setup. Keep
  `--runs` mutually exclusive with `--min-runs` / `--max-runs`.
- Preserve `benchmark-commits [OPTIONS] COMMAND [ARGS]...` with verbatim forwarding
  after the positional command, including pytest's native selectors. Do not add
  `--test`, custom tags, or separate function-selection syntax.
- Avoid reimplementing Hyperfine-only options such as shell handling, parameter scans,
  output formats, hardware counters, and outlier algorithms. Optionally allow advanced
  Hyperfine flags through an explicit engine-only passthrough in a later iteration, not
  in the core delivery.

### Example invocations (not available until implemented)

```bash
benchmark-commits --branch next --engine native benchmark
benchmark-commits --branch next --engine hyperfine benchmark
benchmark-commits --engine hyperfine --warmup 3 --runs 15 benchmark
benchmark-commits --engine native --all --start <older> --end <newer> benchmark
benchmark-commits --engine hyperfine manage test -px
```

The final example demonstrates argument forwarding, not a recommendation to use
test-suite wall time as a Riko pipeline performance metric.

## Historical comparability

- Riko's benchmark has changed across API eras: older revisions used `SyncPipe` /
  `SyncCollection`; current `next` uses reusable `Pipeline`. Run the benchmark belonging
  to each selected commit; do not retrofit newer benchmark functions into earlier
  revisions.
- Treat benchmark outputs as historical observations. Group comparisons by unchanged
  `benchmark_blob` and equivalent workload semantics. Matching names alone do not
  establish equivalence across source changes (e.g. old and current `sync_pipeline`).
  Explicitly label cross-version comparisons as unverified or omit them.
- The current benchmark reads XML feeds from `riko/data/` via `get_path`. Record
  relevant fixture hashes to detect changes in inputs; do not inject frozen fixtures.
- Record the historical benchmark blob hash, fixture hash(es), measured
  command/arguments, interpreter and dependency environment, engine, run settings, and
  host/platform information. Differences that affect comparability must produce distinct
  result identities.
- Prepare the historical `uv` environment **before** timing. Prefer invoking its
  resolved `.venv` Python/console executable directly during timed runs; don't include
  `uv sync` or dependency installation inside Hyperfine measurements. Preserve
  `--raw-command` semantics.
- Never claim numerical comparability for same-named tests unless their workload and
  measurement boundaries are equivalent. In particular, old `sync_pipeline` and current
  `sync_pipeline` do not necessarily represent the same work.

## Engine implementations

**Native:** Keep the existing benchmark output parser and per-test CSV records. For each
measured full invocation, collect the named timings already printed by the script;
aggregate their samples across invocations. If an arbitrary command doesn't print
recognized Riko timings, retain the existing `__command__` fallback. Report the native
value as the benchmark's reported per-call/best-of-loop timing, not as a fresh
whole-process measure. The current printed timing precision is limited; preserve raw
strings where useful and never invent more precision.

**Hyperfine:** Execute one resolved command per chosen commit, passing
warmup/run/prepare settings through, and request structured JSON output saved outside
the disposable worktree. Parse the measured wall-time distribution; retain all raw
Hyperfine JSON for audit. Map the primary summary to normalized `__command__` records.
If supported by the installed Hyperfine version, retain additional CPU/memory metrics
with their units and scope; do not emulate them for native.

## Results and failure handling

- Continue append/resume and incremental flush, but version/migrate the CSV schema
  deliberately. The existing schema cannot identify `native` versus `hyperfine`;
  extending it without migration would corrupt resume/comparison behavior.
- Key each completed run by commit **and** engine, historical benchmark blob, fixtures,
  forwarded command, and material measurement/environment settings. Changing engine or
  options must not skip prior results incorrectly.
- Include at least: commit, date, subject, engine, `measurement_scope`, historical
  benchmark blob hash, fixture identity, command identity, status/error, sample count,
  mean, median, standard deviation, minimum, maximum, and source artifact reference.
- Preserve exit code `125` as an explicit skip and distinguish incompatibility,
  installation failure, timeout, benchmark failure, and success. Clean up worktrees
  after every outcome. Keep raw Hyperfine results outside those worktrees.
- Report regressions only within the same engine, workload/command identity, fixture
  set, and comparable environment. A simple chronological CSV summary is sufficient
  initially; don't build a dashboard.

## Scalene follow-on (after core engines work)

Add a focused way to run a **single specified commit** with the same historical worktree
and command under Scalene. Save the profile outside the worktree, label it diagnostic,
and never use profiled durations as performance-regression evidence. Do not add
automatic mass-profiling of historical commits.

## Acceptance criteria / test plan

1. Native mode reproduces current named benchmark output for an eligible commit; an
   arbitrary forwarded command still works and falls back to `__command__` when
   appropriate.
2. Hyperfine mode works with auto repetitions when `--runs` is omitted; explicit
   warmup/runs/prepare/env options work; valid JSON is captured and normalized as
   `__command__`.
3. Each historical worktree runs its own `riko/cli/benchmark.py` without source
   injection; the recorded `benchmark_blob` reflects what was executed. Changed or
   missing workloads are never silently equated across revisions.
4. Historical benchmark changes, fixture changes, and engine changes cannot be silently
   combined or wrongly skipped by resume. Rerunning the same invocation resumes without
   duplicate rows.
5. Existing branch/range, sampling, seed, `--all`, argument forwarding, exit-125,
   timeout, and cleanup behavior remain correct. Neither active checkout nor Git history
   changes.
6. Unit tests mock Git/uv/Hyperfine as needed; integration tests use a small local Git
   repository/worktrees and a synthetic benchmark command. Add a smoke test against two
   genuinely compatible Riko revisions when feasible.
7. Document installation (Click already in Riko; Hyperfine and Scalene external optional
   tools), semantics, limitations, representative commands, and CSV schema. Validate
   against Riko's applicable tests, lint, and typing gates.

## Implementation order

1. Refactor the supplied Click runner minimally; add stable run identity, schema
   migration/tests, and provenance recording for the historical benchmark and fixtures.
2. Add the Hyperfine subprocess+JSON backend and shared CLI controls while retaining
   native per-test parsing.
3. Validate comparable historical ranges, update documentation and regression summaries.
4. Add optional targeted Scalene profiling only after the first three steps pass.

**Non-goals:** `--benchmark-ref`; benchmark-source or fixture injection; historical API
adapters; Bash rewrite; Rich-bench dependency; custom test selectors, tags, or
registries; automatically backporting new benchmarks to incompatible Riko APIs;
replacing pytest; rewriting historical commits; a generic benchmarking framework or
performance dashboard.
