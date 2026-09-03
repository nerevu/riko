# Cache and replay gameplan

## 1. Mission

Define Riko's explicit pipeline-result replay contract without creating a second persistence or cache
backend hierarchy inside Core.

This plan owns `Pipeline.cache()`, `CacheNode` runtime semantics, cache identity, fill/replay,
invalidation, and the Riko-to-Mezmoize boundary. It consumes:

- canonical node/Workflow v2 structure from `extensibility.md`;
- value freezing/fingerprints and private execution lifetime from `execution-semantics.md`;
- Resource ownership from `execution-semantics.md`;
- implementation ordering from `implementation-sequence.md`.

It does **not** own `StateStore`/checkpoint recovery, HTTP/provider transport caching, or generic
materialization semantics outside an explicit cache boundary.

## 2. Architecture

Riko already depends on `reubano/mezmorize`; use it rather than reimplementing cache stores:

```text
Pipeline.cache()
    -> CacheNode
    -> private Riko Mezmoize shim
    -> Mezmoize Cache
    -> CacheLib/backend
```

There is no Riko `CacheStore` hierarchy. Generally useful backend/cache behavior should move
upstream to Mezmoize rather than being duplicated in Riko.

The private integration module may follow the same pattern as `_objectify.py` / `_reencode.py`, for
example `_mezmorize.py`.

## 3. Definition versus contents

The Pipeline/CacheNode owns **semantic cache identity and policy**. Mutable cached contents belong to
the cache service/resource.

Consequences:

- Pipeline immutability does not imply cached contents are immutable;
- cache contents are never serialized into Workflow v2;
- the cache backend/resource is infrastructure, not the dataflow value itself;
- seekability/replayability of a source is distinct from caching;
- temporary buffering used by an operator is not cross-execution caching;
- provider/HTTP transport caches do not satisfy `Pipeline.cache()` semantics.

## 4. Default cache

Plain:

```python
cached = flow.cache()
```

uses a built-in bounded process-local Mezmoize `SimpleCache` resource.

Default contract:

```python
DEFAULT_CACHE_SIZE = ByteSize(mebibytes=64)
```

with private chunk size:

```python
_CACHE_CHUNK_SIZE = ByteSize(kibibytes=256)
```

The default has no semantic TTL (`timeout=0`/no expiry at the backend). Capacity eviction is an
ordinary cache miss, not a correctness failure or retention guarantee.

`ByteSize` is the public size value type. It subclasses `int`, supports decimal SI and binary IEC
constructors, and canonicalizes to bytes.

Capacity belongs to the configured cache Resource/backend, not to a `.cache(limit=...)` option.

## 5. Explicit cache resource

`CacheNode` declares the normal Resource slot:

```text
cache
```

If unbound, execution supplies the built-in process-local Mezmoize resource. An explicitly bound
Resource may provide persistent/shared behavior through any Mezmoize/CacheLib-supported backend,
including suitable filesystem, Redis, or Memcached configurations.

Riko does not infer persistent/shared cache selection from environment variables.

## 6. TTL

Python API:

```python
ttl: datetime.timedelta | None = None
```

`None` means no semantic expiry. Workflow v2 canonical form stores TTL as integer milliseconds and
rejects durations that cannot be represented exactly in milliseconds.

No TTL does **not** promise retention: bounded backends may evict entries.

## 7. Fill and replay semantics

A cache fill streams values downstream while staging them, but publishes a replayable entry only
after the upstream traversal completes successfully.

```text
upstream item
    -> downstream immediately
    -> staged cache chunks

successful complete traversal
    -> publish manifest

error / cancellation / early consumer exit
    -> discard incomplete generation
```

An incomplete traversal must never become a cache hit.

### 7.1 Chunk + manifest protocol

Cache values are stored in bounded chunks plus one manifest. The manifest is the publication point:
it becomes visible only after every referenced chunk exists.

On replay:

- valid manifest + all chunks -> hit;
- missing/corrupt referenced chunk -> miss;
- stale manifest/chunks are cleaned up best-effort;
- incomplete unpublished generations are unreachable.

This prevents a backend that stores individual values atomically from exposing a partially filled
logical stream as a valid cache entry.

## 8. Concurrency

Concurrent executions filling the same semantic cache key may both proceed. Each fill uses an
isolated generation; whichever complete generation becomes current may serve later reads.

There is no initial single-flight/coalescing requirement. Duplicate computation is acceptable;
partial or cross-generation replay is not.

## 9. Invalidation

A cached Pipeline view supports:

```python
cached.invalidate()
```

Invalidation rotates the semantic cache generation/namespace. Old entries immediately become
unreachable without requiring eager deletion or repopulation. Best-effort backend cleanup may happen
later.

Invalidation does not execute the upstream Pipeline.

## 10. Backend failure

Cache infrastructure is an optimization boundary, not a reason to fail otherwise valid dataflow.

If cache get/set/delete/manifest operations fail:

1. emit a diagnostic through the execution `EventSink`;
2. bypass the cache for the remainder of the current execution;
3. continue normal upstream/downstream processing;
4. retry cache infrastructure normally on the next independent execution.

An **upstream/dataflow failure** is not a cache failure and still fails according to normal execution
policy.

## 11. Identity

Cache keys use the common canonical freezing/fingerprint system from `execution-semantics.md`. Do not
invent cache-only serializers/hashes.

Automatic semantic fingerprints are appropriate for process-local default caching. Where a shared or
persistent cache must remain correct across deploy/dependency changes, explicit node/resource
`version=` follows the same durability guidance as other identity-sensitive boundaries.

The cache backend implementation itself is infrastructure and does not change the logical output of
the node.

## 12. Non-goals

Initial cache work does not add:

- a Riko cache-store class hierarchy;
- hidden memoization of every node;
- transparent source replay;
- a distributed locking/single-flight protocol;
- a retention guarantee when TTL is absent;
- cache-backed checkpoint/recovery semantics;
- environment-selected production cache backends;
- generic HTTP/provider response caching.

## 13. Testing

Required contracts:

1. first complete traversal fills and second execution replays without consuming upstream;
2. early close/cancellation/failure never publishes an incomplete entry;
3. missing chunk degrades to miss and stale cleanup;
4. process-local default respects bounded capacity behavior;
5. explicit TTL expires semantically; no TTL is distinct from retention guarantee;
6. concurrent fills never cross-read partial generations;
7. invalidate rotates generation without eager refill;
8. backend failure emits one useful diagnostic and bypasses cache for that execution;
9. next execution retries a previously failed backend;
10. upstream failure still propagates;
11. sync and async execution observe the same logical replay behavior;
12. Workflow v2 round-trips CacheNode semantic policy but never cache contents/live backend handles.

## 14. Definition of done

`Pipeline.cache()` is an explicit, deterministic replay boundary backed through Mezmoize, incomplete
fills are unobservable, invalidation is generation-based, backend failures are safely bypassed, and
no competing cache persistence abstraction exists in Core.
