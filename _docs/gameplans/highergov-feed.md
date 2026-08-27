# HigherGov feed gameplan

> **Provenance.** Authoritative detail for the HigherGov-first production path and the
> Feed/schema integration it depends on. Core execution semantics are owned by
> [execution-semantics.md](execution-semantics.md), callable-node behavior by
> [callable-pipes.md](callable-pipes.md), and tabular boundaries by
> [tabular-interop.md](tabular-interop.md).

## Mission

Ship Riko's first production use — the HigherGov ingestion pipeline — by implementing a
reusable vertical slice of the eventual architecture rather than the whole protocol stack.
The path combines:

1. HigherGov schema contracts and drift detection;
2. mode-neutral callable `Pipeline` nodes for bounded concurrent I/O;
3. existing pandas transformations where vectorization is still the right tool;
4. Feed-native async sources/results where incremental I/O matters;
5. explicit SQL/Airtable durable boundaries.

HigherGov is an application consumer of the core execution/state/batch contracts. It must not
freeze transitional `SyncPipe` / `AsyncPipe` behavior into the target architecture.

## HigherGov critical path

Issue #176 moves schema work into the HigherGov minimum viable integration. HigherGov should
not begin bulk transformation, scraping, or API processing until the applicable ingestion
boundary has been checked against a version-controlled contract. The issue covers HigherGov
CSV/API/scrape output and Airtable metadata, including distinguishing an empty field from a
removed field.

The target critical path is:

```text
HigherGov acceptance fixtures
→ schema contracts and drift detection
→ callable Pipeline nodes
→ HigherGov bounded-concurrency integration
→ Feed-native streaming where useful
→ shared state/batch/RDP projections as later needs require
```

RDP remains an interchange/protocol projection; it does not need to block this application
vertical slice.

## Core execution shape

HigherGov code should be written against the final mode-neutral Pipeline definition:

```python
flow = (
    Pipeline(source=dataframe.to_dict("records"))
    .map(processor)
    .with_execution(
        executor="thread",
        concurrency=workers,
        ordered=False,
    )
)

result = pd.DataFrame(list(flow))
```

For an expanding callable:

```python
flow = Pipeline(source=items).flat_map(processor)
```

The same definition may run through async iteration when the surrounding application is async:

```python
answers = [answer async for answer in flow]
```

There is no target `flow.collect()` execution terminal and no separate final `SyncPipe.map` /
`AsyncPipe.map` contract. `with_execution(...)` owns execution-wide concurrency/executor/order
settings; step configuration remains fixed when the step is declared.

## Migration principles

### 1. Do not use `itembuilder` as the callable bridge

A Pipeline already has a source and callable nodes. Most HigherGov functions are one-input to
one-output and use `map`; one-to-many operations use `flat_map`.

Do not add artificial `itembuilder`, `.output`, or a requirement that every callable return an
iterator.

### 2. Do not rewrite vectorized pandas transformations initially

Retain the existing vectorized functions:

```python
process_grant_data(...)
process_sled_data(...)
process_fed_data(...)
process_forecast_data(...)
```

Insert schema validation immediately after each CSV load and before renaming/transformation.
Moving dataframe-wide/vectorized work into Python dict processing increases migration surface,
risks behavior drift, and may reduce performance.

Row-oriented processing can be revisited only when measurements justify it.

### 3. Preserve batch-level Selenium lifecycle initially

The current implementation partitions a DataFrame into chunks, creates one driver per chunk
invocation, signs in, processes that chunk, and quits the driver. The first Riko migration maps
**chunk items**, not individual opportunities:

```python
items = [
    {"records": chunk.to_dict("records")}
    for chunk in dataframe_chunks
]


def scrape_chunk(item, **kwargs):
    frame = pd.DataFrame(item["records"])
    result = _scrape_highergov(frame)
    return {"records": result.to_dict("records")}
```

Riko replaces outer executor orchestration while HigherGov initially retains browser creation and
cleanup inside the chunk callable. A later declared `Resource` may own a reusable browser if the
performance/lifecycle tradeoff proves worthwhile.

### 4. Preserve the existing redirect batch operation

Keep the authenticated Selenium batch operation, including driver recreation after failures. Map
the existing batch function; do not replace Selenium with `requests` unless independently tested
and proven equivalent.

### 5. Keep `highergov.utils.riko` small

The first application adapter should contain only thin helpers around ordinary Pipeline use, for
example:

```python
def parallel_map_dataframe(...): ...
def parallel_map_batches(...): ...
def fetch_content_parallel(...): ...
def call_api_parallel(...): ...
```

Do not create a HigherGov-specific runtime, resource manager, DataFrame DSL, or checkpoint layer.

---

## Revised roadmap (HG-0 … HG-9)

