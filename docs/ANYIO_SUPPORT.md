# anyio Support Plan

## Index

[Overview](#overview) | [Prerequisites](#prerequisites) | [Current Architecture](#current-architecture) | [anyio vs Twisted](#anyio-vs-twisted) | [Backend Selection](#backend-selection) | [Implementation Plan](#implementation-plan) | [File-by-File Changes](#file-by-file-changes) | [Installation](#installation) | [Testing](#testing) | [Migration Guide](#migration-guide)

---

## Overview

riko currently uses [Twisted](https://twisted.org/) as its sole async backend. Adding
[anyio](https://anyio.readthedocs.io/) support allows users to run riko's async layer on
`asyncio` or `trio` without any dependency on Twisted.

Benefits of anyio support:

- **Backend flexibility** — anyio supports both `asyncio` and `trio` as underlying runtimes
- **Ecosystem compatibility** — async libraries like `httpx` and `asyncpg` work natively
- **Reduced footprint** — users who don't need Twisted's network stack avoid the dependency
- **Future-proofing** — the broader Python async ecosystem has converged on `asyncio`-compatible primitives

---

## Prerequisites

**Complete the `async`/`await` conversion first.**

Before adding anyio support, riko's `inlineCallbacks`/`returnValue` code must be converted
to native `async`/`await` syntax. This is documented in [ASYNC_AWAIT_CONVERSION.md](ASYNC_AWAIT_CONVERSION.md).

After that conversion:

- All `riko/bado/` functions are native `async def` / `await` coroutines
- `coroutine` in `riko/bado/__init__.py` is already an identity decorator (no-op)
- `return_value` in `riko/bado/__init__.py` is already a no-op
- The only Twisted-specific code that remains is I/O (`getPage`, `downloadPage`, `FileSender`), concurrency (`Cooperator`, `gatherResults`), and the reactor itself

This means the coroutine syntax difference between Twisted and anyio **disappears** after
the conversion. The two backends differ only in their runtime primitives, not in how
coroutines are written.

---

## Current Architecture

All async logic lives under `riko/bado/`. After the `async`/`await` conversion the key
Twisted-specific abstractions that remain are:

| Twisted abstraction | Role | Location |
|---|---|---|
| `react` | Entry point — runs the event loop | `riko/bado/__init__.py` |
| `Deferred` | Represents a future value | `riko/bado/util.py` |
| `gatherResults` | Waits for multiple Deferreds | `riko/bado/itertools.py` |
| `Cooperator` | Cooperative multitasking scheduler | `riko/bado/itertools.py` |
| `getPage` / `downloadPage` | HTTP fetch | `riko/bado/io.py` |
| `FileSender` | Async file streaming protocol | `riko/bado/io.py` |
| `callLater` | Schedule a callback after a delay | `riko/bado/util.py` |
| `getProcessOutput` | Run a subprocess asynchronously | `riko/bado/util.py` |
| `MemoryReactorClock` | In-memory test reactor | `riko/bado/mock.py` |

The `backend` variable in `riko/bado/__init__.py` controls which set of primitives is used.
After the `async`/`await` conversion, `inlineCallbacks` and `returnValue` are no longer
part of this list — they have been removed.

---

## anyio vs Twisted

### Concept Mapping

Both backends now use native `async`/`await`. The differences are confined to runtime
primitives:

| Twisted primitive | anyio equivalent | Notes |
|---|---|---|
| `react(main)` | `anyio.run(main)` | Entry point for event loop |
| `defer.ensureDeferred(coro())` | `await coro()` | At Twisted API boundaries only |
| `Deferred` | `Coroutine` / `asyncio.Future` | Standard awaitables; `Deferred` is `await`-able |
| `defer.succeed(x)` | `async def f(): return x` | Immediate value coroutine |
| `gatherResults(deferreds)` | `asyncio.gather(*coros)` | Or `anyio.TaskGroup` |
| `maybeDeferred(f, *a)` | `await anyio.to_thread.run_sync(f, *a)` | When `f` may be sync |
| `Cooperator` | `anyio.TaskGroup` | Structured concurrency |
| `callLater(n, cb)` | `await anyio.sleep(n)` | Async sleep |
| `getPage(url)` | `httpx.AsyncClient().get(url)` | Requires `httpx` |
| `downloadPage(url, f)` | `httpx.AsyncClient().get(url)` | Stream response to file |
| `FileSender` protocol | `await anyio.open_file(path, 'rb')` | Native async file I/O |
| `getProcessOutput(cmd)` | `await anyio.run_process(cmd)` | Async subprocess |
| `MemoryReactorClock` | `pytest-anyio` fixtures | Test infrastructure |

### What is the same after conversion

Once the `async`/`await` conversion is complete, both backends share:

- `async def` / `await` coroutine syntax — no decorator, no `yield`
- Plain `return` statements — no `returnValue`
- The same `riko/bado/__init__.py` shims (`coroutine` = identity, `return_value` = no-op)

The only per-backend differences live in the four files listed in the implementation plan below.

---

## Backend Selection

### Selection Mechanism

The backend is chosen in the following priority order:

1. **Environment variable** `RIKO_ASYNC_BACKEND` — set to `"twisted"` or `"anyio"`
2. **Auto-detection** — try importing Twisted first, then anyio, then fall back to sync mode

```sh
RIKO_ASYNC_BACKEND=anyio python myscript.py
```

### Programmatic Selection

```python
import os
os.environ['RIKO_ASYNC_BACKEND'] = 'anyio'

from riko.collections import AsyncPipe
```

### Backend Constants

```python
from riko.bado import backend, _issync, _isasync

# backend is one of: "twisted", "anyio", "empty"
# _issync is True when backend == "empty"
# _isasync is True when backend is twisted or anyio
```

---

## Implementation Plan

### Phase 0 — `async`/`await` conversion (prerequisite)

Complete the conversion documented in [ASYNC_AWAIT_CONVERSION.md](ASYNC_AWAIT_CONVERSION.md).
After this phase, `coroutine` and `return_value` in `riko/bado/__init__.py` are already
identity/no-op and require no further change for the anyio backend.

### Phase 1 — `riko/bado/__init__.py`

Add backend detection. Because the coroutine syntax is now identical for both backends, the
only per-backend difference here is the event loop entry point (`react` vs `anyio.run`).

```python
import os
from twisted.internet import defer

_env_backend = os.environ.get('RIKO_ASYNC_BACKEND', '').lower()
_twisted_ok = False
_anyio_ok = False

if _env_backend != 'anyio':
    try:
        from twisted.internet.task import react as _twisted_react
    except ImportError:
        pass
    else:
        _twisted_ok = True

if not _twisted_ok and _env_backend != 'twisted':
    try:
        import anyio as _anyio
    except ImportError:
        pass
    else:
        _anyio_ok = True

if _twisted_ok:
    react = _twisted_react
    backend = "twisted"
elif _anyio_ok:
    def react(coro, _reactor=None):
        _anyio.run(coro, None)

    backend = "anyio"
else:
    react = lambda _, _reactor=None: None
    backend = "empty"

coroutine = lambda f: f       # identity — no-op after async/await conversion
return_value = lambda x: x   # no-op — plain return statements used throughout

class Reactor(object):
    fake = False

reactor = Reactor()
_issync = backend == "empty"
_isasync = not _issync
```

**Unified interface both backends share:**

| Name | Twisted value | anyio value |
|---|---|---|
| `coroutine` | identity (no-op) | identity (no-op) |
| `return_value` | no-op | no-op |
| `react` | `twisted.internet.task.react` | wrapper around `anyio.run` |
| `backend` | `"twisted"` | `"anyio"` |
| `_issync` | `False` | `False` |
| `_isasync` | `True` | `True` |

### Phase 2 — `riko/bado/io.py`

Replace Twisted protocol-based I/O with anyio and httpx equivalents.

**Current (Twisted, post async/await conversion):**
- `FileReader(AccumulatingProtocol)` — streams a file using Twisted's `FileSender`
- `async_url_open` — downloads via `downloadPage`, reads file via `StringTransport`
- `async_url_read` — fetches URL content via `getPage`

**New (anyio):**
- `async_read_file(filename)` — reads using `await anyio.open_file(filename, 'rb')`
- `async_url_open(url)` — downloads via `httpx.AsyncClient` into a `BytesIO` buffer
- `async_url_read(url)` — fetches via `httpx.AsyncClient().get(url).content`

**Key structural difference:** anyio functions do not require a `transport` or `protocol`
argument. Callers that currently pass a `StringTransport()` must be updated.

### Phase 3 — `riko/bado/itertools.py`

Replace Twisted `Cooperator` and `gatherResults` with anyio/asyncio equivalents.

| Twisted | anyio |
|---|---|
| `gatherResults(deferreds)` | `asyncio.gather(*coros)` |
| `Cooperator.cooperate(work)` | `async for item in async_generator: ...` |
| `async_map` with connections | `anyio.TaskGroup` with semaphore |
| `coop_reduce` | `async for` loop with accumulator |

**New `async_map` with concurrency control:**

```python
async def async_map(async_func, iterable, connections=0):
    import asyncio
    items = list(iterable)

    if connections:
        semaphore = anyio.Semaphore(connections)

        async def bounded(item):
            async with semaphore:
                return await async_func(item)

        results = await asyncio.gather(*(bounded(x) for x in items))
    else:
        results = await asyncio.gather(*(async_func(x) for x in items))

    return results
```

### Phase 4 — `riko/bado/util.py`

Replace Twisted deferred utilities with anyio equivalents.

| Twisted | anyio |
|---|---|
| `defer.succeed(x)` | `async def _wrap(): return x` |
| `maybeDeferred(f, *a)` | `await anyio.to_thread.run_sync(f, *a)` |
| `callLater(n, cb)` + `Deferred` | `await anyio.sleep(n); cb()` |
| `getProcessOutput(exe, args, env)` | `(await anyio.run_process([exe]+args, env=env)).stdout` |
| `microdom.parseXML` | `lxml.etree` or `xml.etree.ElementTree` |

> **Note on `xml2etree` / `etree2dict`:** These currently depend on Twisted's `microdom`.
> Under anyio, replace with `lxml.etree` (preferred) or `xml.etree.ElementTree`.
> Output may differ slightly for malformed XML.

### Phase 5 — `riko/bado/mock.py`

Replace `MemoryReactorClock` with anyio-compatible test infrastructure.

**Current (Twisted):** `FakeReactor(MemoryReactorClock)` — fakes the Twisted reactor.

**New (anyio):** Use `pytest-anyio` fixtures. For compatibility with code that checks
`reactor.fake`, keep a simple sentinel:

```python
class FakeReactor:
    _DELAY = 0

    def __init__(self):
        reactor.fake = True
```

---

## File-by-File Changes

### `riko/bado/__init__.py`

Replace the existing try/except block with the detection logic shown in Phase 1 above.
The `coroutine` and `return_value` aliases are now uniform no-ops for all backends.

### `riko/bado/io.py`

Add a new anyio branch alongside the existing Twisted branch:

```python
from riko.bado import backend

if backend == "anyio":
    import anyio
    import httpx

    async def async_url_read(url, timeout=0, **kwargs):
        if url.startswith("http"):
            async with httpx.AsyncClient() as client:
                r = await client.get(url, timeout=timeout or None)
            result = r.content
        else:
            path = url.replace("file://", "")
            async with await anyio.open_file(path, "rb") as f:
                result = await f.read()
        return result

    async def async_url_open(url, timeout=0, **kwargs):
        content = await async_url_read(url, timeout=timeout, **kwargs)
        return BytesIO(content)
```

### `riko/bado/itertools.py`

Add a new anyio branch:

```python
if backend == "anyio":
    import asyncio

    async def coop_reduce(func, iterable, initializer=None):
        it = iter(iterable)
        x = initializer if initializer is not None else next(it)
        for y in it:
            x = func(x, y)
        return x

    async def async_reduce(async_func, iterable, initializer=None):
        it = iter(iterable)
        x = initializer if initializer is not None else next(it)
        for y in it:
            x = await async_func(x, y)
        return x

    async def async_map(async_func, iterable, connections=0):
        items = list(iterable)
        if connections:
            import anyio
            semaphore = anyio.Semaphore(connections)
            async def bounded(item):
                async with semaphore:
                    return await async_func(item)
            results = await asyncio.gather(*(bounded(x) for x in items))
        else:
            results = await asyncio.gather(*(async_func(x) for x in items))
        return results

    async def async_starmap(async_func, iterable):
        return await asyncio.gather(*(async_func(*args) for args in iterable))

    def async_dispatch(split, *async_funcs, **kwargs):
        return async_starmap(lambda item, f: f(item), zip(split, async_funcs))

    def async_broadcast(item, *async_funcs, **kwargs):
        import itertools as it
        return async_dispatch(it.repeat(item), *async_funcs, **kwargs)
```

### `riko/bado/util.py`

Add a new anyio branch:

```python
if backend == "anyio":
    import anyio

    async def async_sleep(seconds):
        await anyio.sleep(seconds)

    async def defer_to_process(command):
        result = await anyio.run_process(
            [sys.executable, "-c", command], env=environ
        )
        return result.stdout

    async_none = None
    async_return = lambda x: x

    def xml2etree(f, xml=True):
        try:
            from lxml import etree
            readable = hasattr(f, "read")
            if readable:
                return etree.parse(f)
            return etree.fromstring(f if isinstance(f, bytes) else f.encode())
        except ImportError:
            import xml.etree.ElementTree as ET
            readable = hasattr(f, "read")
            if readable:
                return ET.parse(f)
            return ET.fromstring(f if isinstance(f, str) else f.decode())
```

### `riko/bado/mock.py`

Add a new anyio branch:

```python
if backend == "anyio":
    class FakeReactor:
        _DELAY = 0

        def __init__(self):
            reactor.fake = True

        def callLater(self, when, what, *args, **kwargs):
            what(*args, **kwargs)
```

---

## Installation

New extras for anyio support in `setup.py` / `optional-requirements.txt`:

```
anyio>=3.6.0,<5.0.0
httpx>=0.24.0,<1.0.0
```

These are separated from the existing `async` extra (which installs Twisted):

| Extra | Packages | Command |
|---|---|---|
| `async` | `Twisted`, `treq` | `pip install riko[async]` |
| `async-anyio` | `anyio`, `httpx` | `pip install riko[async-anyio]` |

In `setup.py`:

```python
extras_require={
    "xml": xml_require,
    "async": async_require,
    "async-anyio": anyio_require,
    "develop": dev_requirements,
}
```

---

## Testing

### Twisted Tests

After the `async`/`await` conversion, Twisted tests use `defer.ensureDeferred` at the
entry point instead of the `@coroutine` decorator. See [ASYNC_AWAIT_CONVERSION.md](ASYNC_AWAIT_CONVERSION.md#testing) for details.

Existing tests continue to work when `RIKO_ASYNC_BACKEND` is unset or set to `"twisted"`.

### anyio Tests

New tests for the anyio backend use `pytest-anyio`:

```sh
pip install pytest-anyio
```

```python
import pytest
from riko.collections import AsyncPipe

@pytest.mark.anyio
async def test_async_pipe_anyio():
    result = await AsyncPipe('fetchdata', conf=fconf).count().list
    assert result == [{'count': 169}]
```

Run tests against a specific backend:

```sh
RIKO_ASYNC_BACKEND=anyio pytest tests/
RIKO_ASYNC_BACKEND=twisted pytest tests/
```

---

## Migration Guide

### For Library Users

**Twisted (after async/await conversion):**

```python
from twisted.internet import defer, task
from riko.bado.mock import FakeReactor
from riko.collections import AsyncPipe

async def run(reactor):
    result = await AsyncPipe('fetch', conf=conf).list
    print(result)

def main(reactor):
    return defer.ensureDeferred(run(reactor))

task.react(main, _reactor=FakeReactor())
```

**anyio:**

```python
import os
os.environ['RIKO_ASYNC_BACKEND'] = 'anyio'

import anyio
from riko.collections import AsyncPipe

async def run():
    result = await AsyncPipe('fetch', conf=conf).list
    print(result)

anyio.run(run)
```

The coroutine body is identical. Only the entry point differs.

### For Pipe Authors

After the `async`/`await` conversion, pipe functions are already native `async def`. No
further changes are needed for anyio compatibility — the same function works with both
backends:

```python
async def async_pipe(item, **kwargs):
    result = await some_async_op(item)
    return {'value': result}
```

The `coroutine` decorator in `riko/bado/__init__.py` is a no-op for both backends, so
wrapping `async def` functions with it is harmless and backwards-compatible.

### Backward Compatibility

- The default backend remains `"twisted"` when Twisted is installed
- The `backend`, `_issync`, and `_isasync` variables remain available in `riko.bado`
- `coroutine` and `return_value` remain importable from `riko.bado` — they are now no-ops for all backends
- No public API changes are required for Twisted users

### Known Limitations

- `etree2dict` and `xml2etree` under anyio use `lxml` or `xml.etree` instead of Twisted's `microdom`. Output may differ slightly for malformed XML.
- `FakeReactor` under anyio does not simulate time advancement — use anyio's `move_on_after` / `fail_after` for timeout testing instead.
- The `connections` parameter in `async_map` under anyio uses a semaphore rather than Twisted's `Cooperator`, which changes scheduling order (but not correctness).
