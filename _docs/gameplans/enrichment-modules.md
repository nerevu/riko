# Authoritative Riko Record and Enrichment Module Gameplan

## 1. Mission

Promote recurring record transformations into precise named modules and isolate optional,
domain-specific enrichment algorithms from Riko core.

This plan incorporates Shelf milestones 7, 13.6, and 13.7.

## 2. Package boundary

```text
riko core modules
    coalesce
    strtransform
    dropfields
    existing regex and rename

riko-enrichment
    simhash or other near-duplicate detection
    contact extraction
```

A module enters core only when it is dependency-free, broadly useful, deterministic, and
has clear record semantics.

## 3. `coalesce`

```python
flow.coalesce(
    conf={
        "target": "client_email",
        "sources": [
            "client_email",
            "client_email_1_drop",
            "client_email_2_drop",
        ],
        "missing": ["null", "nan", "empty"],
    }
)
```

Rules:

* source order is significant;
* target may be included as the first source;
* missing-value policy is explicit;
* false, zero, and empty containers are not missing unless configured;
* source fields remain unless a later `dropfields` pipe removes them;
* output cardinality is one record per input record.

Do not rely solely on `value != value`; use a tested scalar-missing helper with optional
adapters for frame-library scalar types.

## 4. `strtransform`

One module owns a bounded, enumerated set of string operations:

```python
flow.strtransform(
    conf={
        "field": "client_email",
        "operations": [
            {"name": "strip"},
            {"name": "lower"},
            {"name": "split", "pattern": ";", "index": 0},
        ],
    }
)
```

Initial operations:

```text
strip
lower
upper
casefold
replace
regex_replace
split/select
normalize_whitespace
```

No arbitrary method names or callable imports are accepted from serialized configuration.

## 5. `dropfields`

```python
flow.dropfields(
    conf={
        "fields": ["temporary"],
        "patterns": [".*_drop$", ".*_additional$"],
        "missing": "ignore",
    }
)
```

This replaces the Shelf proposal to overload `rename` for deletion. Field removal occurs
after any coalesce pipe that consumes staging columns.

## 6. Existing modules

`regex` remains the replacement module for solicitation-ID normalization. `rename` remains
field renaming only. Their docs gain cross-references but no new semantics.

## 6b. `geolocate` — retire the stub lookups

Three of `geolocate`'s four `type` values return **fixed placeholder data**, which
`riko/cast.py` makes plain:

```python
def lookup_street_address(_: str) -> Location:   # argument ignored
def lookup_ip_address(_: str) -> IPAddress:      # argument ignored
```

Measured across varied inputs:

| `type` | Behavior |
|---|---|
| `currency` | **Real** — resolves via `CURRENCY_CODES`. |
| `street_address` | Canned. Any input returns the same US record (`"state"`, `"county"`, `"city"`, `"street"`, postal `"61605"`, lat/lon `0.0`). |
| `ip_address` | Canned. Same fixed US record for `8.8.8.8`, `1.1.1.1`, or `not-an-ip`. |
| `coordinates` | Half real — echoes the supplied lat/lon, but `country` is canned, so Tokyo and Sydney both report "United States". |

This is worse than a missing feature: the pipe *succeeds* and yields a plausible
record, so a pipeline built on it looks correct and is silently wrong. The
module's doctest asserted `country == "United States"` for a US street address —
which passed for **any** input, including gibberish.

Decide per lookup, and do not leave the middle ground:

* **`currency`** — keep. It is the only one that works, and it needs no
  dependency.
* **`coordinates`** — either drop the canned `country` (returning just the
  parsed lat/lon is honest and still useful) or resolve it properly via an
  offline dataset. Echoing coordinates back is a legitimate normalization step;
  the fabricated country is not.
* **`street_address` / `ip_address`** — remove, or move behind an optional
  extra that raises when the backing data is absent (§12.5: *"Optional
  enrichments fail clearly when unavailable"*). Real geocoding means a service
  or a bundled dataset — either way it belongs with the optional enrichments in
  §8/§9, not silently inside a core module.

Removing a `type` value is a breaking change to the public conf surface, so it
is SemVer-gated. Until then the docstrings carry a `Warning:` naming which
lookups are real.

## 7. Composition

Do not add public `applys()` or `transform_csv()` abstractions. Users compose named modules
through normal fluent chaining or serialized pipeline definitions. The compiler may fuse
compatible record transforms later, but fusion must preserve events, errors, ordering,
and module-level observability.

## 8. Near-duplicate detection

Near-duplicate detection is stateful and optional.

```python
flow.simhash(
    conf={
        "field": "title",
        "threshold": 0.85,
        "action": "drop",
        "scope": "execution",
        "max_entries": 100_000,
    }
)
```

Requirements:

* algorithm and package version are recorded in metadata;
* memory is bounded;
* collision and threshold behavior are tested;
* `flag` output identifies a stable matched record ID, not only `_duplicate=True`;
* distributed/global deduplication requires an explicit external index;
* exact `uniq` remains a separate deterministic operator.

The first adapter may use Simhash, but the public module contract must not depend on one
third-party library's object types.

## 9. Contact extraction

Contact extraction is optional enrichment with structured output:

```python
flow.contactextract(
    conf={
        "field": "content",
        "assign": "contacts",
        "types": ["email", "phone"],
    }
)
```

Missing optional dependencies raise a clear module-unavailable error; they do not silently
return the unchanged item. Extracted values include confidence or provenance when the
underlying implementation provides it. Address extraction is locale-sensitive and should
not be enabled by default.

## 10. Batch behavior

Record implementations land first. Batch implementations may use Arrow or Narwhals
expressions after the batch contract is stable. Record and batch paths must pass the same
golden fixtures.

## 11. Phases

```text
E0  Missing-value and string-operation contracts
E1  coalesce, strtransform, and dropfields record modules
E2  generated fluent stubs and documentation
E3  optional near-duplicate package
E4  optional contact-extraction package
E5  batch implementations and parity benchmarks
E6  geolocate stub retirement (SemVer-gated; see 6b)
```

## 12. Definition of done

1. Core transformation modules are dependency-free.
2. Deletion is not hidden in rename semantics.
3. Serialized configuration cannot invoke arbitrary callables.
4. Missing-value behavior is explicit and tested.
5. Optional enrichments fail clearly when unavailable.
6. Stateful enrichment is bounded and reports its scope.
7. Record and batch implementations share fixtures.
