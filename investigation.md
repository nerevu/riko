# Investigation: `print()` vs `# print()` at `receive.py:110`

## Summary

The discrepancy is caused by **shared mutable global state** in `riko/utils.py` that
persists across the entire pytest session. The `print()` at line 110 is a symptom
indicator, not the direct cause — it acts as a fault-injection that changes the failure
point of an **earlier** doctest, which in turn changes how much contaminating state
accumulates before `send.py:pipe` runs.

---

## Relevant globals (riko/utils.py)

```python
_registry   = {}      # name → generator coroutine
_collector  = {}      # name → deque of collected items
_item_queue = deque() # (name, item) pairs pending pubsub delivery
```

These are **never reset** between pytest tests.

---

## Doctest execution order (full suite)

```
1. tests/test_collections.py::TestCollections::test_send      (uses "receiver", "printer")
2. tests/test_collections.py::TestCollections::test_receive   (uses "receiver")
   ...
3. riko/modules/receive.py::riko.modules.receive              (receiver1)
4. riko/modules/receive.py::riko.modules.receive.parser       (receiver2) ← FAILS at next(source)
5. riko/modules/receive.py::riko.modules.receive.pipe         (receiver3) ← behaviour depends on print()
6. riko/modules/send.py::riko.modules.send                    (receiver1)
7. riko/modules/send.py::riko.modules.send.parser             (receiver2)
8. riko/modules/send.py::riko.modules.send.pipe               (receiver3) ← THE FAILING TEST
```

---

## Why `next(source)` fails in earlier doctests

`send.py:parser` returns the **sender coroutine** (`gen`), not a data item.
`get_assignment(gen)` eagerly pulls two `next()` values from the coroutine, both of
which are `None` (the coroutine yields `None` on every iteration of `while True: _item = yield`).
So `next(source)` always returns `None`, causing all `receive.py` and `send.py` doctests
that call `next(source)` to **fail**.

This is the root bug, but it's not what the user is investigating. The user is
investigating why two states of line 110 produce different failures in `send.py:pipe`.

---

## Trace: state entering `receive.py:pipe` (step #5 above)

After `receive.py:parser` fails at `next(source)`:

| Key                       | Value                                     |
|---------------------------|-------------------------------------------|
| `_registry['receiver2']`  | receiver2 coroutine (at `item = yield`)   |
| `_collector['receiver2']` | `deque([{'x': 0}])`                       |
| `_item_queue`             | `[('receiver2', None), ('receiver2', None)]` |

---

## Case A — `print()` ACTIVE at line 110

### receive.py:pipe step 2 — `next(pipe_target)`

`processor.wrapper` starts; calls `get_assignment(parser_gen)`:

1. `first_result = next(parser_gen)`:
   - Creates `receiver3` coroutine, primes via `actor`
   - `_collector['receiver3']` empty → `next(gen)` → appends `{"state": Stream.PENDING}`
   - while-loop: pops `{"state": PENDING}`, **`print()` fires → `<BLANKLINE>` to stdout**
   - yields `{"state": PENDING}` → `first_result = {"state": PENDING}`

2. `second_result = next(parser_gen)`:
   - while-loop: `_collector['receiver3']` empty → exits
   - `pubsub()` drains `_item_queue` (`receiver2` × 2 → appends `{"state": PENDING}` × 2 to `_collector['receiver2']`)
   - StopIteration

**Doctest captures stdout + return value:**
```
Got:
    <BLANKLINE>
    {'state': <Stream.PENDING: 1>}
```
Expected `{'state': <Stream.PENDING: 1>}` → **MISMATCH → doctest ABORTS here**.

Steps 3–5 of `receive.py:pipe` are never executed.

### State after receive.py:pipe ABORT (Case A)

| Key                       | Value                     |
|---------------------------|---------------------------|
| `_collector['receiver3']` | `deque([])`  ← **empty**  |
| `_item_queue`             | `[]`                      |

### send.py:pipe — `next(sd_target)` (Case A)

- `_collector['receiver3']` is **empty** → `next(gen)` is called
- `{"state": PENDING}` appended to collector
- while-loop runs: `print()` fires → **`<BLANKLINE>` to stdout**
- yields `{"state": PENDING}`

```
Got:
    <BLANKLINE>
    {'state': <Stream.PENDING: 1>}
```

---

## Case B — `# print()` COMMENTED at line 110

### receive.py:pipe step 2 — `next(pipe_target)`

Same as Case A, but **no `print()` fires**:

- `first_result = {"state": PENDING}` (no stdout)
- `second_result`: pubsub drains queue (receiver2 × 2)
- Doctest output: `{'state': <Stream.PENDING: 1>}` → **MATCHES → step 2 PASSES**

### receive.py:pipe step 4 — `next(pipe_source)`

`send.py:parser` runs, pubsub delivers `{'x': 0}` to `_collector['receiver3']`.
`get_assignment(sender_gen)` pulls two `None` values → `next(pipe_source)` returns `None`.
Expected `{'x': 0}` → **MISMATCH → doctest ABORTS here**.

(Steps 1–4 all ran; the side-effect of step 4 — populating `_collector['receiver3']` — already happened.)

### State after receive.py:pipe ABORT (Case B)

| Key                       | Value                                     |
|---------------------------|-------------------------------------------|
| `_collector['receiver3']` | `deque([{'x': 0}])` ← **non-empty!**      |
| `_item_queue`             | `[('receiver3', None), ('receiver3', None)]` |

### send.py:pipe — `next(sd_target)` (Case B)

