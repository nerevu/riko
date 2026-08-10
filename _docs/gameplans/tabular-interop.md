# Riko Tabular Interoperability Gameplan

## 1. Mission

Define the single authoritative contract for moving finite tabular data between Riko's
record-stream model and Pandas, Arrow, and optionally Polars.

This plan owns **in-memory tabular boundaries**. It does not own REST acquisition, file
formats, report rendering, schema contracts, or DataFrame-oriented application logic.

Related plans:

* `rest-incremental.md` — REST collection and incremental cursor semantics;
* `connectors.md` — transport/session lifecycle and tabular file acquisition;
* `artifact-conversion.md` — serialized codecs and rendered artifacts;
* `highergov-feed.md` — application-specific DataFrame integration;
* `execution-semantics.md` — boundedness and materialization semantics.

## 2. Architectural rule

Riko remains record-stream oriented:

```text
Pandas / Arrow / Polars
        ↕ explicit boundary
      Item stream
```

Frame support must not turn every processor into a DataFrame or Arrow operator.
Conversion is explicit, inspectable, and subject to boundedness rules.

## 3. Ownership boundaries

This plan owns:

* `from_pandas` / `to_pandas`;
* `from_arrow` / `to_arrow` / Arrow batches;
* optional Polars convenience boundaries;
* null/index/dtype conversion rules;
* chunking/batching at frame boundaries;
* terminal materialization safeguards.

This plan does **not** own:

* CSV/XLSX/Parquet codec implementation — `artifact-conversion.md` / connectors;
* REST pagination or API cursors — `rest-incremental.md`;
* source checkpoint persistence — `feed-monitoring.md`;
* schema validation/drift contracts — HigherGov/schema plans;
* general batch execution semantics — runtime/RDP plans.

## 4. Pandas input

Target API:

```python
flow = SyncPipe.from_pandas(df)
```

Baseline semantics are equivalent to producing row mappings, but implementations should
avoid unnecessary whole-frame copies where practical.

Configuration should make index handling explicit:

```python
SyncPipe.from_pandas(
    df,
    index="ignore",  # ignore | field | metadata
    index_field="index",
)
```

Requirements:

* preserve column names and row order;
* define duplicate-column behavior explicitly;
* normalize Pandas missing values predictably;
* document dtype information lost when converting to ordinary Python values;
* support chunked row production for large finite frames;
* never require Pandas for users who do not invoke Pandas boundaries.

## 5. Pandas output

Target API:

```python
df = flow.to_pandas()
```

`to_pandas()` is a **terminal materialization operation**.

Possible options:

```python
flow.to_pandas(
    columns=None,
    index=None,
    dtype_backend=None,
)
```

Requirements:

* reject known-unbounded feeds unless an explicit bound/truncation exists;
* warn or require opt-in when boundedness is unknown;
* preserve deterministic column ordering;
* normalize missing values consistently;
* prefer nullable dtypes where doing so does not create surprising coercion;
* report materialized row/byte estimates when available.

Large-data workflows should prefer chunk/batch conversion rather than one giant DataFrame.

## 6. Arrow input

Arrow is the preferred typed interchange boundary when consumers can use it directly.

Target API:

```python
flow = SyncPipe.from_arrow(table)
```

Accepted inputs may include:

```text
pyarrow.Table
pyarrow.RecordBatch
iterable/reader of RecordBatch
```

Requirements:

* preserve Arrow field names and null semantics;
* retain schema metadata when exposed through execution metadata;
* avoid Pandas as an intermediate representation;
* permit batch-wise iteration so a large table need not become one Python list first.

## 7. Arrow output

Target APIs:

```python
table = flow.to_arrow()

batches = flow.to_arrow_batches(
    batch_size=10_000,
)
```

`to_arrow()` materializes a finite table. `to_arrow_batches()` is the preferred bounded
bridge when downstream consumers can process batches incrementally.

Requirements:

* known-unbounded feeds cannot call `to_arrow()` accidentally;
* batch size is explicit and bounded;
* schema evolution within one conversion has an explicit policy (`error`, `promote`, or
  another documented strategy);
* Arrow conversion does not change ordinary Riko item semantics upstream.

## 8. Polars interoperability

Polars support is a convenience layer after Arrow behavior is stable.

Possible API:

```python
flow = SyncPipe.from_polars(frame)
frame = flow.to_polars()
```

Prefer Arrow-backed conversion where possible rather than implementing an independent
Polars record model.

Polars remains optional and lower priority than Arrow/Pandas unless concrete workloads make
it a stronger requirement.

## 9. Missing values and scalar normalization

