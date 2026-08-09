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
* source fields remain unless a later `dropfields` stage removes them;
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
after any coalesce stage that consumes staging columns.

## 6. Existing modules

`regex` remains the replacement module for solicitation-ID normalization. `rename` remains
field renaming only. Their docs gain cross-references but no new semantics.

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
```

## 12. Definition of done

1. Core transformation modules are dependency-free.
2. Deletion is not hidden in rename semantics.
3. Serialized configuration cannot invoke arbitrary callables.
4. Missing-value behavior is explicit and tested.
5. Optional enrichments fail clearly when unavailable.
6. Stateful enrichment is bounded and reports its scope.
7. Record and batch implementations share fixtures.