- `_collector['receiver3']` is **non-empty** → `next(gen)` is **skipped**
- while-loop: pops `{'x': 0}`, **`# print()` does nothing** (commented), yields `{'x': 0}`
- `get_assignment`: `first_result = {'x': 0}`; `second_result` triggers `pubsub()` (processes 2 × `('receiver3', None)`)

```
Got:
    {'x': 0}
```

---

## Root cause summary

| Mechanism                    | Case A (print active)                                  | Case B (print commented)                               |
|------------------------------|--------------------------------------------------------|--------------------------------------------------------|
| `receive.py:pipe` abort point | Step 2 (`next(target)`) — blank line mismatch         | Step 4 (`next(source)`) — None vs {'x': 0}            |
| `_collector['receiver3']` at abort | **empty** (no sender ran)                       | **`[{'x': 0}]`** (sender side-effect occurred)        |
| `send.py:pipe` `next(target)` | `print()` fires → `<BLANKLINE>` + `{"state": PENDING}` | pops stale `{'x': 0}`, no print fires                |

**The `print()` changes _which_ doctest fails earlier**, which in turn changes _how much
contaminating state_ accumulates in `_collector['receiver3']` before `send.py:pipe` runs.

The blank line in Case A is produced by the **`print()` in `send.py:pipe`'s own
`next(target)` call** (since the collector is empty, `next(gen)` primes it and the
while-loop then executes `print()`).

The `{'x': 0}` in Case B is a **stale item** left in `_collector['receiver3']` by the
side-effect of `receive.py:pipe` step 4 (which executed before the abort).

---

## The actual bugs

1. **`send.py:parser` returns `stream = gen` (a coroutine that yields `None`)** instead
   of the original item. This makes `next(source)` return `None` everywhere, causing all
   send/receive doctests to fail at the `next(source)` step.

2. **Global state (`_registry`, `_collector`, `_item_queue`) is never reset** between
   pytest test items, so failures in early doctests contaminate later ones.

3. The `print()` at line 110 is **debug scaffolding** left in the code that happens to
   expose bug #2 by changing the failure point of `receive.py:pipe`.

---

## Recommended Fixes

### Fix 1 — `send.py:parser`: return the original item stream, not the sender coroutine

`parser` sets `stream = gen` (the sender coroutine). Every `next()` on that coroutine
returns `None` (the `yield` expression value in the `while True: _item = yield` loop),
so `next(source)` always yields `None` instead of the actual item.

The function should return `kwargs["stream"]` — the original item — unchanged, just as
it does in the `skip` branch.

```python
# Before (buggy)
send(name, item)
stream = gen
pubsub()
return stream

# After (fixed)
send(name, item)
pubsub()
stream = kwargs["stream"]
return stream
```

---

### Fix 2 — `riko/modules/__init__.py:processor.wrapper`: restore the polling loop

The current code replaces the pollable for-loop with a bare `yield from stream`. This
exhausts the parser generator on the first `next(target)` call, so every subsequent
`next(target)` raises `StopIteration`. The polling loop (now commented out) must be
restored so that `receive.py:parser` is re-invoked on each poll cycle and can drain any
items that arrived in `_collector[name]` since the previous call.

```python
# Before (broken — bare yield-from exhausts the generator immediately)
try:
    yield from stream
except StopIteration:
    return
# for s in stream:
#     state = s.get("state") if self.pollable and s else None
#     if state is not Stream.DONE:
#         yield s
# stream = _get_stream(_input, *parsed, combined=combined, **kwargs)
# if self.isasync:
#     return_value(stream)
# else:
#     yield from stream

# After (restored)
for s in stream:
    state = s.get("state") if self.pollable and s else None

    if state is not Stream.DONE:
        yield s

stream = _get_stream(_input, *parsed, combined=combined, **kwargs)

if self.isasync:
    return_value(stream)
else:
    yield from stream
```

`_get_stream` is a recursive generator already defined in `wrapper`'s closure; it
re-invokes `pipe` (i.e. `parser`) on each poll cycle, sleeping `interval` seconds
between retries until `Stream.DONE` is received.

---

### Fix 3 — `tests/conftest.py`: reset shared global state between pytest items

`_registry`, `_collector`, and `_item_queue` in `riko/utils.py` are module-level
globals that survive the entire pytest session. An autouse fixture that clears them
before (and after) every test item eliminates cross-doctest contamination.

```python
# tests/conftest.py
import pytest
from riko.utils import _registry, _collector, _item_queue


@pytest.fixture(autouse=True)
def reset_pubsub_state():
    _registry.clear()
    _collector.clear()
    _item_queue.clear()
    yield
    _registry.clear()
    _collector.clear()
    _item_queue.clear()
```

---

### Fix 4 — `receive.py:110`: remove the debug `# print()` line

Line 110 (`# print()`) is debug scaffolding with no functional purpose. Remove it.

```python
# Before
        while _collector[name]:
            item = _collector[name].popleft()
            # print()
            yield item

# After
        while _collector[name]:
            item = _collector[name].popleft()
            yield item
```

---

## Fix priority

| # | File | Change | Effect |
|---|------|--------|--------|
| 1 | `riko/modules/send.py` | `stream = kwargs["stream"]` instead of `stream = gen` | `next(source)` returns the actual item |
| 2 | `riko/modules/__init__.py` | Restore polling for-loop + `_get_stream` | Second (and subsequent) `next(target)` works |
| 3 | `tests/conftest.py` | Autouse fixture clearing globals | Eliminates cross-test state contamination |
| 4 | `riko/modules/receive.py` | Remove `# print()` at line 110 | Removes dead debug scaffolding |

Fixes 1 and 2 are required for the doctests to pass. Fix 3 is required for the test
suite to be deterministic (order-independent). Fix 4 is cosmetic cleanup.