### HG-0 — Golden outputs and ingestion contracts

Capture representative fixtures for each HigherGov CSV type, opportunity API results, scrape
output by source type, and Airtable Opportunities/Documents/NIGP metadata.

Record expected fields, required fields, types, nullability, stable external IDs where available,
and representative payloads. Also capture before/after output fixtures for functions being moved
to Pipeline execution.

### HG-1 — Minimal callable Pipeline nodes

Implement only the callable functionality HigherGov needs, using the common decorator/preparation
model described by `callable-pipes.md`.

Conceptually:

```python
@processor(
    emit=True,
    boundedness="preserve",
    ordering="preserve",
)
def pipe(item, fn, objconf, **kwargs):
    return fn(item, **kwargs)
```

`flat_map` declares unknown/potential expansion semantics.

Target usage:

```python
Pipeline(source=items).map(fn)
Pipeline(source=items).flat_map(fn)
```

The public `Context` remains immutable environment/resource configuration. Callables receive
prepared arguments through the existing wrapper mechanism; do not add `CallableContext`, signature
injection, or mutable per-item context state.

For blocking functions under async execution, adaptation occurs through the common execution
bridge. For sync execution, native sync implementation wins. HigherGov code does not choose between
separate public pipe classes.

### HG-2 — Schema contract and drift core

Continue using raw Draft-07 JSON Schema as the authoritative contract. Do not make Pandera the
source of truth.

```python
OPPORTUNITY_CSV_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "Source ID": {"type": ["string", "null"]},
        "Title": {"type": ["string", "null"]},
        "Due Date": {"type": ["string", "null"]},
    },
    "required": ["Source ID", "Title"],
    "additionalProperties": True,
}
```

Minimal Riko API:

```python
observed = inspect_schema(columns=dataframe.columns, dtypes=dataframe.dtypes)
report = diff_schema(expected=OPPORTUNITY_CSV_SCHEMA, observed=observed)
validate_schema(report, on_missing="error", on_extra="warn", on_type_change="error")
```

```python
class SchemaDriftReport(TypedDict):
    source: str
    added: list[str]
    removed: list[str]
    renamed: list[Rename]
    type_changes: list[TypeChange]
    nullable_changes: list[NullableChange]
    computed_field_errors: list[str]
```

Rename behavior: Airtable stable field IDs can identify authoritative renames. CSV/API sources
report removed + added; fuzzy similarity may be advisory only and must never remap automatically.

Added columns normally warn. Removed required columns fail before transformation. Removed optional
columns warn unless a source-specific contract requires them.

### HG-3 — Source-specific schema adapters

**HigherGov CSV** — inspect the header before transformation. Replace repeated per-mapping-key
checks with one structured validation result.

**HigherGov API** — validate one representative live/metadata result before bulk execution, then
validate each returned item for required fields and normalize optional missing keys to `None`.

**HigherGov scrape output** — validate normalized output from each source-specific scraper
(`sled`, `sled_forecast`, `grant`, `sam`, `forecast`). Normalize expected keys before validation so
an empty scrape result differs from a missing field.

**Airtable** — use Metadata API before fetching records. Compare field ID, name, type,
computed-field configuration, and linked-table information. Reindex record DataFrames against
metadata fields so an entirely empty column still exists. Treat `.errorType` as computed-field
health failure where applicable.

### HG-4 — HigherGov integration

1. **Content fetching** — stateless, I/O-bound, easy to compare.
2. **API calls** — input schema -> API preflight -> bounded map -> output validation -> DataFrame.
3. **Redirect batches** — retain current batch callable/browser lifecycle; replace outer executor.
4. **Selenium scrape chunks** — use Riko only for chunk scheduling initially.
5. **Document API calls** — later low-risk map/flat-map target after opportunity API processing.

### HG-5 — Drift sentinel

Add `validate_ingestion_sources()` at the earliest inspectable boundary:

| Source | Earliest validation point |
|---|---|
| Airtable | pipeline start via Metadata API |
| HigherGov API | before bulk API calls |
| HigherGov CSV | immediately after each CSV download |
| Scrape output | first normalized result and subsequent result validation |

The sentinel returns one combined report routed through existing HigherGov alerting.

### HG-6 — Execution hardening driven by production

Production findings feed the common execution owners rather than a HigherGov-specific runtime:

- bounded in-flight work and reorder buffers;
- early-close/cancellation cleanup;
- retry/disposition policy;
- shared concurrency budgets;
- metrics/events;
- process-safe configuration where process execution is actually required.

These semantics belong to `execution-semantics.md` and `implementation-sequence.md`.

### HG-7 — Optional row-stream CSV migration

