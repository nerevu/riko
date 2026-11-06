# DotDict parsing gameplan

It reduces accidental interpretation because only two-element sequences qualify. But
this is still structurally ambiguous:

```python
["active", "text"]
```

could be:

* a Riko typed value sequence;
* an ordinary two-value business list.

So the guard reduces collisions but does not eliminate them.

The risk depends on where it is called:

```python
parse_conf(conf=...)
```

is a safe context because the caller has declared the object to be configuration.

```python
DotDict(record).get(...)
```

is still risky because the caller may be reading arbitrary business data.

## Recommended implementation

Keep the sequence recognition, but make it precise and invoke it only during
configuration parsing:

```python
type ValueSeq = tuple[BasicValue, BasicValue]


def parse_value_seq(val: object) -> ValueSeq | None:
    if not isinstance(val, (list, tuple)) or len(val) != 2:
        return None

    first, second = val

    if not (isinstance(first, BasicValueType) and isinstance(second, BasicValueType)):
        return None

    return first, second
```

Then:

```python
def parse_conf(...):
    if value_seq := parse_value_seq(conf):
        ...
```

Today's stand-ins are `is_value_seq` and `is_mapping_seq` in `riko/base/_guards.py`,
whose only consumer is `riko/parsing/_dotdict.py`. Their names say "generic", but
`is_value_seq` narrows to the typed-value sequence. When `parse_value_seq` lands, they
go with it into configuration parsing (or are deleted), rather than staying in the
generic guard module.

## Is expressing types in plain text valuable enough?

Yes, as a configuration interchange format.

No, as an implicit interpretation rule for arbitrary DotDict values.

The best design is:

* Keep the typed-value representation
* Move its interpretation to configuration parsing
* Make ordinary DotDict access literal

## Recommended boundary

Scheduled as R4L in [implementation-sequence.md](implementation-sequence.md) (after
M1, before R4E; 2026-11-05).

DotDict should handle:

* nested paths
* case-insensitive keys
* raw retrieval
* defaults
* ordinary mapping behavior

parse_conf() should handle:

* typed values
* terminal references
* subkeys
* casting
* dynamic configuration
* configuration-specific sentinels

Naming: the helpers that move here (`resolve_sentinel`, `is_sentinel`, the `Sentinel`
TypedDict and `SentinelValue` key) implement *terminal references*, not sentinels; name
them `resolve_terminal`, `is_terminal_ref`, and `TerminalRef` when they move, leaving
"sentinel" to true sentinels such as `MISSING`. `is_sentinel`, `Sentinel`, and
`SentinelValue` currently sit in `riko/base/_sentinels.py`, which moved whole to `base`
on 2026-10-23 (`dependency-layers.md`), and `resolve_sentinel` is in
`riko/parsing/_dotdict.py`. The move takes the three out of `base`, and `MISSING` and
`StreamState` stay there. `is_sentinel` depends on the caller's terminal names, so it
moves with the code that interprets terminal references, not with a generic guard
module.

Measured 2026-10-15 (no owner before this phase): `gen_dict` resolves a nested mapping
through `resolve_sentinel(v, v)` (`riko/parsing/_dotdict.py`), which returns a plain
`dict`, so every nesting level is re-wrapped in a fresh `DotDict` on the way back out:
`asdict()` on a 20-key item builds 71 `DotDict`s (down from 110 before
`DotDict.__contains__` answered from the store). Fold the wrap into one pass when
`resolve_sentinel` moves here; a strict xfail cannot probe a construction count, so
there is no tripwire.

Typing (2026-10-27 `Any`/`cast` triage): `DotDict[VT]` declares no element type for a
nested mapping, so nine casts in `riko/parsing/_dotdict.py` paper over it
(`__setitem__`/`delete` store plain `dict`s in `VT` slots, and the reducers'
`cast("Self", ...)` is false at runtime: the stored value is a `dict`, not a `DotDict`).
A recursive value type (values `VT | DotDict[VT]`) removes them; land it with the
`resolve_sentinel` move above, since both reshape how nested levels are stored.

Measured 2026-10-20 (triage of the conf-parse memoization removal): the same churn makes
`resolve_conf` (`riko/parsing/config.py`) cost 72 µs for a three-field typed rule conf,
with 164 `is_mapping` checks per parse (`dictize` → `asdict` → `gen_dict` at every
level). A dynamic conf pays it per item (198 µs per item through `regex`), and it is the
larger share of a per-call direct `pipe()` (R4E note in implementation-sequence).
Folding the wrap into one pass is the lever for every path at once.

Conceptually:

```python
raw = DotDict(conf).get_raw("URL")
url = parse_conf(item, raw)
```

or simply:

```python
url = parse_conf(item, conf["URL"])
```

Business data remains literal:

```python
item = DotDict({"type": "currency", "value": 100})

assert item.get("type") == "currency"
assert item.get("value") == 100
```

Configuration is interpreted explicitly:

```python
conf = {"type": "url", "value": "example.com/feed"}

assert parse_conf(conf=conf) == "http://example.com/feed"
```

## Practical migration without breaking legacy pipelines

You do not need to remove the current behavior immediately.

### Phase 1: distinguish raw and configuration access

Add or formalize a raw path:

```python
DotDict.get_raw(...)
```

or:

```python
DotDict.get(..., parse=False)
```

Then make configuration code explicitly request parsing.

I prefer a separate raw method over a boolean flag because call sites are clearer:

```python
record.get_raw("value")
```

versus:

```python
record.get("value", parse=False)
```

### Phase 2: move typed parsing into parse_conf

Replace internal calls where DotDict.get() is being used to interpret configuration
with:

```python
parse_conf(item, conf)
```

