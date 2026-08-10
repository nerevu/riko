# Riko HigherGov Delivery & Async Feed Gameplan

> **Provenance.** Extracted from `docs/ROADMAP.md` Parts III–IV so the roadmap can stay a
> high-level overview. This is the authoritative detail for the HigherGov-first critical path
> and the async `Feed` integration it depends on. Section references like §N point back to
> [ROADMAP.md](../ROADMAP.md) Part I/II (the runtime contract).

## Mission

Ship riko's first production use — the HigherGov ingestion pipeline — by implementing a
reusable **vertical slice** of the eventual RDP architecture rather than the whole protocol.
Two coupled workstreams: (A) a HigherGov-first critical path that front-loads schema
contracts and synchronous callable stages, and (B) an async `Feed` I/O layer that HigherGov
needs near-term for bounded concurrent I/O between DataFrame-oriented stages.

## HigherGov critical path

Issue #176 moves schema work from a later RDP milestone into the **HigherGov minimum
viable integration**. HigherGov should not begin bulk transformation, scraping, or API
processing until the applicable ingestion boundary has been checked against a
version-controlled contract. The issue covers HigherGov CSV/API/scrape output and
Airtable metadata, and requires distinguishing an empty field from a removed field.

The roadmap therefore shifts from **protocol-first** to a **HigherGov vertical slice**
that deliberately implements reusable pieces of the eventual RDP architecture.

## Critical-path change

Previous critical path:

```text
RDP specification
→ async Feed runtime
→ execution traits
→ batches/schema/state
→ Connect
→ application integration
```

Revised critical path:

```text
HigherGov acceptance fixtures
→ synchronous callable stages
→ schema contracts and drift detection
→ HigherGov concurrency integration
→ Riko sync-runtime hardening
→ async Feed
→ RDP and Connect
```

RDP remains the eventual architecture, but it no longer blocks Riko's first production use.
**Schema validation and synchronous callable execution become coequal P0 workstreams.**

## Changes to the draft integration plan

The draft correctly identifies HigherGov's manual concurrency and repeated ingestion
transformations, but it attempts too much in the first migration (callable-stage
development, executor replacement, Selenium lifecycle redesign, CSV streaming, and a broad
rewrite of pandas transformations). The changes:

### 1. Do not use `itembuilder` as the bridge

`SyncPipe` dynamically resolves named Riko modules through `__getattr__`; it does not
provide a callable `.pipe(processor)` or `.output` interface. It already holds a direct
`source`, so callable stages build on that. The target API:

```python
flow = SyncPipe(
    source=dataframe.to_dict("records"),
    parallel=True,
    workers=workers,
    threads=not use_processes,
).map(processor)

result = pd.DataFrame(flow)
```

For an expanding callable:

```python
flow = SyncPipe(source=items).flat_map(processor)
```

This eliminates the artificial `itembuilder` source, `.pipe(processor)`, `.output`, and
the requirement that every callable yield an iterator. Most HigherGov functions are
one-input-to-one-output operations and should use `map`, not `flat_map`.

### 2. Do not rewrite the CSV transformations initially

Retain the existing vectorized pandas functions:

```python
process_grant_data(...)
process_sled_data(...)
process_fed_data(...)
process_forecast_data(...)
```

but insert schema validation immediately after each CSV load and before renaming or
transformation. Moving vectorized pandas work into Python dict processing would increase
migration surface, risk behavior drift, likely reduce performance, and make schema
validation harder to isolate. Row-oriented CSV processing can be revisited later.

### 3. Preserve batch-level Selenium lifecycle initially

The current implementation partitions the DataFrame into chunks, creates one driver inside
each chunk invocation, signs in, processes the chunk, and quits the driver. The first Riko
migration maps **chunk items**, not individual opportunities:

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

Riko replaces executor orchestration; HigherGov retains ownership of browser creation and
cleanup. A per-worker reusable browser can be considered later.

### 4. Preserve the existing redirect batch operation

The current redirect path uses authenticated Selenium batches, including driver recreation
after failures. Map the existing batch function; do not replace Selenium with `requests`
unless independently tested and proven equivalent:

```python
SyncPipe(
    source=redirect_batches,
    parallel=True,
    workers=max_workers,
).map(process_redirect_batch)
```

### 5. Keep `highergov.utils.riko` small

