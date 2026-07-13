# Converting riko from `inlineCallbacks` to `async`/`await`

## Index

[Why Convert](#why-convert) | [Conversion Rules](#conversion-rules) | [Strategy](#strategy) | [riko Layer Map](#riko-layer-map) | [File-by-File Changes](#file-by-file-changes) | [Before/After Examples](#beforeafter-examples) | [Testing](#testing) | [Type Hints](#type-hints)

---

## Why Convert

riko's async layer (`riko/bado/`) uses Twisted's `@inlineCallbacks` / `yield` pattern, which
predates Python's native `async`/`await` syntax. Now that riko is dropping Python 2 support,
switching to native coroutines is the right move. Twisted has supported `async`/`await` since
version 16.4.

Benefits:

- **Cleaner stack traces** — `inlineCallbacks` mangles tracebacks by wrapping frames in generator machinery. Native coroutines produce stack traces that are much easier to read in Sentry or a debugger.
- **Better tooling** — `mypy`, `pyright`, and IDEs understand `async def` return types. `@inlineCallbacks` functions appear to return `Deferred` regardless of `returnValue`, so type checkers cannot infer the actual return type.
- **Standard syntax** — developers familiar with `asyncio` or `trio` can read the code without learning Twisted-specific idioms.
- **asyncio compatibility** — native coroutines can be `await`ed by any asyncio-compatible library, which is the prerequisite for adding anyio support (see [ANYIO_SUPPORT.md](ANYIO_SUPPORT.md)).
- **Performance** — Twisted's own documentation (as of v21.2.0) notes that native coroutines provide higher performance than `inlineCallbacks`.

From the Twisted docs (v21.2.0):

> Unless your code supports Python 2 (and therefore needs compatibility with older versions of
> Twisted), writing coroutines with the functionality described in "Coroutines with async/await"
> is preferred over `inlineCallbacks`.

---

## Conversion Rules

| What | `inlineCallbacks` (old) | `async`/`await` (new) |
|---|---|---|
| Function definition | `@inlineCallbacks` decorator | `async def` |
| Wait for a result | `yield deferred` | `await deferred` |
| Return a value | `returnValue(x)` | `return x` |
| Call from Twisted API | return the `Deferred` directly | wrap with `defer.ensureDeferred(coro())` |

**Interoperability rules to keep in mind:**

- You **can** `await` a `Deferred` — `Deferred` implements `__await__`.
- You **cannot** `yield` an `Awaitable` inside `@inlineCallbacks` — you must convert it first with `defer.ensureDeferred`.
- Twisted APIs (e.g. `react`, `callLater` callbacks, `IResource.render`) still expect `Deferred`. Wrap `async` call-sites with `defer.ensureDeferred`.
- `defer.ensureDeferred` is idempotent when passed a `Deferred` — it is safe to use at any boundary.

---

## Strategy

Convert from **outer layers inward**. Because `async def` functions return an `Awaitable` and
you can `await` a `Deferred`, an outer `async` function can call into inner code that still
returns a `Deferred` without any issue. This means each layer can be migrated independently.

Conversion order for riko:

```
1. riko/bado/__init__.py       ← remove inlineCallbacks/returnValue shims
2. riko/bado/io.py             ← async_url_open, async_url_read, async_read_file
3. riko/bado/itertools.py      ← coop_reduce, async_map, async_starmap
4. riko/bado/util.py           ← xml2etree entry points, async_sleep, defer_to_process
5. riko/collections.py         ← AsyncPipe.output, AsyncPipe.list, AsyncCollection
6. riko/modules/*              ← async_parser, async_pipe in each module
```

At each stage, if a converted `async` function is called from code that has **not yet been
converted** (i.e. code that passes the result to a Twisted API expecting a `Deferred`), wrap
the call with `defer.ensureDeferred`:

```python
from twisted.internet import defer

# caller not yet converted — wrap the awaitable
d = defer.ensureDeferred(my_async_func(arg))
```

Once all callers of a function are converted to `async def`, the `defer.ensureDeferred` wrapper
can be removed from each of those call-sites.

---

## riko Layer Map

```
riko/bado/__init__.py       exposes: coroutine, return_value, react
        │
        ├── riko/bado/io.py          async_url_open, async_url_read
        ├── riko/bado/itertools.py   async_map, coop_reduce, async_starmap
        └── riko/bado/util.py        xml2etree, async_sleep, defer_to_process

riko/collections.py         AsyncPipe, AsyncCollection
        │
        └── riko/modules/*/          async_parser, async_pipe (one per module)
```

The `bado` package is the foundation. Converting it first means the modules and collections
can immediately use `await` on the results.

---

## File-by-File Changes

### `riko/bado/__init__.py`

The `coroutine` and `return_value` aliases become identity functions once the codebase uses
native `async def` throughout. They are kept as no-ops so that any remaining call-sites do
not break before the full migration is complete.

**Before:**

```python
try:
    from twisted.internet.task import react
except ImportError:
    react = lambda _, _reactor=None: None
    inlineCallbacks = lambda _: lambda: None
    returnValue = lambda _: lambda: None
    backend = "empty"
else:
    from twisted.internet.defer import inlineCallbacks
    from twisted.internet.defer import returnValue
    backend = "twisted"

coroutine = inlineCallbacks
return_value = returnValue
```

**After:**

```python
from twisted.internet import defer

try:
    from twisted.internet.task import react
except ImportError:
    react = lambda _, _reactor=None: None
    backend = "empty"
else:
    backend = "twisted"

coroutine = lambda f: f       # no-op: native async def needs no decorator
return_value = lambda x: x   # no-op: use plain return statements
```

The `react` entry point still expects a function that returns a `Deferred`. If the top-level
coroutine is now `async def`, wrap it at the call-site:

```python
from twisted.internet import defer

async def run(reactor):
    result = await AsyncPipe('fetch', conf=conf).list
    print(result)

def main(reactor):
    return defer.ensureDeferred(run(reactor))

react(main)
```

### `riko/bado/io.py`

All `@coroutine`-decorated functions become `async def`. `yield` becomes `await`.
`return_value(x)` becomes `return x`.

**Before:**

```python
@coroutine
def async_url_open(url, timeout=0, **kwargs):
    if url.startswith("http"):
        page = NamedTemporaryFile(delete=False)
        new_url = page.name
        yield downloadPage(encode(url), page, timeout=timeout)
    else:
        page, new_url = None, url

    f = yield async_get_file(new_url, StringTransport(), **kwargs)
    ...
    return_value(f)
```

**After:**

```python
async def async_url_open(url, timeout=0, **kwargs):
    if url.startswith("http"):
        page = NamedTemporaryFile(delete=False)
        new_url = page.name
        await downloadPage(encode(url), page, timeout=timeout)
    else:
        page, new_url = None, url

    f = await async_get_file(new_url, StringTransport(), **kwargs)
    ...
    return f
```

### `riko/bado/itertools.py`

**Before:**

```python
@coroutine
def coop_reduce(func, iterable, initializer=None):
    task = get_task()
    iterable = iter(iterable)
    x = initializer or next(iterable)
    result = {}

    def work(func, it, x):
        for y in it:
            result["value"] = x = func(x, y)
            yield

    _task = task.cooperate(work(func, iterable, x))
    yield _task.whenDone()
    return_value(result["value"])


@coroutine
def async_map(async_func, iterable, connections=0):
    if connections and not reactor.fake:
        results = []
        work = (async_func(x).addCallback(results.append) for x in iterable)
        deferreds = [get_task().coiterate(work) for _ in range(connections)]
        yield gatherResults(deferreds, consumeErrors=True)
    else:
        deferreds = map(async_func, iterable)
        results = yield gatherResults(deferreds, consumeErrors=True)

    return_value(results)
```

**After:**

```python
async def coop_reduce(func, iterable, initializer=None):
    task = get_task()
    iterable = iter(iterable)
    x = initializer or next(iterable)
    result = {}

    def work(func, it, x):
        for y in it:
            result["value"] = x = func(x, y)
            yield

    _task = task.cooperate(work(func, iterable, x))
    await _task.whenDone()
    return result["value"]


async def async_map(async_func, iterable, connections=0):
    if connections and not reactor.fake:
        results = []
        work = (async_func(x).addCallback(results.append) for x in iterable)
        deferreds = [get_task().coiterate(work) for _ in range(connections)]
        await gatherResults(deferreds, consumeErrors=True)
    else:
        deferreds = map(async_func, iterable)
        results = await gatherResults(deferreds, consumeErrors=True)

    return results
```

### `riko/bado/util.py`

**Before:**

```python
def async_sleep(seconds):
    d = Deferred()
    callLater(seconds, d.callback, None)
    return d
```

**After:**

```python
async def async_sleep(seconds):
    d = Deferred()
    callLater(seconds, d.callback, None)
    await d
```

> `async_sleep` was previously a plain function returning a `Deferred`. Making it `async`
> keeps the interface consistent — callers now `await` it instead of `yield`-ing it.

### `riko/collections.py` — `AsyncPipe`

**Before:**

```python
@property
@coroutine
def output(self):
    source = yield self.source
    async_pipeline = partial(self.async_pipe, **self.kwargs)

    if self.mapify:
        args = (async_pipeline, source, self.connections)
        mapped = yield ait.async_map(*args)
        output = multiplex(mapped)
    else:
        output = yield async_pipeline(source)

    return_value(output)

@property
@coroutine
def list(self):
    output = yield self.output
    return_value(list(output))
```

**After:**

```python
@property
async def output(self):
    source = await self.source
    async_pipeline = partial(self.async_pipe, **self.kwargs)

    if self.mapify:
        args = (async_pipeline, source, self.connections)
        mapped = await ait.async_map(*args)
        output = multiplex(mapped)
    else:
        output = await async_pipeline(source)

    return output

@property
async def list(self):
    output = await self.output
    return list(output)
```

### `riko/modules/*/` — `async_parser` and `async_pipe`

Every module that defines `async_parser` or `async_pipe` using `@coroutine` follows the same
mechanical transformation:

**Before (example from `fetchtext.py`):**

```python
@coroutine
def async_parser(_, objconf, skip=False, **kwargs):
    if skip:
        stream = kwargs["stream"]
    else:
        url = get_abspath(objconf.url)
        f = yield io.async_url_open(url)
        assign = kwargs["assign"]
        encoding = objconf.encoding
        _stream = ({assign: line.rstrip('\n').decode(encoding)} for line in f)
        stream = auto_close(_stream, f)

    return_value(stream)
```

**After:**

```python
async def async_parser(_, objconf, skip=False, **kwargs):
    if skip:
        stream = kwargs["stream"]
    else:
        url = get_abspath(objconf.url)
        f = await io.async_url_open(url)
        assign = kwargs["assign"]
        encoding = objconf.encoding
        _stream = ({assign: line.rstrip('\n').decode(encoding)} for line in f)
        stream = auto_close(_stream, f)

    return stream
```

The pattern is identical across all modules:
1. Replace `@coroutine` with `async def`
2. Replace `yield` with `await`
3. Replace `return_value(x)` with `return x`

---

## Before/After Examples

### Entry point (`react` usage)

**Before:**

```python
from riko.bado import coroutine, react
from riko.bado.mock import FakeReactor
from riko.collections import AsyncPipe

@coroutine
def run(reactor):
    results = yield AsyncPipe('fetch', conf=conf).list
    print(results)

react(run, _reactor=FakeReactor())
```

**After:**

```python
from twisted.internet import defer, task
from riko.bado.mock import FakeReactor
from riko.collections import AsyncPipe

async def run(reactor):
    results = await AsyncPipe('fetch', conf=conf).list
    print(results)

def main(reactor):
    return defer.ensureDeferred(run(reactor))

task.react(main, _reactor=FakeReactor())
```

### Pipe with intermediate await

**Before:**

```python
from riko.bado import coroutine, return_value
from riko.bado import io

@coroutine
def async_parser(_, objconf, skip=False, **kwargs):
    if skip:
        stream = kwargs["stream"]
    else:
        url = get_abspath(objconf.url)
        f = yield io.async_url_open(url)
        stream = (line for line in f)

    return_value(stream)
```

**After:**

```python
from riko.bado import io

async def async_parser(_, objconf, skip=False, **kwargs):
    if skip:
        stream = kwargs["stream"]
    else:
        url = get_abspath(objconf.url)
        f = await io.async_url_open(url)
        stream = (line for line in f)

    return stream
```

---

## Testing

Tests that mock `async_pipe` or `async_parser` functions must be updated to return
awaitable values instead of plain `Deferred` objects.

**Before (mock returning Deferred):**

```python
from twisted.internet import defer

module.async_pipe = lambda item, **kw: defer.succeed([item])
```

**After (mock as async function):**

```python
async def _mock_pipe(item, **kw):
    return [item]

module.async_pipe = _mock_pipe
```

Tests that call the entry point via `react` should wrap the top-level coroutine with
`defer.ensureDeferred`:

```python
from twisted.internet import defer, task
from riko.bado.mock import FakeReactor

async def run(reactor):
    result = await AsyncPipe('fetchdata', conf=fconf).count().list
    assert result == [{'count': 169}]

def test_async_pipe():
    try:
        task.react(lambda r: defer.ensureDeferred(run(r)), _reactor=FakeReactor())
    except SystemExit:
        pass
```

---

## Type Hints

One of the most valuable side-effects of this conversion is that `mypy` can now check return
types. `@inlineCallbacks` functions appear to return `Deferred[Any]` regardless of `returnValue`,
so type checkers cannot infer the actual return type.

**Before (opaque to type checkers):**

```python
@inlineCallbacks
def async_parser(_, objconf, **kwargs):
    result = yield fetch_something()
    returnValue(result)   # mypy sees return type as Deferred[Any]
```

**After (transparent):**

```python
async def async_parser(_, objconf, **kwargs) -> Generator:
    result = await fetch_something()
    return result          # mypy infers the correct return type
```

Add return type annotations progressively as each function is converted — the conversion
is a natural opportunity to document the intended types.
