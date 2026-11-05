# Python profiling tools — prior-art research notes

> Research/ADR notebook behind [performance.md](../gameplans/performance.md) (the
> actionable gameplan). Extraction notes from two external sources, read 2026-11-03 —
> kept for rationale and traceability, not as a task list. The decisions riko draws from
> them live in the gameplan's profiler table (§4); this note records the facts behind
> those decisions so they survive link rot.

## Sources

1. `austin-python` README — <https://github.com/P403n1x87/austin-python>
2. "The state of Python profiling in 2026", Gabriele N. Tornetta, 30 October 2026 —
   <https://p403n1x87.github.io/the-state-of-python-profiling-in-2026.html>

Both are by Austin's author, so the comparison favors Austin where the tools are close;
the factual claims about the other tools are consistent with their own documentation.

## 1. Taxonomy

Two axes classify every profiler:

* **Tracing vs. sampling.** A tracing (deterministic) profiler records every call: exact
  counts, heavy overhead, and attribution skew (the article cites one tracing profiler
  reporting 80 % for a function that took 25 %). A sampling profiler snapshots stacks at
  an interval: a statistical estimate whose error shrinks roughly as 1/√n, so sampling
  ten times faster gives about three times less noise from the same run.
* **In-process vs. out-of-process.** In-process tools run inside the target (and so can
  see allocations and per-line detail); out-of-process tools read the interpreter's
  memory from outside, so they can attach to a running process and add almost nothing to
  its run time.

The UMass study the article cites (Berger, Stern and Altmayer Pizzorno, 2022) measured
Austin, py-spy and Scalene at 0–2 % CPU-mode overhead against 73 % for `cProfile` and
more than 200 % for some others. Scalene's own figure is "typically 10–20 %".

## 2. The four sampling profilers compared

| | Tachyon | py-spy | Scalene | Austin |
|---|---|---|---|---|
| Process model | out-of-process | out-of-process | in-process | out-of-process |
| Default rate | 1 kHz (raisable) | — | — | 10 kHz |
| Native frames | placeholder frames only | Linux x86_64/aarch64, Windows | combined stacks | Linux, macOS, Windows |
| asyncio | task-aware stacks (3.15) | none: async functions are ordinary frames | wall-clock `await` time per line + count of waiting async tasks | task-level (3.14+): running vs. waiting per task |
| Memory | no | no | per-line allocations | RSS mode only |
| GPU | no | no | NVIDIA / Apple | no |
| Python versions | 3.15+ only | up to 3.14 | 3.13+ free-threaded (2.4) | 3.10–3.15 |
| Free-threaded builds | yes (3.15) | open issue | yes (2.4+, Oct 2026) | yes |
| Attach to a running process | yes (`attach PID`) | yes | no (must start under it) | yes (elevated privileges) |

Other tools the article places: **pyinstrument** (friendly call trees;
`async_mode="enabled"` follows the async context), **memray** ("serious memory work"),
`cProfile`/`profiling.tracing` (exact call counts).

## 3. CPython 3.14 / 3.15 changes that matter

* **Debug offsets table (3.14).** A structure at the start of the runtime state that
  tells external tools where interpreter data lives, without copying private headers;
  the foundation of PEP 768's remote debugging interface. It is what lets out-of-process
  profilers stop chasing per-version struct layouts.
* **Tachyon (3.15).** `profiling.sampling` in the standard library: `run`, `attach`,
  `dump`; `python -m profiling.sampling attach 12345`; 1 kHz default. Profiler and
  target must share the same minor version and build type (standard vs. free-threaded).
  "Start with Tachyon. It's already installed, and it's good."
* **asyncio task graph (3.14+).** Austin records which task each sample belongs to and
  follows a task from first to last sighting, giving both an aggregate flame graph and
  per-task flame charts with running vs. waiting time.

riko supports 3.12–3.14 (`requires-python = ">=3.12"`), so Austin's task-level
attribution works when profiling on a 3.14 interpreter, while Tachyon waits for 3.15
support; Scalene's per-`await`-line timing and Austin's non-task mode work on every
supported version.