Only after schema and concurrency integration is stable: evaluate row-stream CSV processing,
benchmark against pandas, migrate only row-local transformations, and retain vectorized/dataframe-
wide operations in pandas.

### HG-8 — Feed-native streaming integration

`Feed = AsyncIterable[Item]` remains the async stream vocabulary. HG-8 uses Feed-native source/parser
support through the common Pipeline execution bridge for HigherGov's async I/O paths.

Relevant common work includes:

- source normalization;
- bounded async concurrency;
- cancellation/timeout composition;
- FeedResult metadata/state propagation;
- Feed-native module migration.

See `feed-native-streaming.md` rather than defining an application-specific async runtime.

### HG-9 — State/batch/RDP projections as needed

After the application vertical slice is stable, adopt common facilities when justified:

- `FeedResult` / `FeedState` / `StateStore` for durable source progress;
- single-Pipeline batch mode and negotiated tabular backends;
- RDP schema/transport/manifests for interchange;
- connector/provider packages for reusable external-system semantics.

Do not reintroduce RDP-owned generic checkpoint/state semantics.

---

## HigherGov-first definition of done

The first production Riko milestone is complete when:

1. `Pipeline.map()` / `flat_map()` cover the selected HigherGov callables.
2. HigherGov has no direct executor orchestration in the migrated functions.
3. CSV, API, scrape, and Airtable boundaries have explicit schema contracts.
4. Removed required fields fail before transformation.
5. Added fields produce structured warnings.
6. Airtable empty fields and removed fields are distinguishable through metadata.
7. Selenium drivers are always closed.
8. Existing worker/deployment limits remain unchanged unless deliberately tuned.
9. Golden output fixtures match the pre-Riko implementation.
10. Schema drift and processing failures are reported separately.
11. The same Pipeline definitions are not forked into separate SyncPipe/AsyncPipe application APIs.

---

## Async/Feed integration

HigherGov uses Feed-native sources/results as the **asynchronous I/O layer between DataFrame-oriented
boundaries**, not as a replacement for pandas or for the entire application pipeline.

```text
SQL / CSV / Airtable
        ↓
schema validation
        ↓
DataFrame or paginated source
        ↓
Pipeline / Feed-native source
        ↓
bounded concurrent I/O processing
        ↓
Pipeline / FeedResult
        ↓
DataFrame / batch sink
        ↓
existing pandas transforms, SQL, or Airtable
```

### 1. OpenAI processing

An async source can yield items lazily:

```python
async def entry_feed(entries: pd.DataFrame):
    for row in entries.itertuples(index=False):
        yield {
            column: value
            for column, value in zip(entries.columns, row, strict=True)
        }
```

and the same Pipeline abstraction handles the async callable:

```python
flow = (
    Pipeline(source=entry_feed(entries_df))
    .map(analyze_entry)
    .with_execution(concurrency=MAX_CONCURRENT, ordered=False)
)

answers = [answer async for answer in flow]
```

Recursive document summarization remains sequential **within one document** when later chunks depend
on earlier summaries; concurrency is across independent documents.

HTTP/provider retries should not be multiplied by an independent application retry loop. Use the
common `RetryPolicy` and provider hints at the correct failure boundary.

### 2. Webpage-content fetching

Blocking functions can run through the common async adaptation path:

```python
flow = (
    Pipeline(source=finder_opportunity_feed(dataframe))
    .map(fetch_finder_content)
    .with_execution(
        executor="thread",
        concurrency=3,
        ordered=False,
    )
)
```

This provides bounded submission and cancellation without a separate `AsyncPipe` API.

### 3. HigherGov API calls

The per-row body remains an ordinary callable:

```python
def call_highergov_api(item: dict, **kwargs) -> dict:
    result = _api_call_single_item(item)
    return result if result is not None else item


flow = (
    Pipeline(source=dataframe_feed(cleaned_higher_df))
    .map(call_highergov_api)
    .with_execution(
        executor="thread",
        concurrency=4,
        ordered=False,
    )
)
```

If the callable later becomes native async, the Pipeline definition shape remains the same and the
matching native implementation wins.

Input schema validation occurs before yielding source records; output records are validated before
downstream transformation.

### 4. HigherGov document fetching

```text
opportunity
    ↓ flat_map
fetch document metadata -> document
    ↓
extract text -> chunk document -> summarize -> clean/hash
    ↓
bounded batch database write
```

```python
flow = (
    Pipeline(source=opportunity_feed(logic_mapped))
    .flat_map(fetch_documents)
    .map(normalize_document)
    .map(extract_document_text)
    .map(summarize_if_needed)
    .map(hash_document)
    .with_execution(concurrency=MAX_CONCURRENT, ordered=False)
)
```

