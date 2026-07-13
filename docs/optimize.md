# riko Modernization & Optimization Guide

## Index

[Python Syntax](#python-syntax) | [Type Annotations](#type-annotations) | [Packaging](#packaging) | [Performance & Correctness](#performance--correctness) | [Code Quality](#code-quality) | [Dependencies](#dependencies) | [Dead Code & Removed Features](#dead-code--removed-features) | [Summary Table](#summary-table)

---

## Python Syntax

### S.1 Remove `(object)` base class declarations

Python 3 makes all classes new-style by default. The explicit `(object)` base is
redundant noise.

**Occurrences** (8): `PyPipe`, `PyCollection`, `processor`, `operator`, `Reactor`,
`TimeoutIterator`, `Chainable`, and `Node` in `bado/microdom.py`.

```python
# Before
class PyPipe(object):
class processor(object):

# After
class PyPipe:
class processor:
```

**Files**: `riko/collections.py`, `riko/modules/__init__.py`, `riko/bado/__init__.py`,
`riko/modules/timeout.py`, `riko/utils.py`, `riko/bado/microdom.py`
**Effort**: Trivial

---

### S.2 Replace old-style `super()` calls

`super(ClassName, self)` is Python 2 style. Python 3 zero-argument `super()` is cleaner
and avoids repeating the class name.

**Occurrences** (5 non-`bado`): `SyncPipe`, `SyncCollection`, `AsyncPipe`, `AsyncCollection`,
`DotDict`.

```python
# Before
super(SyncPipe, self).__init__(name, source, **kwargs)
super(DotDict, self).__getitem__(keys[0])

# After
super().__init__(name, source, **kwargs)
super().__getitem__(keys[0])
```

**Files**: `riko/collections.py`, `riko/dotdict.py`
**Effort**: Trivial

---

### S.3 Standardise string formatting to f-strings

The codebase uses a mix of `%`-formatting and f-strings. The `%` style appears in
`bado/util.py`, `collections.py`, `modules/__init__.py`, and several modules.

```python
# Before
self.pipe = import_module("riko.modules.%s" % self.name).pipe
logger.debug("xml parser: lxml")

# After
self.pipe = import_module(f"riko.modules.{self.name}").pipe
```

**Effort**: Low

---

### S.4 Use `|` union type syntax (Python 3.10+)

Once the minimum Python version is raised to 3.10, replace `Optional[X]` with `X | None`
and `Union[X, Y]` with `X | Y` in type annotations.

```python
# Before (requires `from __future__ import annotations` or 3.10+)
def get_value(item, conf=None, ...) -> Optional[str]:

# After (3.10+)
def get_value(item, conf=None, ...) -> str | None:
```

**Effort**: Low (batch search/replace after annotations are added)

---

## Type Annotations

### T.1 Annotate `riko/utils.py` public functions

The utility module has no type annotations. The most-called functions are good starting
points:

```python
from collections.abc import Callable, Iterator
from typing import Any

def multiplex(sources: Iterator[Iterator[dict]]) -> Iterator[dict]: ...
def multi_try(source: Any, zipped: list[tuple[Callable, type]], default: Any = None) -> Any: ...
def group_by(iterable: Iterator[dict], attr: str, default: Any = None) -> Iterator[tuple[str, list[dict]]]: ...
```

**Files**: `riko/utils.py`
**Effort**: Medium

---

### T.2 Annotate `processor` and `operator` wrappers

The `@processor()` and `@operator()` decorators accept a rich set of `**opts` but no
annotations exist. Adding `ParamSpec` and `TypeVar` allows type checkers to infer the
wrapped function's signature through the decorator.

```python
from typing import TypeVar, Callable, ParamSpec

P = ParamSpec('P')
T = TypeVar('T')

class processor:
    def __call__(self, pipe: Callable[P, T]) -> Callable[P, Iterator[dict]]: ...
```

**Files**: `riko/modules/__init__.py`
**Effort**: Medium

---

### T.3 Annotate `SyncPipe` and `AsyncPipe` public API

`SyncPipe.pipe`, `.export`, `.to_df`, `.output`, `.list` (from ROADMAP
items 1.1–3.2) should all carry return-type annotations as they are added.

```python
@classmethod
def from_records(cls, records: Iterable[dict], **kwargs: Any) -> SyncPipe: ...

@property
def output(self) -> Iterator[dict]: ...

@property
def list(self) -> list[dict]: ...

def to_df(self) -> pd.DataFrame: ...
```

**Files**: `riko/collections.py`
**Effort**: Low (incremental, as new methods are added)

---

### T.4 Add `TypedDict` for conf objects

Conf dicts (passed to every pipe as `conf={}`) are plain `dict` today. `TypedDict`
subclasses for the most-used pipes would let type checkers catch misconfigured flows at
development time.

```python
from typing import TypedDict

class FetchPageConf(TypedDict, total=False):
    url: str | dict
    start: str
    end: str
    token: str
    detag: bool
    memoize: bool
```

**Files**: new `riko/types.py`
**Effort**: Medium (one `TypedDict` per pipe, add incrementally)

---

## Packaging

### P.1 Migrate to `pyproject.toml`-only packaging

`setup.py` uses `pkutils` (a niche helper) for manifest parsing. PEP 517/518 packaging
with a fully declarative `[project]` section in `pyproject.toml` eliminates this
dependency and makes the project easier to build and audit.

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "riko"
version = "0.67.0"
description = "A Python stream processing engine"
requires-python = ">=3.9"
dependencies = ["meza>=0.42.1", "mezmorize", "pygogo", "requests"]

[project.optional-dependencies]
xml   = ["lxml", "speedparser3"]
async = ["twisted", "treq"]
pandas = ["pandas>=1.3"]
```

**Files**: `pyproject.toml`, delete `setup.py`
**Effort**: Low

---

### P.2 Update Python version classifiers and minimum

`setup.py` classifiers only list Python 3.7–3.9. End-of-life versions (3.7, 3.8) can be
dropped. Add 3.10–3.13 to the classifier list and raise `python_requires` to `>=3.9`.

Dropping 3.7/3.8 unlocks `|` union types in signatures (3.10 for runtime, 3.9 for
`from __future__ import annotations`) and `match`/`case` (3.10).

**Files**: `pyproject.toml`
**Effort**: Trivial

---

### P.3 Replace `nose` with `pytest`

`setup.py` still references `test_suite = "nose.collector"`. `nose` has been unmaintained
since 2015 and does not support Python 3.10+. Migrate to `pytest`:

```toml
# pyproject.toml
[tool.pytest.ini_options]
testpaths = ["tests"]
doctest_optionflags = ["NORMALIZE_WHITESPACE", "ELLIPSIS"]
addopts = "--doctest-modules"
```

**Files**: `pyproject.toml`, `dev-requirements.txt`
**Effort**: Low

---

### P.4 Publish a `riko[pandas]` optional extra

`meza` pulls in `pandas` transitively but there is no named extra for users who want the
`export('dataframe')` / `to_df()` path. Add a `pandas` extra alongside the existing `xml`
and `async` extras (see ROADMAP item 3.3).

```toml
[project.optional-dependencies]
pandas = ["pandas>=1.3"]
```

**Files**: `pyproject.toml`
**Effort**: Trivial

---

## Performance & Correctness


`group_by` must be updated to use the key string for ordering, not the element, since it
currently passes the yielded value to `groups[key]` lookup.

**Files**: `riko/utils.py`
**Effort**: Low (fix + regression test)

---

### O.2 `group_by` — avoid double materialisation and re-sort

`group_by` materialises the full list twice (once as `data`, once via `sorted`) and then
uses `unique_everseen` only for ordering. A single-pass dict preserves insertion order
natively in Python 3.7+ and avoids the sort:

```python
def group_by(iterable, attr, default=None):
    keyfunc = def_itemgetter(attr, default)
    groups: dict[str, list] = {}

    for item in iterable:
        key = str(keyfunc(item))
        groups.setdefault(key, []).append(item)

    return groups.items()
```

This eliminates: one `list(iterable)` call, one `sorted()` call, and the `unique_everseen`
call. For large streams the memory saving is significant.

**Files**: `riko/utils.py`
**Effort**: Low

---

### O.3 `DotDict.get` — remove unnecessary copy

`DotDict.get` creates a full `DotDict(self.copy())` at the start of every call, then
traverses keys modifying `value`. The copy is only needed as an initial value — subsequent
iterations replace it immediately.

```python
# Before — copies the entire dict on every .get() call
def get(self, key=None, default=None, **kwargs):
    keys = self._parse_key(key)
    value = DotDict(self.copy())    # <-- unnecessary copy

# After — start from self directly
def get(self, key=None, default=None, **kwargs):
    keys = self._parse_key(key)
    value = self
    ...
```

`DotDict.get` is called for every field access in every conf resolution, so this is a
hot path in any non-trivial pipeline.

**Files**: `riko/dotdict.py`
**Effort**: Low (requires careful testing of the traversal logic)

---

### O.5 `SyncPipe.output` — pool not cleaned up on partial iteration

When `parallelize=True` and `reuse_pool=False`, the pool is closed only at the end of
`output` property evaluation — but `output` is a generator. If the caller stops
iterating early (e.g. `.list[:5]`), `pool.close()` and `pool.join()` are never called,
leaking worker threads or processes.

**Fix**: Use a `try/finally` around the mapped iteration, or switch from `imap` to a
context-managed executor pattern that guarantees cleanup regardless of how many items
are consumed.

```python
@property
def output(self):
    pipeline = partial(self.pipe, **self.kwargs)

    if self.parallelize:
        zipped = zip(self.source, repeat(pipeline))
        mapped = self.map(listpipe, zipped, chunksize=self.chunksize)
        try:
            yield from multiplex(mapped)
        finally:
            if not self.reuse_pool:
                self.pool.close()
                self.pool.join()
    elif self.mapify:
        yield from multiplex(self.map(pipeline, self.source))
    else:
        yield from pipeline(self.source)
```

**Files**: `riko/collections.py`
**Effort**: Low–Medium

---

### O.6 `get_value` — exception-driven type dispatch

`get_value` in `parsers.py` uses four separate `except` clauses to detect whether `conf`
is a `DotDict`, a plain value, `None`, etc. This is the hot path for every pipe invocation.
Replacing exception-driven dispatch with `isinstance` guards reduces overhead and makes
the logic readable:

```python
def get_value(item, conf=None, force=False, default=None, **kwargs):
    item = item or {}

    if conf is None:
        return default

    if isinstance(conf, dict) and "subkey" in conf:
        return item.get(conf["subkey"], **kwargs)

    if isinstance(conf, dict) and "value" in conf and not set(kwargs).difference(["objectify"]):
        return conf["value"]

    if force:
        return conf

    if hasattr(conf, "get"):
        return conf.get(**kwargs)

    return conf
```

**Files**: `riko/parsers.py`
**Effort**: Medium (requires careful testing against existing edge cases)

---

### O.7 `processor` wrapper — bare `except:` swallows errors silently

In `modules/__init__.py` (line ~405):

```python
try:
    _input = DotDict(item) if combined.get("dictize") else item
except:
    print(list(item))
```

The bare `except:` catches `KeyboardInterrupt` and `SystemExit` as well as all errors.
The `print` call is a debug artifact. Replace with a specific exception and use `logger`:

```python
try:
    _input = DotDict(item) if combined.get("dictize") else item
except (TypeError, ValueError) as e:
    logger.debug("Failed to DotDict item: %s — %r", e, item)
    _input = item
```

**Files**: `riko/modules/__init__.py`
**Effort**: Trivial

---

### O.8 `SyncPipe.__getattr__` — risk of infinite recursion on internal attributes

`__getattr__` unconditionally returns `SyncPipe(name, ...)` for any missing attribute,
including Python dunder names like `__repr__`, `__reduce__`, and `__copy__`. This can
cause recursion errors when pickling (required for `ProcessPool`) or during debug
introspection.

```python
# Before — no guard
def __getattr__(self, name):
    return SyncPipe(name, source=iter(self), ...)

# After — guard dunders and internal names
def __getattr__(self, name):
    if name.startswith("_"):
        raise AttributeError(name)
    return SyncPipe(name, source=iter(self), ...)
```

**Files**: `riko/collections.py`
**Effort**: Low

---

## Code Quality

### Q.1 Replace `send`/`receive` module-level mutable globals

`riko/utils.py` uses four module-level mutable dicts/queues (`_registry`, `_collector`,
`_pubsub_instances`, `_item_queue`) as the shared state for the `send`/`receive` pipe
pattern. This is not thread-safe — concurrent pipelines sharing the same process will
corrupt each other's state.

Encapsulate state in a `PipelineContext` object passed explicitly (or as a
`contextvars.ContextVar` for async pipelines):

```python
import contextvars

_pipeline_ctx: contextvars.ContextVar[dict] = contextvars.ContextVar(
    '_pipeline_ctx', default={}
)

def send(name, item):
    ctx = _pipeline_ctx.get()
    ctx.setdefault(name, []).append(item)
```

`contextvars.ContextVar` is safe for both thread-pool and asyncio concurrent execution.

**Files**: `riko/utils.py`, `riko/modules/send.py`, `riko/modules/receive.py`
**Effort**: Medium

---

### Q.2 `fetch` class — replace `TextIOBase` subclass with `contextmanager`

`fetch` inherits from `io.TextIOBase` but only overrides `read`, `readline`, `close`, and
conditionally `seek`. It is used exclusively as a context manager. A `@contextmanager`
function avoids the class boilerplate and the awkward `LocalProxy` workaround for
memoized responses:

```python
from contextlib import contextmanager

@contextmanager
def fetch(url=None, memoize=False, **kwargs):
    opener = get_opener(memoize=memoize, **kwargs)
    response, content_type = opener(get_abspath(url))
    ...
    try:
        yield f
    finally:
        f.close()
```

**Files**: `riko/utils.py`
**Effort**: Medium

---

### Q.3 Remove debug `print` statements from production paths

Production code in `riko/utils.py` and `riko/modules/receive.py` contains `print`
calls that should be `logger.debug`:

| Location | Current | Fix |
|---|---|---|
| `utils.py:606` | `print((f"send to {name}", item))` | `logger.debug("send to %s: %r", name, item)` |
| `collections.py:199` | `print(("init", next(self)))` | `logger.debug("receive init: %r", ...)` |
| `modules/receive.py:88` | `print((f"got in {objconf.name}", item))` | `logger.debug(...)` |
| `modules/receive.py:92` | `print("while", ...)` | `logger.debug(...)` |

**Files**: `riko/utils.py`, `riko/collections.py`, `riko/modules/receive.py`
**Effort**: Trivial

---

### Q.4 `multi_try` — `else` on `for` loop is misleading

`multi_try` uses `for/else` correctly but the pattern is easy to misread:

```python
# Before
def multi_try(source, zipped, default=None):
    value = None
    for func, error in zipped:
        try:
            value = func(source)
        except error:
            pass
        else:
            return value
    else:
        return default

# After — clearer with explicit return after loop
def multi_try(source, zipped, default=None):
    for func, error in zipped:
        try:
            return func(source)
        except error:
            pass
    return default
```

This also removes the unused `value = None` assignment.

**Files**: `riko/utils.py`
**Effort**: Trivial

---

### Q.5 Resolve `TODO` comments in active code paths

Several `TODO` comments mark real issues in active paths:

| Location | TODO | Action |
|---|---|---|
| `parsers.py:238` | `# TODO: fix so .items() returns a DotDict instance` | Fix `DotDict` or use a `__iter__`-aware approach |
| `utils.py:231` | `# TODO: need to use separate timeouts for memoize and urlopen` | Add `connect_timeout` / `read_timeout` separation |
| `utils.py:296` | `# TODO: move this to meza.process.group` | Upstream to meza or inline after O.2 fix |
| `modules/aggregate.py:54` | `# TODO: this should work even when func returns a list` | Fix or document limitation |
| `modules/filter.py:144` | `# TODO: add terminal check` | Implement or close as won't-fix |

**Effort**: Low–Medium per item

---

## Dependencies

### D.1 Replace `mezmorize` with `functools.cache` / `cachetools`

`mezmorize` wraps `Flask-Cache` / `cachelib` and brings in Flask as a transitive
dependency for the in-process caching path. The only usage is in `get_opener` to cache
memoized URL responses.

`functools.lru_cache` (stdlib) or `cachetools.TTLCache` cover this without Flask:

```python
from functools import lru_cache

@lru_cache(maxsize=128)
def _cached_fetch(url: str, decode: bool = False, **kwargs) -> bytes | str:
    ...
```

For TTL-based expiry (useful for exchange rate responses), `cachetools.TTLCache` is a
lightweight alternative.

**Files**: `riko/utils.py`, `requirements.txt`
**Effort**: Low–Medium

---

### D.2 Replace bundled `microdom`/`sux` with stdlib `xml.etree`

`riko/bado/microdom.py` (800+ lines) and `riko/bado/sux.py` (670+ lines) are vendored
copies of Twisted's internal microdom/sax parser. They exist because Twisted's microdom
is not part of the public API and accessing it requires internal imports.

After the async/await conversion (ROADMAP 4.1), `xml2etree` in `bado/util.py` is the
only caller. Replace it with `xml.etree.ElementTree` (stdlib):

```python
import xml.etree.ElementTree as ET

def xml2etree(f, xml=True):
    readable = hasattr(f, "read")
    content = f.read() if readable else f
    return ET.fromstring(content) if isinstance(content, (str, bytes)) else ET.parse(f).getroot()
```

The `etree2dict` conversion in `parsers.py` already works with any ElementTree-compatible
element via `.items()`, `.text`, and child iteration — no microdom-specific API is used.

**Files**: `riko/bado/util.py`, delete `riko/bado/microdom.py`, `riko/bado/sux.py`
**Effort**: Medium (requires testing XML/RSS parsing across all source pipes)

---

### D.3 Deprecate `pkutils` in build tooling

`pkutils` is a low-maintenance helper used only in `setup.py` for parsing requirements
files and reading package metadata. Replacing `setup.py` with `pyproject.toml` (P.1)
eliminates this dependency entirely.

**Files**: `setup.py` (deleted by P.1), `dev-requirements.txt`
**Effort**: Trivial (follows from P.1)

---

### D.4 Mark `yql` module as deprecated

Yahoo Query Language (YQL) was shut down in January 2019. The `yql` module is broken
by default for all users and cannot be fixed without a replacement service. Options:

- **Deprecate**: Add a `DeprecationWarning` on import and remove in the next major version
- **Replace**: Map to a modern equivalent (e.g. a generic JSON/GraphQL fetch pipe)
- **Remove**: Delete the module if no replacement is planned

```python
# riko/modules/yql.py — top of file
import warnings
warnings.warn(
    "The yql pipe relies on Yahoo Query Language, which was shut down in 2019. "
    "This module will be removed in a future version.",
    DeprecationWarning,
    stacklevel=2,
)
```

**Files**: `riko/modules/yql.py`
**Effort**: Trivial

---

## Dead Code & Removed Features

### R.1 Remove commented-out debug `print` blocks in `utils.py`

Lines 451–516 of `utils.py` contain ~25 commented-out `print` and `pprint` calls inside
`multi_substitute`. These are debug artifacts. Remove them to reduce noise.

**Files**: `riko/utils.py`
**Effort**: Trivial

---

### R.2 Remove commented-out pollable stream code in `modules/__init__.py`

Several blocks of commented-out code for a `pollable` streaming pattern exist in the
`processor.__call__` method (the `_get_stream` inner function and the `# stream = _get_stream`
block at the end). Either implement or delete:

```python
# Remove all of these comment blocks:
# if self.pollable:
#     self.stream_func = self.pipe.__dict__.get("stream_func")

# stream = _get_stream(_input, *parsed, combined=combined, **kwargs)
# if self.isasync:
#     return_value(stream)
# else:
#     yield from stream
```

**Files**: `riko/modules/__init__.py`, `riko/collections.py`
**Effort**: Trivial

---

## Summary Table

| # | Change | Category | Impact | Effort | Files |
|---|---|---|---|---|---|
| S.1 | Remove `(object)` base classes | Syntax | Low | Trivial | `collections.py`, `modules/__init__.py`, others |
| S.2 | Replace old-style `super()` | Syntax | Low | Trivial | `collections.py`, `dotdict.py` |
| S.3 | Standardise to f-strings | Syntax | Low | Low | multiple |
| S.4 | Use `|` union type syntax | Syntax | Low | Low | multiple (after 3.10+) |
| T.1 | Annotate `riko/utils.py` | Types | Medium | Medium | `utils.py` |
| T.2 | Annotate `processor`/`operator` | Types | High | Medium | `modules/__init__.py` |
| T.3 | Annotate `SyncPipe` public API | Types | High | Low | `collections.py` |
| T.4 | Add `TypedDict` conf objects | Types | Medium | Medium | new `riko/types.py` |
| P.1 | Migrate to `pyproject.toml` | Packaging | Medium | Low | `pyproject.toml`, delete `setup.py` |
| P.2 | Update Python version classifiers | Packaging | Low | Trivial | `pyproject.toml` |
| P.3 | Replace `nose` with `pytest` | Packaging | Medium | Low | `pyproject.toml` |
| P.4 | Add `riko[pandas]` extra | Packaging | Medium | Trivial | `pyproject.toml` |
| O.1 | Fix `unique_everseen` yield bug | Correctness | High | Low | `utils.py` |
| O.2 | `group_by` single-pass rewrite | Performance | Medium | Low | `utils.py` |
| O.3 | `DotDict.get` — remove copy | Performance | High | Low | `dotdict.py` |
| O.4 | Remove `lenish` (duplicates `length_hint`) | Correctness | Low | Trivial | `collections.py` |
| O.5 | Fix pool leak on partial iteration | Correctness | High | Low–Med | `collections.py` |
| O.6 | `get_value` — replace exception dispatch | Performance | High | Medium | `parsers.py` |
| O.7 | Fix bare `except:` in `processor` | Correctness | High | Trivial | `modules/__init__.py` |
| O.8 | Guard `__getattr__` dunders | Correctness | High | Low | `collections.py` |
| Q.1 | Thread-safe send/receive globals | Correctness | High | Medium | `utils.py`, `send.py`, `receive.py` |
| Q.2 | Replace `fetch` class with `contextmanager` | Quality | Low | Medium | `utils.py` |
| Q.3 | Remove debug `print` calls | Quality | Medium | Trivial | `utils.py`, `collections.py`, `receive.py` |
| Q.4 | Simplify `multi_try` loop | Quality | Low | Trivial | `utils.py` |
| Q.5 | Resolve active `TODO` comments | Quality | Medium | Low–Med | multiple |
| D.1 | Replace `mezmorize` with stdlib cache | Dependencies | Medium | Low–Med | `utils.py` |
| D.2 | Replace `microdom`/`sux` with `xml.etree` | Dependencies | High | Medium | `bado/util.py`, delete microdom/sux |
| D.3 | Remove `pkutils` from build | Dependencies | Low | Trivial | follows from P.1 |
| D.4 | Deprecate `yql` module | Dependencies | Medium | Trivial | `modules/yql.py` |
| R.1 | Remove commented-out debug prints | Dead code | Low | Trivial | `utils.py` |
| R.2 | Remove commented-out pollable code | Dead code | Low | Trivial | `modules/__init__.py`, `collections.py` |
| R.3 | Delete `lenish` function | Dead code | Low | Trivial | `collections.py` |

---

## Suggested Implementation Order

Items grouped by dependency and risk, lowest risk first.

```
Phase 1 — Zero-risk cleanups (no behaviour change)
  S.1 (object) classes → S.2 super() → S.3 f-strings
  R.1 debug prints → R.2 pollable comments → R.3 lenish
  Q.3 print→logger → Q.4 multi_try → P.2 classifiers → P.4 riko[pandas]
  D.4 yql deprecation → D.3 pkutils (via P.1)

Phase 2 — Packaging & tooling
  P.1 pyproject.toml → P.3 pytest

Phase 3 — Correctness fixes (need tests before & after)
  O.1 unique_everseen bug → O.7 bare except → O.8 __getattr__ guard
  O.4 lenish/length_hint → O.5 pool leak

Phase 4 — Performance improvements (benchmark before & after)
  O.2 group_by → O.3 DotDict.get copy → O.6 get_value dispatch

Phase 5 — Type annotations (incremental, can go in parallel)
  T.3 SyncPipe API → T.1 utils.py → T.2 processor/operator → T.4 TypedDict

Phase 6 — Dependency reductions (highest risk, most reward)
  D.1 mezmorize → D.2 microdom/sux → Q.1 send/receive globals → Q.2 fetch class
```