## 4. Memory mode is not allocation profiling

Austin's memory mode measures the change in resident set size between samples — physical
memory the process actually touched, not bytes it asked for (allocate 512 MB, touch
half, RSS grows ~256 MB). For "which line allocated what" or leak hunting the article
points to an allocation profiler: Scalene or memray. Within riko, `tracemalloc` is the
cheap in-process option for a harness high-water mark.

## 5. Native stack unwinding

Austin 4.1 unwinds native stacks on Linux (x86_64, aarch64), macOS (the same method as
`samply`) and Windows (x86_64), showing interleaved Python and native frames; the
article claims it is the only out-of-process Python profiler doing so on macOS. To get a
consistent native stack it briefly suspends each thread per sample, so overhead grows
with the sampling rate: use a larger interval (1 ms to start) and avoid it in
production. It replaces the earlier `austinp` (libunwind) tool.

For riko this is the way to see `lxml`/`fastfeedparser` (the `perf` extra) time on the
macOS development machines.

## 6. Austin 4.x throughput

| Change | Wall-time samples/s | Per-sample time |
|---|---|---|
| 4.0 vs 3.7 | 54 k → 111 k (+2.1×) | 32.4 → 12.4 µs |
| 4.1 repeated-stack detection | 121 k → 166 k (+37 %) | 15.0 → 10.4 µs |

CPU mode: 20 k → 37 k samples/s across the same releases.

## 7. `austin-python`

* `pip install --user austin-python --upgrade`; needs the Austin binary, found via the
  current directory, `AUSTINPATH`, `~/.austinrc` (`binary = "/path/to/austin"`), or
  `PATH`. Tested on Linux, macOS and Windows with Python 3.9–3.14.
* Console scripts: `austin2speedscope` (Speedscope JSON), `austin2pprof` (Google pprof),
  `austin-query` (query a profile from the shell; text tables or JSON),
  `austin-compress` (aggregate raw samples).
* Formats: collapsed stacks and MOJO (the binary default since Austin 4).
* API: `austin.aio.AsyncAustin` (and threaded variants) with `on_sample`/`on_metadata`
  hooks for building tools; `austin.query.ProfileQuery.from_file(path)` with `top(n)`,
  `callers(fn)`, `filter(thread=..., task=...)`, `tree()`, `tasks()` and
  `task_stacks(name)` (3.14+ asyncio), results convertible with `to_dict()`.
* The article's before/after idiom:

  ```python
  from austin.query import ProfileQuery


  def hot(path):
      return {
          f"{e.location.filename}:{e.location.function}": e.own_pct
          for e in ProfileQuery.from_file(path).top(50)
      }
  ```

  diffed between `before.mojo` and `after.mojo`.

## 8. Agent-driven profiling

Two paths: the VS Code extension's MCP server (exposes a loaded profile through data
tools, plus "action tools" that search and zoom the flame graph while a person watches)
and `austin-query`, which any shell-capable agent can run. The loop the article
describes — ask "why is this endpoint slow?", the agent profiles, finds the hot path,
proposes a fix, profiles again — maps onto a repo skill wrapping the runner's profiler
follow-on once that exists.

## 9. The article's "which tool when"

* Python 3.15, quick start: Tachyon.
* Memory, GPU, or line-level detail, and you can start the program under it: Scalene.
* Older versions or attaching in production: py-spy or Austin; Austin covers 3.15 and
  free-threaded builds and samples faster.
* asyncio code: Austin (task-level, 3.14+), Tachyon (task-aware stacks, 3.15), Scalene
  (which `await` lines are slow).
* Native extensions, especially on macOS: Austin native mode.
* Agent-driven or teaching: Austin's MCP server or `austin-query`.

"The best profiler is the one people actually use."

## 10. What riko does not take

* GPU profiling (no GPU work in riko).
* The VS Code extension as a dependency of any workflow; `austin-query` is the portable
  surface.
* Austin's memory mode as a substitute for allocation profiling (§4).
* Any profiler as a package dependency; all stay external optional tools.