Keep legacy behavior temporarily, but emit a warning only when ambiguous typed mappings
are encountered outside known configuration paths.

### Phase 3: make DotDict literal by default

After internal call sites and tests are converted:

```python
DotDict.get()
```

returns stored data.

```python
parse_conf()
```

interprets Riko configuration.

### Phase 4: optionally retain compatibility mode

For loading old Yahoo Pipes definitions:

```python
DotDict(..., config_mode=True)
```

or preferably at the workflow boundary:

```python
migrate_v1_to_v2(..., legacy_typed_values=True)
```

This keeps compatibility scoped to migrated `PipeDef`s (pipe definitions) rather than
spreading it across all runtime data.

---

## Connector configuration implication

The same boundary applies to promoted source and protocol adapters:

* connector configuration is parsed explicitly before execution;
* response records, email bodies, API payloads, database rows, and broker messages
  remain literal business data;
* a two-element list received from an external system is never interpreted as a typed
  Riko value merely because it resembles legacy configuration syntax;
* credential references and URI options use typed parsed configuration objects;
* compatibility parsing is limited to migrated serialized `PipeDef`s.

This requirement is especially important for JSON, CKAN, Prometheus, OpenAPI, and mail
payloads, where arbitrary arrays are normal data.

### Known instance: typed-value-shaped business data on module output

Triaged 2026-10-14. Feed entries carry fields shaped like a typed value, e.g.
feedparser's `summary_detail = {"type": "text/html", "value": "<b>hi</b>"}`. Today
`DotDict` read paths (`[]`, `get`, `asdict`) treat that as configuration and collapse it
to `"<b>hi</b>"`, so any processor run over the entry rewrites the field on output,
whether or not it touches it. The "literal DotDict access" boundary above fixes this;
until it lands, the strict-xfail tripwire
`TestDotDict::test_typed_value_shaped_business_data_reads_literally` in
`tests/internal/test_values.py` pins the collapse. (A nested `DotDict` write does not
re-read sibling fields, so a write is not a second trigger.)

### Known instance: keys made only of dots alias the empty key

Triaged 2026-10-31. `parse_key` strips trailing dots, so `"."` and `".."` parse to
`[""]` and `"a."` to `["a"]`. `d["."] = 5` stores a literal `"."` key that `d["."]` then
cannot read (`KeyError: ''`), `DotDict({"": 1}).get(".")` returns `1`, and `update`'s
subkey-precedence skip turns `"."` into a skip of `""`, so `DotDict({"": 1, ".": 2})`
drops the `""` key. `parse_item_key` reads only the exact empty string `""` literally.
The literal-access boundary above owns the key grammar; until it lands, the strict-xfail
tripwire `TestDotDict::test_dot_only_key_keeps_the_empty_key` in
`tests/internal/test_values.py` pins the drop.

### Known instance: a path past a scalar returns the scalar

Triaged 2026-10-31. `DotDict({"a": {"b": 1}}).get("a.b.z")` returns `1`: `_parse_value`
returns any non-`None` value for a leftover key instead of the default, so a path that
runs past a scalar reads as the scalar. Streamed JSON in `any2dict` reports the same
path as missing; both branches yield no records, so only the warning differs. The
literal-access boundary above owns it; until it lands, the strict-xfail tripwire
`TestDotDict::test_get_does_not_read_through_a_scalar` in
`tests/internal/test_values.py` pins it.

### Known instance: keys that differ only in case resolve to different duplicates

Triaged 2026-11-01. `DotDict` lowercases keys as it builds its store, so of two keys
that differ only in case the last one wins, as in Python's `dict`; streamed JSON in
`any2dict` matches the first `map_key` event and cannot see a later duplicate without
buffering the whole object. The two branches therefore read `{"X": …, "x": …}`
differently. Accepted as a documented difference: the characterization rows
`TestAny2dict::test_case_duplicate_keys_pick_a_branch_specific_value` in
`tests/internal/test_values.py` pin each branch's current pick so a change in either
shows up. Exact duplicate keys in fetched JSON (`any2dict`, `cast` with `JSON`,
`exchangerate`) keep the last value on both branches, as `json.loads` does; only
workflow documents reject them (audit 2026-11-01, accepted: the streamed branch cannot
see a later duplicate without buffering the object).

### Known instance: a numeric-string key reads as a sequence index

Triaged 2026-11-03 (repo audit). `DotDict.get` runs `int(k)` on every path segment, so a
key such as `"2020"` is taken as a sequence index: `DotDict({"2020": "x"}).get("2020")`
returns `None` while `["2020"]` returns `"x"`. Every module that reads a field through
`get` then sees the field as missing: `rename` deletes it and never re-adds it, `uniq`
keeps only the first item, `filter` and `subelement` yield nothing, `sort` is a no-op.
The literal-access boundary above owns the key grammar; until it lands, the strict-xfail
tripwire `TestDotDict::test_numeric_string_key_reads_literally` in
`tests/internal/test_values.py` pins the miss.

### Known instance: data-derived keys containing dots nest on module output

Triaged 2026-11-05 (GitHub issue #60). Module output is stored through `DotDict`, which
parses `.` in a key as a path, so a key built from a field *value* nests wherever the
value holds a dot: `count` with `count_key: "title"` over `"riko pt. 1"` yields
`{"riko pt": {" 1": 1}}`. Static, author-written keys are unaffected. The literal-access
boundary above owns the key grammar, including how a module writes a literal key; until
it lands, the strict-xfail tripwire
`tests/public/test_modules.py::TestCount::test_count_key_values_containing_dots_stay_literal`
pins the nesting. PR #63's local repair (a `set_literal` write plus a literal-first
`__getitem__`) was declined because it changes every `DotDict` read ahead of this
boundary.
