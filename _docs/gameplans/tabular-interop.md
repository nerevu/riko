# Tabular interoperability gameplan

## 1. Mission

Define the single authoritative contract for moving finite tabular data between Riko's
ordinary item mode, Pipeline batch mode, Pandas, Arrow, and optionally Polars.

This plan owns **in-memory tabular boundaries**. It does not own REST acquisition, file
formats, report rendering, schema contracts, or DataFrame-oriented application logic.

Related plans:

* `execution-semantics.md` — one `Pipeline[T]`, batch mode/backend negotiation,
  boundedness/materialization semantics;
* `rest-incremental.md` — REST collection and incremental cursor semantics;
* `connectors.md` — transport/session lifecycle and tabular file acquisition;
* `artifact-conversion.md` — serialized codecs and rendered artifacts;
* `highergov-feed.md` — application-specific DataFrame integration.

## 2. Architectural rule

There is one Pipeline abstraction:

```text
Pandas / Arrow / Polars / SQL-native batches
        ↕ explicit/negotiated boundary
            Pipeline[T]
        item mode or batch mode
```

Frame support must not create a parallel `BatchPipe` hierarchy or require every processor
to become a DataFrame operator. In batch mode the current batch is simply the logical value
seen by batch-capable transforms.

Conversion remains explicit/inspectable where a user requests a concrete frame type and is
subject to boundedness rules.

## 3. Ownership boundaries

This plan owns:

* frame input conveniences such as `from_frame` / `from_pandas` / `from_arrow`;
* materialization conveniences such as `to_pandas` / `to_arrow`;
* optional Polars conveniences;
* null/index/dtype conversion rules;
* frame/Arrow representation boundaries;
* terminal materialization safeguards.

`execution-semantics.md` owns:

* `Pipeline(batch=True, batch_size=...)`;
* the rule that `batch_size` is invalid unless `batch=True`;
* backend negotiation order;
* forced `batch_backend=` behavior;
* the fact that batches are ordinary Pipeline values.

This plan does **not** own:

* CSV/XLSX/Parquet codec implementation — `artifact-conversion.md` / connectors;
* REST pagination or API cursors — `rest-incremental.md`;
* source state/checkpoint persistence — `execution-semantics.md`;
* schema validation/drift contracts — HigherGov/schema plans.

## 4. Common frame input

Prefer one mode-neutral Pipeline entry point where possible:

```python
flow = Pipeline.from_frame(df)
```

Backend-specific conveniences may remain aliases when they improve discoverability:

```python
flow = Pipeline.from_pandas(df)
flow = Pipeline.from_arrow(table)
flow = Pipeline.from_polars(frame)
```

They create ordinary immutable Pipeline definitions. There are no sync-only frame
constructors in the target API.

The caller may choose item or batch mode:

```python
rows = Pipeline.from_frame(df, batch=False)

batches = Pipeline.from_frame(
    df,
    batch=True,
    batch_size=10_000,
)
```

## 5. Pandas input

Baseline item-mode semantics are equivalent to row mappings while avoiding unnecessary
whole-frame copies where practical.

Index handling is explicit:

```python
Pipeline.from_pandas(
    df,
    index="ignore",  # ignore | field | metadata
    index_field="index",
)
```

Requirements:

* preserve column names and row order;
* define duplicate-column behavior explicitly;
* normalize Pandas missing values predictably in item mode;
* document dtype information lost when converting to ordinary Python values;
* support bounded batch/chunk production for large finite frames;
* never require Pandas for users who do not invoke Pandas boundaries.

## 6. Pandas output

A concrete Pandas result is an explicit finite materialization:

```python
df = flow.to_pandas()
```

Possible options:

```python
flow.to_pandas(
    columns=None,
    index=None,
    dtype_backend=None,
)
```

Requirements:

* reject known-unbounded feeds unless an explicit finite bound/truncation exists;
* require clear opt-in/diagnostic behavior when boundedness is unknown;
* preserve deterministic column ordering;
* normalize missing values consistently;
* prefer nullable dtypes where doing so does not create surprising coercion;
* report materialized row/byte estimates when available.