The first version should contain approximately:

```python
def parallel_map_dataframe(...): ...
def parallel_map_batches(...): ...
def fetch_content_parallel(...): ...
def call_api_parallel(...): ...
```

It should not initially contain CSV parsing, column pipe factories, Selenium resource
factories, thread-local resource management, process-worker support, or dataframe
transformation DSLs.

## Revised roadmap (HG-0 … HG-9)

### Milestone HG-0 — Golden outputs and ingestion contracts

Before changing execution, capture representative fixtures for each HigherGov CSV type,
HigherGov opportunity API results, HigherGov scrape output by source type, and Airtable
Opportunities / Documents / NIGP metadata.

For each source, record expected fields, required fields, types, nullability, stable
external IDs when available, and representative payloads. Also capture before/after output
fixtures for the functions being parallelized. This separates execution regression from
upstream schema drift.

### Milestone HG-1 — Minimal synchronous callable stages

Implement only the synchronous callable functionality HigherGov needs.

New Riko modules `riko/modules/map.py` and `riko/modules/flatmap.py` use the existing
`processor` decorator and extend the existing `Opts`; defaults belong in each module:

```python
@processor(
    emit=True,
    boundedness="preserve",
    ordering="preserve",
    side_effects="none",
    determinism="deterministic",
)
def pipe(item, fn, objconf, **kwargs):
    return fn(item, **kwargs)
```

`flatmap.py` declares `boundedness="unknown"` and accepts multiple returned items.

Public methods:

```python
SyncPipe.map(fn, **kwargs)
SyncPipe.flat_map(fn, **kwargs)
```

Context is passed through the existing kwargs mechanism: `fn(item, context=self.context,
**kwargs)`. There is no signature inspection, `with_context`, `CallableContext`, traits
object, or `call_kwargs` primitive.

The existing sync parallel implementation materializes the source before pool mapping. That
is acceptable for the first HigherGov release because the targeted DataFrames and chunk
collections are already materialized; bounded streaming submission is an immediate
follow-up, not a prerequisite. `map()` defaults to ordered results; HigherGov functions
that reconstruct results by stable IDs may explicitly select unordered execution.

### Milestone HG-2 — Schema contract and drift core

This milestone is now part of the MVP.

Continue using raw Draft-07 JSON Schema as the authoritative contract. Do not make Pandera
the source of truth.

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

Minimal Riko API — functions and `TypedDict` reports, not a large schema object model:

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

Rename behavior: do not infer renames as authoritative from similar names. Airtable
identifies renames through stable field IDs; CSV/API report removed plus added; optional
fuzzy matches may appear under `rename_candidates`; never automatically remap based on
similarity.

Added columns normally warn, not fail. Removed required columns fail before transformation.
Removed optional columns default to warning unless downstream code requires that field
(policy may be `error`/`warn`/`allow` per source).

### Milestone HG-3 — Source-specific schema adapters

**HigherGov CSV** — inspect the CSV header before `pd.read_csv()` transformation work.
Replace the repeated per-mapping-key existence checks with one structured error:

```python
report = validate_csv_header(filepath, schema=GRANT_SCHEMA)
```

**HigherGov API** — before bulk execution, validate one representative live/metadata
result against the expected API contract, validate each returned item for required fields,
and normalize optional missing keys to `None`. Absence of an optional field must not
automatically mean it was removed.

**HigherGov scrape output** — validate the normalized output from each source-specific
scraper (`sled`, `sled_forecast`, `grant`, `sam`, `forecast`). Normalize all expected
output keys before validation:

```python
result = {**EXPECTED_EMPTY_FIELDS[source_type], **scraped_result}
```

This distinguishes a selector returning no value, a scraper forgetting a field, and a null
field. Selector failure is primarily data-health drift and is reported under field-health
failures in the same structured report.

**Airtable** — use the Metadata API before fetching records. Compare field ID, name, type,
computed-field configuration, and linked-table information. Reindex record DataFrames
against metadata fields so an entirely empty column still appears. Treat fields exposing
`.errorType` as computed-field health failures, as required by issue #176.

### Milestone HG-4 — HigherGov integration

1. **Content fetching** first — stateless, I/O-bound, easy to compare, independent of
   Selenium authentication.