Frame libraries represent missing/scalar values differently. Define one conversion policy
rather than letting each connector invent its own.

At record-stream boundaries:

* missing tabular values normalize to the ordinary Riko null representation (`None`) unless
  preserving a typed scalar is explicitly supported;
* NaN versus null distinctions that cannot survive mapping conversion are documented;
* timestamps, decimals, binary values, categorical values, and extension dtypes have
  deterministic conversion rules;
* timezone-aware timestamps must not silently lose timezone information.

Arrow boundaries may retain richer types than dict/Pandas boundaries.

## 10. Index semantics

A DataFrame index is not implicitly a Riko field.

Supported policies:

```text
ignore
field      # write index into a configured field
metadata   # preserve as namespaced boundary metadata when practical
```

MultiIndex conversion requires explicit field names or a documented generated-name policy.

## 11. Schema metadata

Tabular boundaries may expose observed schema information:

```text
columns/fields
logical/physical types
nullability
Arrow schema metadata
row count when known
```

Observation is not validation. Strict schema contracts and drift behavior remain owned by
the schema/HigherGov gameplans.

## 12. Chunking and batches

Chunking is a boundary optimization, not a new execution model.

Examples:

```python
SyncPipe.from_pandas(df, chunk_size=10_000)
flow.to_arrow_batches(batch_size=10_000)
```

Rules:

* batch/chunk size is explicit;
* conversion preserves logical row order unless downstream execution selects otherwise;
* chunk boundaries are not semantically meaningful to ordinary record processors;
* a downstream stage that requires whole-frame semantics must declare/materialize that
  boundary itself.

## 13. File/artifact relationship

Do not conflate an in-memory frame with a serialized artifact:

```text
DataFrame / Arrow Table
    in-memory tabular value

CSV / XLSX / Parquet file
    serialized artifact
```

Reading/writing CSV/XLSX/Parquet belongs to codec/connector plans. Those implementations may
use Arrow or another frame internally, but their public artifact contract is not defined
here.

## 14. REST relationship

REST sources emit records. A caller may explicitly materialize those records into a frame:

```text
REST source
→ records
→ transformations
→ to_pandas() / to_arrow()
```

REST pagination, auth, dependent endpoints, and cursors remain entirely in
`rest-incremental.md`. There is no REST-specific DataFrame API.

## 15. HigherGov relationship

HigherGov can retain vectorized Pandas transformations and use Riko for row/batch-oriented
concurrency where useful. `highergov-feed.md` may contain concrete DataFrame examples, but
shared frame conversion behavior is defined only here.

## 16. Dependency policy

Pandas, PyArrow, and Polars are optional dependencies.

Suggested extras may be independent:

```text
pandas
arrow
polars
frames  # convenience aggregate extra, if useful
```

Import errors should identify the missing optional dependency and the requested boundary.
Core Riko must remain importable without any frame library installed.

## 17. Observability

Boundary events may report:

* source/target frame type;
* row count when known;
* chunk/batch count;
* materialization size estimate;
* schema fingerprint/summary;
* conversion duration;
* coercion warnings.

Do not emit whole rows or sensitive frame contents in diagnostics by default.

## 18. Testing strategy

Required deterministic tests:

1. Pandas input preserves columns and row order;
2. index `ignore`/`field` behavior is explicit;
3. representative nullable Pandas values normalize predictably;
4. Pandas round-trip documents expected dtype changes;
5. known-unbounded feeds reject `to_pandas()`;
6. Arrow Table and RecordBatch inputs produce equivalent records;
7. Arrow batch output respects configured batch size;
8. Arrow metadata/type behavior is deterministic;
9. `to_arrow()` rejects unbounded input;
10. timezone/decimal/binary fixtures round-trip according to documented rules;
11. optional dependency errors are clear;
12. Polars convenience paths use the same logical semantics where enabled.

## 19. Phases

```text
T0  scalar/null/index conversion contract
T1  Pandas input/output boundaries
T2  Arrow table and RecordBatch input
T3  Arrow table/batch output
T4  observability + schema metadata
T5  optional Polars conveniences
```

## 20. Definition of done

1. Pandas/Arrow/Polars semantics are specified in one gameplan only.
2. Frame libraries remain optional dependencies.
3. Riko's internal processor model remains record-stream oriented.
4. Terminal frame materialization cannot silently consume known-unbounded feeds.
5. Large finite inputs can cross boundaries in chunks/batches.
6. Null, index, and typed scalar behavior is deterministic and documented.
7. REST, connector, artifact, and application plans reference this contract rather than
   redefining it.