Large-data workflows should prefer Pipeline batch mode or incremental Arrow batches rather
than one giant DataFrame.

`to_pandas()` is a representation/materialization boundary, not one of the removed generic
execution terminals such as `collect()` / `first()`.

## 7. Arrow input

Arrow is the preferred typed interchange boundary when consumers can use it directly.

```python
flow = Pipeline.from_arrow(table)
```

Accepted inputs may include:

```text
pyarrow.Table
pyarrow.RecordBatch
iterable/reader of RecordBatch
```

Requirements:

* preserve Arrow field names and null semantics;
* retain schema metadata in `FeedResult.metadata` or the appropriate batch metadata when
  truthful;
* avoid Pandas as an intermediate representation;
* permit batch-wise iteration so a large table need not become one Python list first.

## 8. Arrow output

Concrete conversion APIs may include:

```python
table = flow.to_arrow()

batches = flow.to_arrow_batches(batch_size=10_000)
```

`to_arrow()` materializes a finite table. `to_arrow_batches()` is an incremental bridge
when a consumer explicitly wants Arrow batches.

Requirements:

* known-unbounded feeds cannot call `to_arrow()` accidentally;
* batch size is explicit and bounded;
* schema evolution within one conversion has an explicit policy;
* Arrow conversion does not change ordinary upstream item semantics.

When the Pipeline is already in batch mode and Arrow is the negotiated representation, the
runtime should avoid redundant conversion/copying when it can safely reuse the native batch.

## 9. Polars interoperability

Polars remains optional. Convenience APIs may be:

```python
flow = Pipeline.from_polars(frame)
frame = flow.to_polars()
```

Prefer Arrow/interchange-backed conversion where that is the safe efficient path rather
than inventing an independent Polars record model.

## 10. Batch backend negotiation

Batch representation is graph/capability-aware. The core preference order is:

```text
native safe/zero-copy
→ Arrow
→ Polars
→ Pandas
→ Python list
```

This is a preference order, not a requirement to install every backend.

An explicit:

```python
batch_backend="arrow"
```

forces the requested supported backend. If unavailable/incompatible, raise rather than
silently choosing another forced representation.

Backend choice is an execution representation decision. The logical Pipeline remains one
`Pipeline[T]` definition.

## 11. Batches are ordinary values

In item mode:

```python
flow.map(func)
# func receives one item
```

In batch mode:

```python
flow.map(func)
# func receives the current batch
```

There is no separate `BatchPipe.map()` contract. Operators that are not batch-capable must
have an explicit conversion/planning boundary rather than silently materializing an entire
unbounded stream.

## 12. Missing values and scalar normalization

Frame libraries represent missing/scalar values differently. Define one conversion policy
rather than letting each connector invent its own.

At ordinary item boundaries:

* missing tabular values normalize to the Riko null representation (`None`) unless a typed
  scalar is explicitly preserved;
* NaN versus null distinctions that cannot survive mapping conversion are documented;
* timestamps, decimals, binary values, categorical values, and extension dtypes have
  deterministic conversion rules;
* timezone-aware timestamps must not silently lose timezone information.

Native batch representations may retain richer type/null semantics than item mappings.

## 13. Index semantics

A DataFrame index is not implicitly a Riko field.

Supported policies:

```text
ignore
field      # write index into configured field
metadata   # preserve as namespaced metadata when truthful/practical
```

MultiIndex conversion requires explicit field names or a documented generated-name policy.

## 14. Schema metadata

Tabular boundaries may expose observed schema information through the common metadata model:

```text
columns/fields
logical/physical types
nullability
Arrow schema metadata
row count when known
```

Observation is not validation. Strict schema contracts and drift behavior remain owned by
the schema/HigherGov gameplans.

Metadata propagates only while truthful. A representation/operator that invalidates schema
metadata must invalidate or replace it rather than silently retaining stale values.

## 15. Chunking and boundedness

Batching/chunking is streaming and bounded; it must not materialize an unbounded source.