2. **API calls** — extract `_api_call_single_item(item) -> Item`; run schema validation:
   input DataFrame schema → API preflight schema → parallel map → output record validation
   → DataFrame.
3. **Redirect batches** — keep the current batch callable and browser lifecycle, replace
   the outer `ThreadPoolExecutor`.
4. **Selenium scrape chunks** — keep `_scrape_highergov(chunk)`, use Riko only for chunk
   scheduling; no browser-per-thread persistence yet.
5. **Document API calls** — `fetch_document_data()` becomes a later low-risk `map` target
   after opportunity API processing is stable.

### Milestone HG-5 — Drift sentinel

Add a preflight command `validate_ingestion_sources()` that runs at the earliest point each
source can be inspected:

| Source        | Earliest validation point                                            |
| ------------- | ------------------------------------------------------------------- |
| Airtable      | pipeline start, via Metadata API                                    |
| HigherGov API | before bulk API calls                                               |
| HigherGov CSV | immediately after each CSV download                                 |
| Scrape output | after first normalized scrape result and on every result validation |

The contract: validate at the earliest available boundary, before transformation or
persistence. The sentinel returns one combined report routed through existing HigherGov
alerting.

### Milestone HG-6 — Sync executor hardening

After the first production integration: remove full-source materialization for pool
submission; bound in-flight tasks; add bounded ordered-result buffering; improve pool
cleanup on early consumer exit; add retry policy; add aggregate metrics; implement
fail/skip/dead-letter policies; add cancellation semantics; support explicit process-safe
context serialization. This work becomes production-driven because HigherGov exercises the
sync runtime.

### Milestone HG-7 — Optional row-stream CSV migration

Only after schema and concurrency integration is stable: evaluate row-stream CSV
processing, benchmark against pandas, migrate only row-local transformations, retain
vectorized and dataframe-wide operations in pandas. The decision is based on memory and
performance measurements, not line-count reduction.

### Milestone HG-8 — Async Feed

