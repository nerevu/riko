# riko Improvement Roadmap

## Index

[Background](#background) | [Milestone 1 — API Ergonomics](#milestone-1--api-ergonomics) | [Milestone 2 — Error Handling](#milestone-2--error-handling) | [Milestone 3 — DataFrame Integration](#milestone-3--dataframe-integration) | [Milestone 4 — Async Modernisation](#milestone-4--async-modernisation) | [Milestone 5 — New Source Pipes](#milestone-5--new-source-pipes) | [Milestone 6 — fetchpage Improvements](#milestone-6--fetchpage-improvements) | [Milestone 7 — Column Transformation Pipes](#milestone-7--column-transformation-pipes) | [Summary Table](#summary-table)

---

## Background

This roadmap addresses gaps identified when integrating riko into a DataFrame-centric pipeline
that replaces manual `ThreadPoolExecutor` patterns and sequential `Series.apply()` calls. The
analysis surfaced six categories of issues, ordered here from fastest to ship to most involved.

The target integration patterns are:

```python
# Pattern A — parallel per-item processing
flow = SyncPipe.from_df(df).pipe(my_fn)
result_df = flow.to_df()

# Pattern B — parallel URL fetching per item
sources = [{'url': url} for url in urls]
stream = SyncCollection(sources).fetch()

# Pattern C — parallel fetch with content extraction
items = [{'_idx': idx, 'url': url} for idx, url in url_series.items() if pd.notna(url)]
flow = SyncPipe.from_records(items, parallel=True, workers=3)
result = {item['_idx']: item['content'] for item in flow.pipe(fetch_fn).output}

# Pattern E — serial column transformation from CSV source (no intermediate DataFrame)
(
    stream
        .coalesce('Client Email', 'Client Email_1_drop', 'Client Email_2_drop')
        .strtransform(conf={'rule': {'field': KEY_COL, 'transform': 'lower'}})
        .regex(conf={'rule': {'field': KEY_COL, 'match': r'(\\w+)', 'replace': ''}})
)

# Pattern F — serial column transformation from existing DataFrame
# (uses applys directly — no SyncPipe involved)
result_df = SyncPipe.from_df(df).coalesce('Client Email', 'Client Email_1_drop')
```

---

## Milestone 1 — API Ergonomics

**Goal**: Make the above integration patterns work with minimal boilerplate.

### 1.1 Add `SyncPipe.pipe(callable)` / `AsyncPipe.pipe(callable)`

**Problem**: The integration doc assumes `flow.pipe(fn)` routes to an arbitrary callable.
`SyncPipe.__getattr__` routes any attribute name to a module lookup — `riko.modules.pipe`
does not exist, so `flow.pipe(fn)` raises `ModuleNotFoundError`.

The `aggregate` module already provides this capability: `flow.aggregate(func=fn)` applies `fn` to every
stream item. But the name is not discoverable and the calling convention differs from what
library users expect.

**Fix**: Add an explicit `.pipe(callable, **kwargs)` method on both `SyncPipe` and `AsyncPipe`
that delegates to `.aggregate(func=callable, **kwargs)`.

```python
# riko/collections.py — SyncPipe
def pipe(self, fn, **kwargs):
    return self.aggregate(func=fn, **kwargs)
```

```python
# Usage
flow = SyncPipe(source=items).pipe(my_function)
```

**Files changed**: `riko/collections.py`
**Effort**: Low

---

### 1.2 Add `SyncPipe.from_df(dataframe)` / `AsyncPipe.from_df(dataframe)`

**Problem**: buld a pipe from dataframe, not an iterable of dicts.

The correct current idiom is `SyncPipe(source=iter(list_of_dicts))`

**Fix**: Add a `from_df` class method that creates a `SyncPipe` / `AsyncPipe` directly
from a dataframe, with full `parallel`, `workers`, and `threads` support.

```python
# riko/collections.py — SyncPipe
@classmethod
def from_df(cls, df, **kwargs):
    return cls(source=df.to_dict('records'), **kwargs)
```

```python
# Usage
flow = SyncPipe.from_df(df, parallel=True, workers=4)
flow = AsyncPipe.from_df(df)
```

**Files changed**: `riko/collections.py`
**Effort**: Low

---


### 1.4 Improve `aggregate` discoverability

**Problem**: `flow.aggregate(func=fn)` is the existing way to apply a callable, but:
- The name `aggregate` is a data-warehouse term that most Python developers don't associate with "apply a function"
- The `func` keyword arg is required but not obvious
- The module is not listed prominently in README or docs

**Fix**:
- Add `.pipe(callable)` as the primary interface (see 1.1)
- Keep `.aggregate(func=callable)` for backwards compatibility
- Add a `aggregate` example to the README "Usage" section

**Files changed**: `README.rst`, `docs/`
**Effort**: Low

---

## Milestone 2 — Error Handling

**Goal**: Parallel processing should isolate per-item failures rather than crashing the
entire pool.

### 2.1 Per-item error isolation in `SyncPipe` parallel output

**Problem**: `SyncPipe.output` uses `Pool.imap_unordered` or `ThreadPool.imap_unordered`.
If the pipe function raises an exception for one item, the exception propagates and the
entire parallel job fails. This is unsafe for production workloads where some items are
expected to fail (e.g., 404 responses, malformed records).

**Fix**: Wrap the per-item call in a try/except inside the worker function. Failed items
yield an error dict rather than raising, so the stream continues processing.

```python
# riko/collections.py
# before
@property
def list(self):
    return list(self.fetch())


# after
@property
def list(self):
    results = []

    try:
        for result in self.fetch():
            results.append(result)
    except Exception as e:
        error = {'_riko_item': source}
        error[self.error_key] = str(e)
        results.append(error)

    return results
```

Add an `error_key` parameter to `SyncPipe` constructor (default: `'_riko_error'`). Items
with this key present can be filtered downstream:

```python
flow = SyncPipe(items, parallel=True, error_key='_error')
results = [item for item in flow if '_error' not in item]
errors = [item for item in flow if '_error' in item]
```

**Files changed**: `riko/collections.py`
**Effort**: Medium

---

### 2.2 Add `on_error` callback parameter

**Problem**: Callers need visibility into which items failed and why, without having to
filter the output stream manually.

**Fix**: Accept an optional `on_error` callable on `SyncPipe`:

```python
def on_error(item, exc):
    logger.warning(f"Failed to process {item}: {exc}")

flow = SyncPipe(items, parallel=True, on_error=on_error)
```

When a per-item exception is caught, `on_error(item, exc)` is called and the item is
skipped from the output stream entirely.

**Files changed**: `riko/collections.py`
**Effort**: Low (follows from 2.1)

---

### 2.3 Thread-local worker state (`worker_init`)

**Problem**: Several integration patterns require per-worker stateful resources that are
not thread-safe:

- `requests.Session` — not thread-safe; one per thread avoids contention
- Selenium `WebDriver` — not thread-safe; one driver per thread, each signed in separately

Currently riko has no mechanism to initialise per-thread resources before the pool starts
processing items. Users must replicate the `threading.local()` pattern inside every pipe
callable, leaking infrastructure concerns into business logic.

**Fix**: Add an optional `worker_init` callable to `SyncPipe`. When `parallel=True`, it is
passed to `ThreadPool(initializer=worker_init)` (supported since Python 3.7). The callable
runs once per worker thread before any items are processed, with no arguments. The pipe
callable can then retrieve the thread-local resource via `threading.local()`:

```python
import threading
import requests

_local = threading.local()

def init_session():
    _local.session = requests.Session()
    _local.session.headers['Authorization'] = f'Bearer {TOKEN}'

def resolve_url(item):
    resolved = _local.session.get(item['url'], allow_redirects=True).url
    yield {**item, 'resolved_url': resolved}

flow = SyncPipe(items, parallel=True, workers=5, worker_init=init_session)
result = flow.pipe(resolve_url).list
```

For process-based pools (`threads=False`), `worker_init` is passed to `Pool(initializer=…)`
which has the same interface. In that case callers are responsible for using module-level
globals rather than `threading.local()`.

**Files changed**: `riko/collections.py`
**Effort**: Low–Medium

---

## Milestone 3 — DataFrame Integration

**Goal**: Surface existing DataFrame support that is hidden behind an undiscoverable API,
add the missing input-side constructor, and complete the unimplemented `fetchdataframe` pipe.

### What already exists

`SyncPipe.export()` accepts an `out_type` argument and routes through `CONVERSION_FUNCS`:

```python
CONVERSION_FUNCS = {
    "dataframe": cv.records2df,   # ← already wired up
    "csv":       cv.records2csv,
    "json":      cv.records2json,
    "list":      lambda items, **kw: list(items),
    # ...
}
```

So `flow.export('dataframe')` already produces a `pd.DataFrame` via `meza.convert.records2df`.
The `list` property is itself just `self.export()`. The output-side of DataFrame integration
is complete — it just needs exposure.

---

### 3.1 Add `SyncPipe.from_df(df)` class method

**Problem**: The output side works (`export('dataframe')`), but there is no input-side
counterpart. Creating a stream from an existing DataFrame requires the undocumented
`SyncPipe(source=iter(df.to_dict('records')))` idiom.

**Fix**: Add `from_df` as a named constructor that delegates to `from_records`:

```python
# riko/collections.py — PyPipe
@classmethod
def from_df(cls, df, *args, **kwargs):
    records = df.to_dict('records')
    return cls.__init__(*args, source=records, **kwargs)
```

```python
# Usage
flow = SyncPipe.from_df(df, parallel=True, workers=4)
result_df = flow.pipe(process_row).export('dataframe')
```

**Files changed**: `riko/collections.py`
**Effort**: Low

---

### 3.2 Add `SyncPipe.to_df()` alias

**Problem**: `flow.export('dataframe')` already works, but the string argument is
undiscoverable and inconsistent with how users expect a "get me a DataFrame" method
to look. `pd.DataFrame(list(flow.output))` is what users reach for by default,
bypassing `meza` entirely.

**Fix**: Add `.to_df()` as a named alias for `export('dataframe')`:

```python
# riko/collections.py — SyncPipe
def to_df(self, **kwargs):
    return self.export('dataframe', **kwargs)
```

```python
# Usage — before (undiscoverable)
result_df = flow.export('dataframe')

# Usage — before (bypasses meza)
result_df = pd.DataFrame(flow.list)

# Usage — after
result_df = flow.to_df()
```

**Files changed**: `riko/collections.py`
**Effort**: Trivial

---

### 3.3 Add `riko[pandas]` optional extra and document `export` types

**Problem**: `meza` (which provides `records2df`) requires pandas transitively, but this
is not surfaced in `setup.py` as a named extra. Users who want DataFrame output have no
install target to point to, and no documentation listing all supported `out_type` values.

**Fix**:

Add a named extra to `setup.py`:

```python
extras_require={
    "pandas": ["pandas>=1.3.0"],
    "async": async_require,
    "async-anyio": anyio_require,
    "xml": xml_require,
    "develop": dev_requirements,
}
```

Add a table to `README.rst` listing all `export()` output types:

| `out_type` | Output | Notes |
|---|---|---|
| `"list"` | `list[dict]` | Default |
| `"dataframe"` | `pd.DataFrame` | Requires `riko[pandas]` |
| `"csv"` | CSV string | via `meza` |
| `"json"` | JSON string | via `meza` |
| `"array"` | numpy array | via `meza` |
| `"geojson"` | GeoJSON dict | via `meza` |
| `"ofx"` | OFX stream | Requires `csv2ofx` |
| `"qif"` | QIF stream | Requires `csv2ofx` |
| `"tuple"` | `tuple` | |

**Files changed**: `setup.py`, `README.rst`
**Effort**: Low

---

## Milestone 4 — Async Modernisation

**Goal**: Remove the async incompatibility that prevents riko from working alongside
`asyncio`-based libraries (e.g., `anyio`, `httpx`).

The integration doc notes:

> `util_openai.py` async processing — uses asyncer/anyio. riko's async is Twisted-based — incompatible concurrency model.

This incompatibility means riko cannot be used in an async context alongside anyio without
running a separate event loop — a significant footgun.

### 4.1 Convert `inlineCallbacks` to `async`/`await`

See [ASYNC_AWAIT_CONVERSION.md](ASYNC_AWAIT_CONVERSION.md).

Convert all `@coroutine` / `yield` / `return_value` usage in `riko/bado/` and
`riko/modules/` to native `async def` / `await` / `return`. This is a prerequisite for
the anyio backend and also improves stack traces and mypy support.

**Files changed**: `riko/bado/__init__.py`, `riko/bado/io.py`, `riko/bado/itertools.py`, `riko/bado/util.py`, `riko/collections.py`, all `riko/modules/*.py` with async variants
**Effort**: Medium (mechanical, file-by-file)

---

### 4.2 Add anyio async backend

See [ANYIO_SUPPORT.md](ANYIO_SUPPORT.md).

Add `anyio` as an alternative async backend selectable via `RIKO_ASYNC_BACKEND=anyio`.
This replaces Twisted's `getPage`/`downloadPage`/`FileSender` with `httpx.AsyncClient`
and anyio file I/O, and replaces `Cooperator`/`gatherResults` with `asyncio.gather` /
`anyio.TaskGroup`.

After this milestone, riko's async API is compatible with any `asyncio`-based code,
including projects that use `anyio`, `httpx`, or `asyncpg`.

**Files changed**: `riko/bado/__init__.py`, `riko/bado/io.py`, `riko/bado/itertools.py`, `riko/bado/util.py`, `riko/bado/mock.py`, `setup.py`
**Effort**: Medium

---

## Milestone 5 — New Source Pipes

**Goal**: Allow riko to read directly from data sources beyond files and URLs.

### 5.1 Add `fetchsql` source pipe

**Problem**: The integration pipeline stores intermediate data in PostgreSQL and reads it
back before each step. There is no way to feed a SQL query result directly into a riko
stream without first loading into a DataFrame.

**Fix**: Create `riko/modules/fetchsql.py` — a source pipe that reads from any
SQLAlchemy-compatible database in a streaming fashion using `yield_per()`.

```python
from riko.collections import SyncPipe

flow = SyncPipe('fetchsql', conf={
    'url': 'postgresql+psycopg2://user:pass@host/db',
    'query': 'SELECT id, url FROM opportunities WHERE processed = false',
    'chunk_size': 1000,
})
flow = flow.pipe(process_opportunity)
result_df = flow.to_df()
```

**Design notes**:
- Uses `sqlalchemy.create_engine` + `connection.execution_options(stream_results=True)`
- Streams rows as plain dicts using `yield_per(chunk_size)` to keep memory bounded
- SQLAlchemy is an optional dependency: `pip install riko[sql]`
- Handles connection lifecycle (open on iteration start, close on stream exhaustion or error)

**Files created**: `riko/modules/fetchsql.py`
**Files changed**: `setup.py`, `optional-requirements.txt`, `README.rst`, `docs/FAQ.rst`
**Effort**: Medium

---

### 5.2 Implement `fetchdataframe` source pipe (existing stub)

**Problem**: `fetchdataframe` is declared in `riko/modules/__init__.__sources__` and
referenced in `riko/modules/__init__.__all__`, but `riko/modules/fetchdataframe.py`
does not exist. Any attempt to use it raises `ModuleNotFoundError`.

This is the natural pipe-level counterpart to `SyncPipe.from_df()` — it allows a
DataFrame to be declared as a named source inside a flow, making the flow definition
fully declarative.

**Fix**: Create `riko/modules/fetchdataframe.py` following the same `@processor` pattern
used by other source pipes (e.g., `csv.py`, `itembuilder.py`):

```python
# riko/modules/fetchdataframe.py
from . import processor
import pygogo as gogo

OPTS = {"ftype": "none", "emit": True}
logger = gogo.Gogo(__name__, monolog=True).logger


def parser(_, objconf, skip=False, **kwargs):
    stream = kwargs["stream"] if skip else iter(objconf.dataframe.to_dict('records'))
    return stream


@processor(**OPTS)
def pipe(*args, **kwargs):
    return parser(*args, **kwargs)
```

```python
# Usage — declarative DataFrame source
flow = SyncPipe('fetchdataframe', conf={'dataframe': my_df})
flow = flow.filter(conf={'rule': {'field': 'status', 'op': 'is', 'value': 'active'}})
result_df = flow.to_df()

# Usage — chained after another source
flow = SyncPipe('fetchdataframe', conf={'dataframe': enriched_df}).pipe(process_row)
```

**Design notes**:
- `conf['dataframe']` holds the in-memory DataFrame; `parser` calls `.to_dict('records')`
  and yields each row
- Follows the same `OPTS = {"ftype": "none"}` pattern as `csv` and `itembuilder` to
  mark itself as a source (not a transformer)
- An async variant (`async_pipe`) can be added later following the same pattern as other
  source pipes

**Files created**: `riko/modules/fetchdataframe.py`
**Files changed**: `docs/FAQ.rst` (add to pipe table), `README.rst`
**Effort**: Low

---

## Milestone 6 — fetchpage Improvements

**Goal**: Make `fetchpage` useful for pipelines that need non-HTML content types.

### 6.1 Add content-type-aware response handling

**Problem**: `fetchpage` currently returns raw HTML (bytes or string) with optional tag
stripping (`detag=True`). It cannot handle PDF, DOCX, or plain-text URLs, which are
common in document-fetching pipelines.

The integration doc notes:

> `util_text_extract.get_content_from_url` does HTML→Markdown conversion and handles
> multiple content types (PDF, DOCX, etc.). riko's `fetchpage` only returns raw HTML
> with optional tag stripping.

**Fix**: Add a `postprocess` option to `fetchpage` that accepts a callable applied to
the raw response after fetching:

```python
from riko.collections import SyncPipe

def html_to_markdown(content):
    from markdownify import markdownify
    return markdownify(content)

flow = SyncPipe.from_records(url_items, parallel=True)
flow = flow.fetchpage(
    conf={'url': url, 'detag': False},
    postprocess=html_to_markdown,
    assign='content',
)
```

This keeps `fetchpage` focused on fetching while delegating transformation to the caller.
The `postprocess` callable receives the raw string content and returns the transformed value.

**Files changed**: `riko/modules/fetchpage.py`
**Effort**: Low

---

### 6.2 Add `fetchpage` response metadata

**Problem**: `fetchpage` currently only yields the page content. There is no way to access
the HTTP status code, content-type header, or final URL after redirects from within the
stream.

**Fix**: Add a `include_meta` option (default: `False`) that includes response metadata
alongside the content:

```python
flow = flow.fetchpage(conf={'url': url}, include_meta=True, assign='page')

# Each output item will contain:
# {
#   'page': '<html>...',
#   'page_status': 200,
#   'page_content_type': 'text/html',
#   'page_final_url': 'https://example.com/canonical',
# }
```

**Files changed**: `riko/modules/fetchpage.py`, `riko/utils.py`
**Effort**: Low–Medium

---

## Milestone 7 — Column Transformation Pipes

**Goal**: Provide built-in composable pipes for the recurring column manipulation patterns
that appear in DataFrame-centric pipelines: coalescing fallback columns, normalising IDs,
stripping URL noise, dropping staging columns by suffix, and applying string operations.

These patterns appear 4–9 times each across a typical pipeline's data processing utilities.
The riko approach replaces 10–20 lines of pandas per function with a single declarative
`transform_csv()` or `applys()` call.

**Two usage modes:**

| Mode | When to use | Mechanism |
|---|---|---|
| CSV-first (`transform_csv`) | Source data comes from a CSV file | `_csv_stream` generator + `applys` — no intermediate DataFrame |
| DataFrame-first (`applys`) | Data already in memory as a DataFrame | `df.to_dict('records')` → `applys` → `pd.DataFrame()` |

---

### 7.1 `coalesce(primary, *fallbacks)`

**Problem**: `df['col_a'] = df['col_a'].fillna(df['col_b']).fillna(df['col_c'])` appears
repeatedly. Each occurrence is 3–5 lines of pandas and hardcodes column names as strings
scattered through the function body.

**Fix**: A pipe factory that fills `primary` from each fallback in order when the value
is `None` or `float('nan')`:

```python

result_df = (
    SyncPipe.from_df(df)
        .coalesce(conf=('Client Email', 'Client Email_1_drop', 'Client Email_2_drop'))
        .coalesce(conf=('Client Phone', 'Client Phone_drop'))
)
```

Implementation uses IEEE 754 identity (`result != result` is `True` only for `float('nan')`)
to detect NaN without importing `math.isnan`, keeping the pipe callable dependency-free.

**Files created**: `riko/modules/coalesce.py`
**Effort**: Low

---

### 7.2 `strip(column)`

**Problem**: `df[col] = df[col].str.strip('/ ')` appears once per data-processing function
to normalise a special key column that accumulates leading/trailing slashes and spaces
through redirect chains.

**Fix**:

```python

result_df = SyncPipe.from_df(df).strip('Opportunity Link')
```

**Files changed**: `riko/modules/strip.py`
**Effort**: Trivial

---

### 7.3 `regex(column)`

**Problem**: `df[col] = df[col].astype(str).str.replace(r'-|_', '', regex=True)` appears
three times to strip hyphens and underscores from solicitation ID fields before comparison.

**Fix**:

```python

conf={'rule': {'field': 'Solicitation ID', 'match': r'-|_', 'replace': ''}}
result_df = SyncPipe.from_df(df).regex(conf=conf)
```

**Effort**: Trivial

---

### 7.4 `rename(*suffixes)`

**Problem**: Each data-processing function ends with a `.filter(regex='_drop').columns`
→ `.drop(columns=…)` block to remove staging columns.

```python
remove_rule = [
    {"field": r".*_drop$"},
    {"field": r".*_additional$"},
]

return SyncPipe.from_df(df).rename(conf={"rule": remove_rule})
```

Note: `rename` must be the **last** pipe in any chain that uses `coalesce`
on `_drop`-suffixed fallback columns — those columns are read before being dropped.

**Effort**: Trivial

---

### 7.5 `strtransform(column, *ops)`

**Problem**: String normalisation (`.str.lower()`, `.str.split(r'...').str[0]`) is applied
to contact fields in several functions, sometimes after a coalesce so the operation also
covers merged-in values. Each usage is 2–3 lines.

**Fix**: `strtransform`:

```python
SyncPipe.from_df(df).strtransform(conf={'rule': {'field': 'Client Email', 'transform': 'lower'}})
```

**Files changed**: `riko/transform.py`
**Effort**: Trivial

---

### 7.6 `applys(stream, *pipes)` serial composition helper

**Problem**: Chaining pipe factories over any iterator of dicts requires repeating
`chain.from_iterable(pipe_fn(item) for item in stream)` for every factory. This is the
serial composition primitive that all column transform patterns are built on.

**Fix**: A standalone generator function that applies factories left to right with zero overhead:

```python
# riko/transform.py
from itertools import chain as _chain

def applys(self, *pipes):
    result = self

    for pipe_name, conf in pipes:
        pipe = get_pipe(pipe_name)
        result = _chain.from_iterable(pipe(item, conf) for item in result)

    return result
```

`applys` is pure generator composition — fully lazy, no `SyncPipe` involved, no
threading overhead. It is the preferred mechanism for serial O(n) column operations.

**Usage with DataFrame input:**

```python

result_df = SyncPipe.from_df(df).applys(
    ('coalesce', ('Client Phone', 'Client Phone_drop')),
    ('coalesce', ('Client Email', 'Client Email_1_drop', 'Client Email_2_drop')),
    ('rename', {"rule": {"field": r".*_drop$"}})
)
```

**Usage with CSV input (zero intermediate DataFrame):**

```python
conf={'rule': {'field': 'Solicitation ID', 'match': r'^(nan|None)$', 'replace': ''}}

sources = [{'url': url} for url in urls]
stream = SyncCollection(sources).csv().regex(conf=conf)
```

The CSV-first path eliminates the `pd.read_csv → DataFrame → .to_dict('records')` round-trip,
so no intermediate DataFrame is allocated.

**Files created**: `riko/transform.py`
**Effort**: Trivial

---

## Summary Table

| # | Change | Milestone | Status | Impact | Effort | Files |
|---|---|---|---|---|---|---|
| 1.1 | `SyncPipe.pipe(callable)` method | 1 | Missing | High | Low | `collections.py` |
| 1.2 | `SyncPipe.from_records(iterable)` class method | 1 | Missing | High | Low | `collections.py` |
| 1.3 | Verify + document `fetchpage` subkey URL | 1 | Unverified | Medium | Low | `parsers.py`, `fetchpage.py` |
| 1.4 | Improve `aggregate` discoverability | 1 | Missing | Low | Low | `README.rst` |
| 2.1 | Per-item error isolation in parallel | 2 | Missing | High | Medium | `collections.py` |
| 2.2 | `on_error` callback parameter | 2 | Missing | Medium | Low | `collections.py` |
| 2.3 | `worker_init` for thread-local resource setup | 2 | Missing | High | Low–Medium | `collections.py` |
| 3.1 | `SyncPipe.from_df(df)` class method | 3 | Missing | High | Low | `collections.py` |
| 3.2 | `SyncPipe.to_df()` alias for `export('dataframe')` | 3 | **Exists** (undiscoverable) | High | Trivial | `collections.py` |
| 3.3 | Document all `export()` types + `riko[pandas]` extra | 3 | Partial | Low | Low | `setup.py`, `README.rst` |
| 4.1 | `async`/`await` conversion | 4 | Missing | High | Medium | `bado/`, `modules/` |
| 4.2 | anyio async backend | 4 | Missing | High | Medium | `bado/`, `setup.py` |
| 5.1 | `fetchsql` source pipe | 5 | Missing | High | Medium | new file, `setup.py` |
| 5.2 | `fetchdataframe` source pipe | 5 | **Stub** (no file) | Medium | Low | new file |
| 6.1 | `fetchpage` `postprocess` option | 6 | Missing | Medium | Low | `fetchpage.py` |
| 6.2 | `fetchpage` response metadata | 6 | Missing | Low | Low–Medium | `fetchpage.py` |
| 7.1 | `coalesce(primary, *fallbacks)` | 7 | Missing | High | Low | `transform.py` |
| 7.2 | `strip(column)` | 7 | Missing | Medium | Trivial | `transform.py` |
| 7.6 | `applys(stream, *pipes)` serial composition helper | 7 | Missing | High | Trivial | `transform.py` |

---

## Suggested Implementation Order

Implement milestones sequentially. Within each milestone, ship items in the order listed.

```
Milestone 1 (1–2 weeks)
  └── 1.2 from_records → 1.1 .pipe() → 1.3 subkey verify → 1.4 aggregate docs

Milestone 2 (1–2 weeks)
  └── 2.1 error isolation → 2.2 on_error callback → 2.3 worker_init

Milestone 3 (1 week)
  └── 3.1 from_df → 3.2 to_df → 3.3 pandas extra

Milestone 4 (2–3 weeks)
  └── 4.1 async/await conversion → 4.2 anyio backend

Milestone 5 (1–2 weeks)
  └── 5.2 fetchdataframe (complete stub) → 5.1 fetchsql (new, complex)

Milestone 6 (1 week)
  └── 6.1 postprocess → 6.2 metadata

Milestone 7 (1 week)
  └── 7.6 applys → 7.1 coalesce → 7.2 strip → 7.3 normalize_id
      → 7.4 drop_suffix → 7.5 string_op → 7.7 transform_columns
```

Milestones 1–3 are entirely sync-side and can be shipped before any async work is done.
Milestone 4 is independent of 1–3 and can proceed in parallel on a separate branch.
Milestones 5–6 can begin once Milestones 1–3 are complete and the API shape is stable.
Milestone 7 is independent of all others — `riko/transform.py` has no dependency on
changes from other milestones and can be shipped at any time. `applys` and the pipe
factories have zero dependency on `SyncPipe`.

Items marked **Exists** in the summary table require only a thin alias or documentation
fix — no new logic. Items marked **Stub** have a declared module name in `__sources__`
but no corresponding `.py` file.
