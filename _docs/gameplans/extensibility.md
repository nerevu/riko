# Extensibility & ecosystem gameplan

> **Provenance.** Extracted from `docs/ROADMAP.md` Part V so the roadmap can stay a
> high-level overview. This gameplan is the authoritative extensibility/ecosystem plan
> (module contract, plugins, workflow spec, observability, adapters, drivers, GUI). Section
> references like §N point back to [RUNTIME_CONTRACT.md](../RUNTIME_CONTRACT.md) (the runtime
> contract). Pieces that already have
> their own detailed plan link to [connectors.md](connectors.md), [cli.md](cli.md), and
> [mcp.md](mcp.md).

This gameplan folds in the most valuable conclusions from two rounds of prior-art research on
issue [#10](https://github.com/nerevu/riko/issues/10): the original six-project survey
(Pypes, Mario, RssPercolator, Plagger, Turtle, node-machine) and a later competitive
comparison (2026-08-07) against modern Python ETL and stream-processing libraries —
[Bonobo](https://www.bonobo-project.org/), [petl](https://petl.readthedocs.io/),
[Singer](https://www.singer.io/), [Streamz](https://streamz.readthedocs.io/),
[Bytewax](https://docs.bytewax.io/), and [FastPipe](https://pypi.org/project/fastpipe/). This gameplan is itself the research record for both rounds (prior-art sources at the end). It is the **contracts and extensibility plane** that complements the **data
plane** of the RDP/Connect roadmap in Parts I–II, and is dependency-ordered, not a calendar
commitment.

**Positioning refinement (2026-08-07 comparison).** Locality alone is not riko's
differentiator — Bonobo, petl, Streamz, FastPipe, and single-worker Bytewax all run from
ordinary Python. The defensible intersection is *configuration-driven reusable pipes +
first-class feed/web and record transformations + shared sync/async/local-parallel APIs over
one pipe vocabulary + lazy `send`/`receive` fan-out + workflows-as-data*. Riko sits between
"just write a Python loop" and "adopt a dedicated data platform"; every item here is judged
by whether it deepens that intersection rather than reproducing infrastructure another
project already specializes in (see the [E8](#e8-prior-art-research-conclusions) product
test).

Where an item overlaps an existing section it references that section instead of restating
it. The organizing conviction is **contracts before interfaces**: CLI, GUI, plugins, and
drivers must all consume one module/workflow contract rather than invent parallel models.

## E0. Roadmap principles

1. **Contracts before interfaces.** CLI, GUI, plugins, and drivers consume one contract.
2. **Local semantics are authoritative.** Generated code and every execution driver must
   match the in-process executor (the codegen-vs-executor parity tests already enforce this
   for built-ins).
3. **Explicit ports, errors, and side effects.** A module contract states what it accepts,
   emits, mutates, and depends on (see §4 execution characteristics).
4. **Optional integrations stay optional.** Plugin loading, OpenTelemetry, cloud SDKs, and
   protocol clients must not inflate the minimal install.
5. **Version data, not implementation details.** Workflow files and plugin contracts need
   schema versions and migrations; private Python objects are not a durable storage format.
6. **Secure by default.** Installing a package is a trust decision; riko must not silently
   fetch or execute remote code.
7. **Evidence before optimization.** Performance work is tied to reproducible workloads and
   measured regressions (see Milestone 9 and the `benchmark` CLI).

## E1. Module contract v1 (self-describing)

Borrows named ports from Pypes and machine-readable definitions from node-machine. Extends
the existing `ModuleMetadata` (§24) and the execution-characteristic `Opts` (§4) into a
versioned, complete module definition — the highest-value idea in the research, because it
unlocks plugin discovery, workflow validation, generated docs, CLI inspection, GUI forms,
compatibility checks, and remote-execution boundaries. It must precede E2, E3, and E7.

A `ModuleDefinition` should expose at least: stable name + contract version; type and
supported subtypes; sync/async availability; input/output ports with cardinality;
configuration schema, defaults, required values, and deprecations; item-field expectations
and emitted-field behavior; named error outcomes / documented exception classes;
side-effect flags — reuse the §4 `side_effects`/`determinism` opts; streaming
characteristics — reuse the §5 `boundedness`/`ordering` opts; concurrency safety and
cancellation support; short description, examples, docs URL; distribution name + version for
external modules.

**Explicit over inferred (2026-08-07 comparison).** The competitive review adds that several
capabilities must be *declared*, not inferred from decorator type, so the CLI, compiler,
validator, GUI, and future drivers can reason about a workflow without hard-coding module
names: supported execution modes (sync / async / thread-safe / process-safe — the
prerequisite for the per-pipe policy in [E6](#e6-experimental-execution-drivers), motivated
by FastPipe); source / transform / aggregate / sink role; lazy vs buffering vs materializing
behavior; bounded vs unbounded input suitability; ordering guarantees; stateful vs stateless
(per the §15 definition of module state); fan-in/fan-out cardinality; schema/field
expectations where knowable; a checkpoint/recovery capability slot — present even when the
built-in value is `none` (Bytewax); and a temporal/windowing capability slot reserved for
[E4](#e4-observability-hooks). Each module also declares what it expects from `Context` (§18)
— inputs, resources, event sinks — rather than reaching into global state (Bonobo's
service-injection lesson, captured without adding a parallel service container).

Deliverables: extend `ModuleMetadata` or add a versioned `ModuleDefinition`; generate
configuration JSON Schema from the typed configs (`riko/types/configs.py` via `gen-config`);
add `riko module list|show NAME|schema NAME` and `riko pipeline validate FILE|explain FILE`;
export the built-in catalog as deterministic JSON for docs/GUI; add a contract-conformance
test helper for module authors.

Acceptance: all built-in modules pass one conformance suite; the catalog generates without
importing uninstalled optional deps; documentation tables are generated from the catalog,
not hand-maintained; unknown config keys, missing required values, and invalid port
connections produce actionable validation errors.

## E2. Plugin ecosystem v1

Completes the entry-point discovery deferred in §24. Borrows Plagger's plugin ecosystem and
node-machine's reusable packs. The CLI-side command-plugin discovery is detailed in
[cli.md](cli.md).

Discovery uses Python package-metadata entry points, e.g.:

```toml
[project.entry-points."riko.modules"]
example = "riko_example:modules"
```

The loaded object returns module definitions (E1) or invokes a public registration function.
Import-path scanning and remote code downloads are not the default discovery mechanism.

Deliverables: add `riko.ext.register` and a documented registry protocol; discover via
`importlib.metadata.entry_points()`; deterministic name-conflict and override rules; record
provider distribution/version, contract version, and load errors; add `riko plugin
list|inspect|doctor`; publish a minimal plugin template (tests, typing, packaging, docs);
support disabling plugins by name/distribution; add compatibility checks against riko and
module-contract versions.

**Security requirements (secure by default):** never install plugins while loading a
workflow; never download or execute remote code from a workflow definition; display plugin
provenance in validation, execution plans, and errors; permit an application-supplied
allowlist/denylist; document that an installed Python plugin has the same process privileges
as the host application.

Acceptance: a separately distributed package can add a processor/operator/splitter without
modifying `riko.modules`; plugin failures are isolated during discovery and reported without
hiding healthy modules; a workflow validates against an installed plugin without executing
it; built-in and third-party modules use the same definition and conformance APIs.

## E3. Workflow specification v1

Gives the existing JSON pipe-def and compact DAG formats a versioned, interoperable storage
contract. Borrows the declarative-recipe approach from Plagger and RssPercolator.

Design: canonical JSON-compatible data model; explicit `format_version`; stable node IDs and
explicit source/target ports (closes the compact-DAG named-port gap noted in §24 baseline);
full support for linear, fan-out, fan-in, split, named inputs, and terminal outputs;
optional YAML authoring that normalizes to the canonical model; environment-independent core
document (secrets/inputs are references, not embedded credentials); deterministic
serialization for reviewable diffs; forward-migration tools and explicit rejection of
unsupported future versions.

Deliverables: publish a JSON Schema 2020-12 document for workflow v1; define the canonical
normalized model and keep the compact DAG as convenience syntax; add optional metadata,
parameters, resource references, and declared outputs; round-trip tests for JSON, YAML,
normalized objects, and generated Python (extend the existing codegen round-trip tests in
`tests/internal/test_compile.py`); add `riko pipeline format|migrate|diff|graph`; define a
recipe-directory convention with example inputs and expected-output assertions; add
digest/signature fields only as integrity metadata (no implied trust in referenced code).

Acceptance: every representable in-process pipeline round-trips through workflow v1 without
losing port information; workflow files remain usable across patch/minor releases via
validation or documented migration; a GUI can render node forms and connections from the
schema + catalog alone; secrets are supplied at runtime, never serialized into examples.

## E4. Observability hooks

Borrows Mario's explicit lifecycle and Turtle's operational granularity. **Extends — does
not duplicate** — the retry policy (§11), error/disposition policies (§12), and aggregate
pipe counters (§12.5).

New surface: lifecycle events for pipeline / module / item-batch / retry / cancellation /
resource-closure; optional callbacks or an event sink on `Context`; structured execution
records (workflow ID, run ID, module ID, provider, duration, counts, outcome); **optional**
OpenTelemetry *API* integration for traces/metrics without requiring an SDK in the core
install; bounded diagnostic sampling so item payloads are never logged by default;
execution-plan estimates at known buffering/materialization boundaries.

**Bounded streaming semantics (Streamz / Bytewax).** Borrow the *semantics and metadata*,
not the runtime. Near-term: document and expose backpressure/buffering boundaries
consistently; make bounded concurrency settings inspectable in execution plans (§6); evaluate
finite sliding/count windows as ordinary operators (§15); and define what "stateful" means
for a riko module so E1 can declare it. Durable checkpointing/recovery, keyed distributed
state, and worker scaling stay out of core — reserved for an optional driver contract
([E6](#e6-experimental-execution-drivers)) that must prove it can remain optional.

Acceptance: instrumentation-disabled overhead is negligible on benchmarked paths;
instrumentation never records full item payloads unless explicitly opted in; the metrics set
is the one already enumerated for Connect (§12.5 counters, plus wall/active time, in-flight
task count, and peak memory).

## E5. Adapter and connector packages

Borrows Mario's file-like/subprocess adapters and RssPercolator's multi-source/multi-sink
model. Complements the Feed source/sink work in
[async Feed integration](highergov-feed.md#async-feed-integration) and the full connector
plan in [connectors.md](connectors.md).

Deliverables: define source and sink adapter protocols around the module contract (E1);
first-class local adapters for file-like objects, iterables, async iterables, stdin/stdout,
and subprocess streams; standardized multi-source merge and multi-sink broadcast with
documented ordering and failure policy (see §8 merge); publish recipe packs (feed
aggregation, file conversion, HTTP enrichment, notifications); connector contract tests
against local fixtures and fake servers, not live services.

**Prioritization rule:** a connector belongs in core only when it is broadly useful, small
in dependency footprint, and deterministically testable; otherwise it is a plugin
distribution (E2). This is the §23.1 "a protocol is a source/sink adapter, not a runtime
concern" rule applied to packaging.

**Connector contracts as a separate concern (Singer).** Keep transformations as ordinary
pipes, but treat source/sink interoperability as its own small contract layered on E1 (and
distributed as plugins per E2): standardized discovery/config; schema/field metadata where
available; incremental cursor/state handoff for sources that support it; explicit resource
ownership and close semantics; source/sink provenance in workflow inspection. Prefer optional
adapters to Singer taps/targets over reimplementing their catalog/replication ecosystem.

**High-value built-ins over generic breadth (petl).** Add a built-in only when it (1) recurs
across workflows, (2) has non-trivial streaming/materialization semantics worth
standardizing, (3) benefits from config/metadata/compilation support, and (4) does not turn
riko into a dataframe engine. The bar is higher than "another wrapper around a one-line
function" — `udf` already covers one-off logic. Candidate areas to evaluate:
reconciliation/conflict detection, validation, richer grouping/aggregation, and
schema-oriented record operations.

## E6. Experimental execution drivers

Borrows Turtle's driver boundary and scatter/gather model, but postpones cloud-specific work
until local contracts are stable. Complements the RDP/Connect actor model (§17, Milestone 8).

A driver accepts a validated execution plan and reports standardized outcomes; it must not
reinterpret graph structure or module semantics. Deliverables: an experimental driver
interface outside the stable API tier; a reference local driver that delegates to the
existing executor; a process-pool driver for modules explicitly marked serializable /
process-safe (reuse the §4.3 process-execution serialization boundaries); scatter/gather
planning for eligible stateless modules with bounded concurrency; specified idempotency,
retries, cancellation, artifact transfer, and result ordering.

**Per-pipe execution policy (FastPipe), deferred behind E1.** FastPipe moves one pipeline
through async, process, and thread pipes with adapters between them. Riko should not copy
this until the module contract (E1) can answer whether a pipe is safe and useful under a
given mode. Only then investigate a workflow-level policy — e.g. `fetch → async / high
concurrency`, `parse → process pool`, `store → thread pool` — separate from the
pipeline-wide execution mode. Existing simple defaults must be preserved: per-pipe execution
is an explicit optimization, never required boilerplate.

Non-goals for the first driver release: a scheduler service, a workflow database, automatic
cloud deployment, transparent execution of arbitrary installed modules on untrusted workers,
or exactly-once claims (consistent with §27).

## E7. Visual tooling and 1.0 readiness

Addresses the GUI question without coupling UI to the engine. Pypes shows the value of a
graph editor; the Yahoo! Pipes experience warns that large visual pipelines can become
harder to manage than text — so the GUI **complements** reviewable workflow files, it does
not replace them.

GUI (separate repository, versioned independently): generate the node palette, forms,
validation, and help from module definitions (E1); import/export workflow v1 (E3) without
private riko objects; graph validation before execution; a read-only execution plan and
event stream (E4) before any editing-time execution; source/diff/search/grouping/subflow-
collapse for large pipelines; secrets stay in the host app. Acceptance: the editor works
against a static exported catalog without importing riko in the browser; all validation
rules also exist in the Python library and CLI.

**1.0 readiness** (borrowing node-machine's conformance-badge idea): publish stable API,
extension API, module-contract, workflow-schema, and compatibility policies; author guides
for plugins, workflows, and drivers; a conformance-badge process driven by automated tests;
a curated recipe gallery with reproducible fixtures; benchmark history and regression
thresholds; deprecation/migration windows. Ship 1.0 only after at least one external plugin
and one external workflow consumer validate the contracts, and no open P0 correctness issue
remains in execution, routing, lifecycle, or serialization (see §27 non-goals and §26
Milestone 10).

> **Boundary:** E7 owns the **ecosystem** side of 1.0 (conformance badges, published stable/
> extension/contract/schema policies, deprecation/migration windows). The **internal DX/API-shape
> polish and the release/package-fidelity gate** (config strictness, clean-break Pipeline/Execution
> split, `Collection`→`Pipeline(source=…)`, `with_config`/`executor=`, pub/sub 1.0 contract,
> wheel/PyPI CI, the Must-land/Preferred/Can-wait triage) live in
> [release-readiness.md](release-readiness.md).

## E8. Prior-art research conclusions

Issue #10 named six projects. Their implementations are dated, but several design ideas
remain useful; each is mapped to where it lands above.

| Project | Borrowed idea | Lands in | What riko does not copy |
|---|---|---|---|
| Pypes | Flow-based graphs of black-box components through named ports; one graph model shared by editor and runtime | E1, E3, E7 | Stackless / Python 2 assumptions; a monolithic drag-and-drop app coupled to the runtime |
| Mario | File/socket/generator/subprocess adapters; explicit start/close; partial-chunk handling | E4, E5 | A byte-pump as the primary data model (riko keeps mapping-like items + iterable streams) |
| RssPercolator | Async multi-source fetch, multiple destinations, filters in declared order | E5, §8 | Feed-specific concepts embedded in the core engine |
| Plagger | Plugin architecture, declarative YAML recipes, end-to-end example gallery | E2, E3 | An implicit global hook system with weak contracts |
| Turtle | Composition-vs-execution boundary, local/remote chaining, scatter/gather, package integrity | E6 | Cloud-first architecture; auto-executing downloaded code |
| node-machine | Machine-readable definitions, typed inputs, named exits, generated docs/tests, reusable packs | E1, E7 | Multiple overlapping invocation styles and deferred-control APIs |

The 2026-08-07 competitive comparison against modern ETL/streaming libraries adds a second
set of borrowed ideas:

| Project | Borrowed idea | Lands in | What riko does not become |
|---|---|---|---|
| Bonobo | Injectable runtime services/resources through an explicit context boundary | E1, E4 (`Context`) | A framework whose primary abstraction is dependency injection or graph execution |
| petl | Purpose-built table algebra and data-quality primitives | E5 (built-in vocabulary) | A dataframe/table engine or relational query system |
| Singer | Standardized tap/target contracts, schema messages, incremental replication state | E2, E5 | A source-to-destination replication protocol as its main job |
| Streamz | Continuous push graphs, live windows, branching, backpressure | E4 | A reactive/event framework where push semantics replace the iterator core |
| Bytewax | Durable keyed state, recovery, partitioned sources, distributed workers | E4 (metadata), E6 (optional driver) | A distributed stateful engine with checkpoint/recovery machinery in core |
| FastPipe | Explicit per-pipe thread/process/async modes with inter-pipe adapters | E1, E6 | A low-level concurrency framework with a tiny transformation vocabulary |

### Non-goals clarified by the 2026-08-07 comparison

Extends the §27 non-goals and the E6 first-release non-goals. Unless the product direction
changes materially, these stay outside core — interoperate rather than absorb:

- Bytewax-style distributed worker coordination and durable recovery;
- Streamz-style full reactive dataframe semantics;
- petl-style comprehensive relational/table algebra;
- Singer's full connector catalog and replication protocol ecosystem;
- Bonobo-style service-container-centric application architecture;
- FastPipe-style concurrency primitives as the primary user-facing abstraction;
- task scheduling/orchestration, durable retries, hosted workflow management, cluster deploy.

### Product test for new proposals

> Does this make riko better at expressing, inspecting, or executing configuration-driven
> record-stream transformations, or does it mainly reproduce infrastructure another project
> already specializes in?

If the latter, prefer an adapter or integration (E5/E6) over expanding core. The goal is not
a smaller version of every ETL/streaming system, but an increasingly coherent version of
riko's particular intersection — reusable configured pipes, rich feed/web and record
transformations, multiple local execution models, lazy fan-out, and workflows-as-data.

### Dependency ordering

```text
E1 module contract
   ├── E2 plugins
   └── E3 workflow spec
          └── E4 observability
                 └── E5 adapters
                        └── E6 drivers
                               └── E7 GUI + 1.0
```

The GUI may be prototyped early against exported static schemas, but it must not fork the
runtime contracts.


---

> **Runtime-contract section extracted from ROADMAP §24.** E1/E2 continue this section — the module-contract & plugin ecosystem plan. `§N` refs point to [RUNTIME_CONTRACT.md](../RUNTIME_CONTRACT.md).

## 24. Module registry and plugins

> **Shipped:** see [IMPLEMENTED.md §24](../IMPLEMENTED.md#24-module-discovery-shipped)
> (`pkgutil`-based `list_modules`; built-in name/namespace reservation). **Remaining:** the
> entry-point/runtime `ModuleRegistry` (P8-planned) below.

Initial registry:

* static built-in module registry
* unqualified names reserved for built-ins
* namespaces reserved now
* entry-point discovery deferred
* **`pipe_` / `pipe:` reserved at registration** — `ext/resolver.py` routes any name with
  those prefixes to the pipeline resolver *before* consulting `ModuleRegistry`, so a
  registered leaf extension named `pipe_transform` can never resolve
  ([correctness-audit **R18**](correctness-audit.md#8-open-defect-register--features-branch-audit)).
  Registration must reject the prefixes with a riko-owned message rather than accepting a
  name that silently never resolves; trying the registry first is the alternative, but it
  makes resolution order depend on install state, which the reservation rule above exists
  to avoid.

One distribution and internal plugin architecture are sufficient initially. External connectors should use optional dependencies and plugin boundaries.

**One-sided registration (execution-mode adaptation).** A `ModuleDefinition` needs only the
implementation the author actually wrote — the runtime adapts the missing side
([execution-semantics.md § Execution-mode adaptation](execution-semantics.md)):

```python
@processor
def pipe(item, **kwargs): ...


register(ModuleDefinition(name="example.normalize", sync_pipe=pipe))
```

```python
@processor
async def pipe(item, **kwargs): ...


register(ModuleDefinition(name="example.lookup", async_pipe=pipe))
```

Supplying both `sync_pipe` and `async_pipe` stays available as an optimization when the two
implementations genuinely differ; it is never required merely for sync/async parity.


## Prior-art sources

The research behind E0–E8 (folded in from the retired `lessons.md`). **Round 1** — issue
[#10](https://github.com/nerevu/riko/issues/10) six-project survey:
[Pypes](https://github.com/fullscale/pypes) ·
[Mario](https://github.com/colinmarc/mario) ·
[RssPercolator](https://github.com/olviko/RssPercolator) ·
[Plagger](https://github.com/miyagawa/plagger) ·
[Turtle](https://github.com/iopipe/turtle) ·
[node-machine](https://github.com/node-machine/machine).
**Round 2** (2026-08-07) — modern ETL/streaming: Bonobo, petl, Singer, Streamz, Bytewax,
FastPipe (links in the intro).

**Standards:** [Python plugin discovery](https://packaging.python.org/en/latest/guides/creating-and-discovering-plugins/) ·
[entry points](https://packaging.python.org/en/latest/specifications/entry-points/) ·
[JSON Schema](https://json-schema.org/specification) ·
[OpenTelemetry Python](https://opentelemetry.io/docs/languages/python/instrumentation/).

**Related issues:** [#9](https://github.com/nerevu/riko/issues/9) plugins ·
[#11](https://github.com/nerevu/riko/issues/11) benchmarks ·
[#16](https://github.com/nerevu/riko/issues/16) pipeline format ·
[#17](https://github.com/nerevu/riko/issues/17) GUI ·
[#19](https://github.com/nerevu/riko/issues/19) protocols.