Then continue with `Feed = AsyncIterable[Item]`, lazy `AsyncPipe` chaining, AnyIO, bounded
async map, merge, cancellation, timeout, and async source normalization. HigherGov's
existing async OpenAI path can remain outside Riko until this milestone. See
[Async Feed integration](#async-feed-integration) below for the Feed integration detail.

### Milestone HG-9 — RDP and Connect

Finally return to the RDP specification, Singer compatibility, batches, manifests, state
stores, checkpoints, CDC, schema evolution events, and Connect execution plans. The schema
contracts implemented for HigherGov become the first working slice of this architecture
rather than throwaway application validation.

## Dependency change

HigherGov and current Riko both require Python 3.12+. Current Riko is version `0.69.0`.
During development, HigherGov should use a pinned Git revision or local workspace source:

```toml
[project]
dependencies = [
    "riko",
]

[tool.uv.sources]
riko = { path = "../riko", editable = true }
```

After the callable and schema APIs are released, replace that with a minimum released
version and update `uv.lock`.

## HigherGov-first definition of done

The first production Riko milestone is complete when:

1. `SyncPipe.map()` and `flat_map()` exist using current module primitives.
2. HigherGov has no direct executor code in the selected migrated functions.
3. CSV, API, scrape, and Airtable boundaries have explicit schema contracts.
4. Removed required fields fail before transformation.
5. Added fields produce structured warnings.
6. Airtable empty fields and removed fields are distinguishable through metadata.
7. Selenium drivers are always closed.
8. Heroku worker limits remain unchanged.
9. Golden output fixtures match the pre-Riko implementation.
10. Schema drift and processing failures are reported separately.

## Async Feed integration

HigherGov uses `Feed` as the **asynchronous I/O layer between DataFrame-oriented stages**,
not as a replacement for pandas or for the script-level pipeline.

## Feed as the async I/O layer

The basic architecture:

```text
SQL / CSV / Airtable
        ↓
schema validation
        ↓
DataFrame or paginated source
        ↓
Feed[Item]
        ↓
bounded async I/O processing
        ↓
Feed[Item]
        ↓
DataFrame / batch sink
        ↓
existing pandas transforms, SQL, or Airtable
```

Feed avoids creating a list of every record and submitting all tasks at once. It provides
bounded submission, natural backpressure, results as they finish, normal Riko error/retry
handling, and cancellation through the pipeline.

## Best HigherGov Feed use cases

### 1. OpenAI processing

The strongest Feed use case. The current implementation iterates the complete DataFrame,
builds `entry_args`, creates one task handle per entry, waits for the entire task group,
and merges all answers. Document summarization follows the same pattern. A Feed-based
implementation processes entries lazily with bounded concurrency:

```python
async def entry_feed(entries: pd.DataFrame):
    for row in entries.itertuples(index=False):
        yield {
            column: value
            for column, value in zip(entries.columns, row, strict=True)
        }


async def analyze_entry(item: dict, **kwargs) -> dict:
    description = str(
        {
            key: value
            for key, value in item.items()
            if key != "id" and pd.notna(value)
        }
    )

    return await _aanalyze_entry(
        description=description,
        entry_id=item["id"],
        question=kwargs["question"],
    )


flow = (
    AsyncPipe(source=entry_feed(entries_df), context=context)
    .map(analyze_entry, concurrency=MAX_CONCURRENT, ordered=False, question=question)
)

answers = [answer async for answer in flow]
```

**Recursive document summarization** — the chunks of one document must remain sequential
because later chunks may include prior summaries. Concurrency is **across documents**, not
across chunks within one document:

```python
async def summarize_document(item: dict, **kwargs) -> dict:
    summary = await _asummarize_text_recursive(
        chunks=item["summary_iterators"],
        large_doc=item["size_category"] == "large",
    )

    return {**item, "Summary": summary}
```

The existing OpenAI SDK retry configuration remains responsible for HTTP-level retries.
Riko should not independently retry the entire document callable unless explicitly
configured.

### 2. Webpage-content fetching

Scripts 08 and 13 perform blocking URL extraction through pandas `.apply()`. Feed executes
these blocking functions in a bounded thread pool:

```python
def fetch_finder_content(item: dict, **kwargs) -> dict:
    content = get_content_from_path(item["url"])

    if content and len(content) > 100_000:
        content = reduce_text(content, truncation=True)

    return {**item, "Finder Webpage Content": content}


flow = (
    AsyncPipe(source=finder_opportunity_feed(dataframe))
    .map(
        fetch_finder_content,
        execution="thread",
        concurrency=3,
        ordered=False,
        side_effects="none",
        determinism="nondeterministic",
    )
)
```

Preferable to `SyncPipe(parallel=True)` here because the containing script already has
async-compatible dependencies, Feed provides bounded submission, cancellation is meaningful
for long HTTP fetches, and results can be sent to Airtable in batches without waiting for
every page. The callable still receives Riko's normal kwargs; there is no special context
signature.

### 3. HigherGov API calls

The per-row body becomes an ordinary thread-executed callable (initially, because the
current implementation uses `requests`):

```python
def call_highergov_api(item: dict, **kwargs) -> dict:
    result = _api_call_single_item(item)
    return result if result is not None else item


flow = (
    AsyncPipe(source=dataframe_feed(cleaned_higher_df))
    .map(
        call_highergov_api,
        execution="thread",
        concurrency=4,
        ordered=False,
        side_effects="none",
        determinism="nondeterministic",
    )
)
```

Later the callable may use an async HTTP client; no other HigherGov code changes because
`AsyncPipe.map()` supports synchronous and asynchronous callables.

The Feed source validates its input schema before yielding anything, and returned API
records are validated before downstream transformation:

```python
async def validated_api_input_feed(dataframe, schema):
    report = inspect_dataframe_schema(dataframe, schema)

    if report["removed_required"]:
        raise SchemaDriftError(report)

    for item in dataframe_records(dataframe):
        yield item


flow = (
    AsyncPipe(source=validated_api_input_feed(df, INPUT_SCHEMA))
    .map(call_highergov_api, execution="thread", concurrency=4)
    .map(validate_api_result)
)
```

### 4. HigherGov document fetching

Script 09 becomes an incremental Feed pipeline:

```text
opportunity
    ↓ flat_map
fetch document metadata → document
    ↓
extract text → chunk document → reuse cached summary or summarize → clean and hash
    ↓
batch database write
```

```python
flow = (
    AsyncPipe(source=opportunity_feed(logic_mapped))
    .flat_map(fetch_documents, execution="thread", concurrency=4, ordered=False)
    .map(normalize_document)
    .map(extract_document_text, execution="thread", concurrency=3, ordered=False)
    .map(summarize_if_needed, concurrency=MAX_CONCURRENT, ordered=False)
    .map(hash_document)
)
```

`fetch_documents()` uses `flat_map` because one opportunity can return multiple documents.
Do **not** flatten summary chunks into independent records — a large document's summary
chunks are ordered and stateful; keep them inside the document item and let the
summarization callable consume the iterator sequentially.

### 5. Airtable pagination and updates

A Feed source adapter wraps Airtable pagination, loading and validating authoritative
metadata before yielding records:

```python
async def airtable_feed(table, *, view: str | None = None, schema: dict):
    metadata = await anyio.to_thread.run_sync(load_table_metadata, table)
    validate_airtable_metadata(metadata, schema)

    async for page in airtable_pages(table, view=view):
        for record in page:
            yield normalize_airtable_record(record, metadata)
```

Updates remain batches:

```python
async for batch in achunks(flow, 10):
    await anyio.to_thread.run_sync(
        partial(
            opportunities_table.batch_update,
            list(batch),
            replace=False,
            typecast=True,
        )
    )
```

Feed adds value even though Airtable requires batched writes: records read page by page,
transformations begin before the full table loads, update batches write incrementally, and
bounded queues prevent fetchers from outrunning writes. DataFrame-wide steps (duplicate
detection, whole-table masks) still load a DataFrame.

### 6. Selenium scraping

Feed replaces the outer executor but retains the chunk-level browser lifecycle. Represent
each chunk as one Feed item:

```python
async def dataframe_chunk_feed(dataframe: pd.DataFrame, size: int):
    for start in range(0, len(dataframe), size):
        yield {
            "start": start,
            "records": dataframe.iloc[start : start + size].to_dict("records"),
        }


def scrape_chunk(item: dict, **kwargs) -> dict:
    chunk = pd.DataFrame(item["records"])
    result = _scrape_highergov(chunk)
    return {"start": item["start"], "records": result.to_dict("records")}


flow = (
    AsyncPipe(source=dataframe_chunk_feed(opportunities, 15))
    .map(
        scrape_chunk,
        execution="thread",
        concurrency=1 if IS_HEROKU else 3,
        ordered=False,
        side_effects="non_idempotent",
        determinism="nondeterministic",
    )
)
```

Bounded scheduling and cancellation without thread-local drivers. Explicit worker resource
setup/cleanup (`worker_resource=ChromeDriverResource(...)`) is not needed for the first
integration.

### 7. URL redirect resolution

Use a Feed of batches; each result remains `{"results": {...}, "failures": [...]}` and a
final reducer combines dictionaries and failure lists. Do not convert to one URL per driver
invocation:

```python
flow = (
    AsyncPipe(source=url_batch_feed(pairs, batch_size=20))
    .map(
        process_redirect_batch,
        execution="thread",
        concurrency=3,
        ordered=False,
        side_effects="none",
        determinism="nondeterministic",
    )
)
```

## Feed and schema drift

Feed makes schema validation a source-boundary guarantee.

**CSV source** — validation occurs before the first row is yielded:

```python
async def highergov_csv_feed(path, schema, mappings):
    header = read_csv_header(path)
    report = diff_schema(schema, header)

    if report["removed_required"]:
        raise SchemaDriftError(report)

    for row in csv_dict_rows(path):
        yield normalize_csv_row(row, mappings)
```

**Airtable source** — Metadata API → validate field IDs/types → normalize empty fields →
start yielding records.

**API source** — validate input dataframe → call API → validate each returned payload →
yield normalized result.

**Scrape source** — web scraping has no authoritative metadata, so validate the normalized
output shape and field health:

```python
result = {**EMPTY_SCRAPE_RESULT[source_type], **scraped}
validate_scrape_result(result, source_type)
```

A missing output key is schema drift. A present key whose value is `None` is an empty scrape
result. This directly supports issue #176's empty-versus-removed distinction.

## Where Feed should not be used

**Keep pandas for whole-dataset operations** — do not convert these merely to use Riko:
`combine_first` and DataFrame joins, global duplicate detection, mask calculations
depending on the entire dataset, vectorized date and string transformations,
source-specific CSV transformations, schema reports requiring the complete column set, and
Airtable batch payload formatting. For these stages, `Feed → collect into DataFrame →
pandas transformation → optionally return to Feed` is valid.

**Keep SQL as a durable script boundary** — Feed initially operates **inside** each script.
Do not attempt `script 01 → one live Feed → script 17`. Use `script input → Feed
processing → existing SQL/Airtable output`. This limits recovery scope and avoids requiring
checkpoints and Connect before HigherGov can use Feed.

## Recommended HigherGov Feed slices

**Slice 1: OpenAI and webpage content** — implement lazy `AsyncPipe` chaining, AnyIO
runtime, bounded async `map`, synchronous callable thread offload, ordered/unordered
results, cancellation and `aclose()`. Migrate OpenAI document summarization, OpenAI entry
analysis, Finder webpage content, and Opportunity webpage content.

**Slice 2: HigherGov APIs** — add async/thread callable retries, `flat_map`, structured
errors, per-stage counters. Migrate opportunity API calls, document API calls, document
content extraction.

**Slice 3: blocking stateful resources** — migrate Selenium scrape chunks and redirect
batches. Keep browser ownership inside each chunk callable.

**Slice 4: paginated ingestion and batched sinks** — add Airtable page source, SQL
row/chunk source, batch/chunk operator, incremental Airtable and SQL sinks.

## Minimal Feed functionality HigherGov actually needs

HigherGov does not need the entire Connect/RDP roadmap to use Feed. Its initial dependency:

```text
Feed = AsyncIterable[Item]

AsyncPipe accepts:
    Items
    Feed
    Awaitable[Items | Feed]

AsyncPipe.map:
    lazy
    bounded concurrency
    ordered=True by default
    thread execution for blocking callables

AsyncPipe.flat_map:
    lazy expansion
    bounded concurrency
    sync or async iterable results

Lifecycle:
    cancellation
    aclose()
    bounded result queues

Context:
    existing Context passed through normal kwargs
```

It does not initially require manifests, checkpoint lineage, CDC, RDP messages, Arrow
batches, merge dependency groups, process execution, or persistent stage state.

The practical HigherGov architecture is therefore:

```text
pandas for dataset logic
Feed for concurrent I/O
schema contracts at source boundaries
SQL/Airtable for durable boundaries
```

Feed is a near-term HigherGov requirement rather than a post-HigherGov roadmap item.


---

> **Salvaged from the retired `productionizing.md` §7.** File-by-file schema-drift implementation for the HigherGov schema contracts (HG-2/HG-3 above). Not a P-track phase.

# Schema-drift implementation (salvaged)

Schema drift is a HigherGov prerequisite, but it should not be embedded directly in `collections.py`.

## 7.1 `riko/types/schema.py`

Add report types:

```python
class SchemaField(TypedDict, total=False):
    type: str | list[str]
    nullable: bool
    required: bool
    external_id: str
```

```python
class FieldTypeChange(TypedDict):
    field: str
    expected: object
    observed: object
```

```python
class SchemaDriftReport(TypedDict):
    source: str
    added: list[str]
    removed: list[str]
    rename_candidates: list[dict[str, str]]
    type_changes: list[FieldTypeChange]
    nullable_changes: list[str]
    computed_field_errors: list[str]
```

## 7.2 `riko/schema.py`

Start with one simple module.

Functions:

```python
def inspect_records_schema(...) -> dict: ...
def diff_schema(...) -> SchemaDriftReport: ...
def validate_schema(...) -> SchemaDriftReport: ...
```

The expected schema is a Draft-07 mapping or boolean schema.

Behavior:

* missing required field → error
* added field → warning by default
* removed optional field → warning by default
* incompatible type change → error
* rename similarity → advisory candidate only
* stable external field IDs → authoritative rename detection

Do not require pandas in this module.

HigherGov can provide DataFrame column and dtype information through an adapter.

## 7.3 HigherGov repository adapters

In HigherGov, add:

```text
data_enrichment_pipeline/schema/contracts.py
data_enrichment_pipeline/schema/airtable.py
data_enrichment_pipeline/schema/dataframe.py
data_enrichment_pipeline/schema/preflight.py
```

These files:

* convert DataFrame dtypes to generic schema observations;
* inspect CSV headers;
* query Airtable Metadata;
* report `.errorType` computed-field failures;
* call the generic riko schema functions.

This satisfies issue #176 without making pandas or Airtable part of riko core.

---