One opportunity may expand to multiple documents, hence `flat_map`. Do not flatten summary chunks
into independent records when chunk order/state is internal to one document summarization.

### 5. Airtable pagination and updates

A Feed-native source may validate authoritative metadata before emitting records page-by-page.
Writes remain bounded batches. When common Pipeline batch mode is used, batches are ordinary values
and backend negotiation follows `execution-semantics.md` / `tabular-interop.md`.

Do not define an Airtable-specific batch pipeline hierarchy.

### 6. Selenium scraping

Represent each scrape chunk as one source item and execute the blocking callable with bounded thread
execution. Browser ownership can remain inside the callable initially; if later promoted to a Riko
resource, declare it through `Resource`/`resources=` and let the execution own cleanup.

### 7. URL redirect resolution

Use a source of batches and map the existing redirect batch callable. A final ordinary reducer can
combine result dictionaries/failure lists. Do not reduce the operation to one browser invocation per
URL merely to make it look row-oriented.

---

## Feed and schema drift

Feed-native sources should establish schema validity before normal downstream processing when the
source exposes enough metadata to do so.

**CSV source** — validate header before first row.

**Airtable source** — Metadata API -> validate field IDs/types -> normalize empty fields -> emit.

**API source** — validate input boundary -> call API -> validate returned payload -> emit.

**Scrape source** — validate normalized output shape/field health after each scrape result.

A missing expected output key is schema drift. A present key whose value is `None` is an empty result.

---

## Where Pipeline/Feed should not replace pandas

Keep pandas for whole-dataset operations such as:

- `combine_first` / DataFrame joins;
- global duplicate detection;
- masks depending on the entire dataset;
- vectorized date/string transformations;
- source-specific CSV transformations;
- schema reports requiring the complete column set.

A valid boundary is:

```text
Pipeline/Feed
→ explicit finite DataFrame materialization
→ pandas transformation
→ optional Pipeline.from_frame(...)
```

The concrete tabular conversion contract belongs to `tabular-interop.md`.

Keep SQL/Airtable/object storage as durable application/run boundaries rather than trying to carry
one live stream through every HigherGov script before checkpoint/orchestration requirements justify
it.

---

## Minimal core functionality HigherGov actually needs

```text
Pipeline[T]
    immutable definition
    sync or async iteration
    map / flat_map
    with_execution(...)

Feed = AsyncIterable[Item]
    Feed-native sources/parsers

Execution
    bounded concurrency
    native sync/async selection
    thread adaptation for blocking callables
    cancellation / early close

Context / Resource
    immutable definitions
    execution-owned live handles

Schema
    boundary inspection/diff/validation
```

HigherGov does **not** initially require distributed leases, a second checkpoint protocol, an agent
runtime, or the entire RDP/Connect feature set.

The practical architecture is:

```text
pandas for dataset logic
Pipeline/Feed for bounded concurrent I/O
schema contracts at source boundaries
SQL/Airtable for durable boundaries
```

---

# Schema-drift implementation

> Salvaged from the retired `productionizing.md`; this is application-enabling schema work, not a
> parallel execution phase.

## `riko/types/schema.py`

Add report types:

```python
class SchemaField(TypedDict, total=False):
    type: str | list[str]
    nullable: bool
    required: bool
    external_id: str


class FieldTypeChange(TypedDict):
    field: str
    expected: object
    observed: object


class SchemaDriftReport(TypedDict):
    source: str
    added: list[str]
    removed: list[str]
    rename_candidates: list[dict[str, str]]
    type_changes: list[FieldTypeChange]
    nullable_changes: list[str]
    computed_field_errors: list[str]
```

## `riko/schema.py`

Start with one simple module:

```python
def inspect_records_schema(...) -> dict: ...
def diff_schema(...) -> SchemaDriftReport: ...
def validate_schema(...) -> SchemaDriftReport: ...
```

Expected schema is a Draft-07 mapping or boolean schema.

Behavior:

- missing required field -> error;
- added field -> warning by default;
- removed optional field -> warning by default;
- incompatible type change -> error;
- rename similarity -> advisory candidate only;
- stable external field IDs -> authoritative rename detection.

Do not require pandas in this module. HigherGov can provide DataFrame dtype/column information
through an adapter.

## HigherGov repository adapters

In HigherGov, add:

```text
data_enrichment_pipeline/schema/contracts.py
data_enrichment_pipeline/schema/airtable.py
data_enrichment_pipeline/schema/dataframe.py
data_enrichment_pipeline/schema/preflight.py
```

These files:

- convert DataFrame dtypes to generic schema observations;
- inspect CSV headers;
- query Airtable Metadata;
- report `.errorType` computed-field failures;
- call generic Riko schema functions.

This satisfies issue #176 without making pandas or Airtable part of Riko core.