```python
Pipeline.from_pandas(df, batch=True, batch_size=10_000)
```

Rules:

* `batch_size` requires `batch=True`;
* logical row order is preserved unless downstream execution/operator semantics explicitly
  choose otherwise;
* batch boundaries are execution representation details unless an operator explicitly
  treats the current batch as its logical value;
* whole-frame materialization requires a known/effectively bounded input.

## 16. File/artifact relationship

Do not conflate an in-memory frame with a serialized artifact:

```text
DataFrame / Arrow Table / RecordBatch
    in-memory tabular value/representation

CSV / XLSX / Parquet file
    serialized artifact
```

Reading/writing CSV/XLSX/Parquet belongs to codec/connector plans. Those implementations may
use a negotiated batch representation internally, but their public artifact contract is not
defined here.

## 17. REST relationship

REST sources emit records by default and may opt into ordinary Pipeline batch mode:

```python
flow = Pipeline("rest", conf=conf, batch=True, batch_size=1000)
```

REST pagination, auth, dependent endpoints, and cursors remain entirely in
`rest-incremental.md`. There is no REST-specific DataFrame execution model.

## 18. HigherGov relationship

HigherGov may retain vectorized Pandas transformations and use Riko item/batch-oriented
concurrency where useful. `highergov-feed.md` may contain concrete frame examples, but
shared frame conversion/batch-representation behavior is defined here and in
`execution-semantics.md`.

## 19. Dependency policy

Pandas, PyArrow, and Polars are optional dependencies.

Suggested extras may be independent:

```text
pandas
arrow
polars
frames
```

Batch acceleration/representation dependencies should compose with the existing `perf`
policy where appropriate. Import/capability errors identify the missing optional dependency
and requested boundary/backend. Core Riko remains importable without frame libraries.

## 20. Observability

Boundary/batch events may report:

* source/target frame type;
* negotiated/forced batch backend;
* row count when known;
* batch count/size;
* materialization size estimate;
* schema fingerprint/summary;
* conversion duration;
* coercion warnings.

Do not emit whole rows or sensitive frame contents in diagnostics by default.

## 21. Testing strategy

Required deterministic tests:

1. one `Pipeline.from_frame` definition works in sync and async execution;
2. Pandas item input preserves columns and row order;
3. index `ignore`/`field` behavior is explicit;
4. representative nullable Pandas values normalize predictably;
5. Pandas round-trip documents expected dtype changes;
6. known-unbounded feeds reject whole-frame materialization;
7. Arrow Table and RecordBatch inputs produce equivalent logical records/batches;
8. batch mode respects configured `batch_size`;
9. batch backend negotiation follows native -> Arrow -> Polars -> Pandas -> list;
10. forced unavailable backend raises;
11. `.map()` receives an item in item mode and current batch in batch mode;
12. Arrow metadata/type behavior is deterministic;
13. timezone/decimal/binary fixtures round-trip according to documented rules;
14. optional dependency errors are clear;
15. Polars convenience paths retain the same logical semantics where enabled.

## 22. Phases

```text
T0  scalar/null/index conversion contract
T1  common Pipeline.from_frame + Pandas conveniences
T2  Arrow Table/RecordBatch input
T3  Pipeline batch-mode backend negotiation
T4  Arrow/frame materialization boundaries
T5  observability + schema metadata
T6  optional Polars conveniences
```

## 23. Definition of done

1. Pandas/Arrow/Polars semantics are specified in one gameplan only.
2. Frame libraries remain optional dependencies.
3. There is one `Pipeline[T]`; no `BatchPipe` hierarchy exists.
4. Item and batch modes have explicit, predictable callable semantics.
5. Terminal frame materialization cannot silently consume known-unbounded feeds.
6. Large finite inputs can cross boundaries as bounded batches.
7. Batch backend negotiation and forced-backend behavior match execution semantics.
8. Null, index, metadata, and typed-scalar behavior is deterministic/documented.
9. REST, connector, artifact, SQL, and application plans reference this contract rather than
   redefining it.
