# Entity resolution gameplan

> **Provenance.** Raised by the AI/ML strategy assessment in
> [`../research/ai-ml-strategy.md`](../research/ai-ml-strategy.md), which found linkage
> touched by several plans but owned by none.

## 1. Mission

Give Riko one generic record-linkage contract: decide whether records from one or more
sources describe the same real-world entity, and say why, without auto-merging anything
the evidence does not support.

Target shape:

```text
records from one or more sources
→ bounded candidate generation (blocking)
→ layered comparison: exact → normalized → fuzzy → probabilistic → semantic
→ scored, explained MatchResult per candidate pair/set
→ accept above threshold / manual review in the ambiguous band / reject below
→ optional cross-run identity map persisted through StateStore
```

## 2. Package boundary and ownership

```text
riko core
    match-result contract, layer vocabulary, thresholds, review routing
    exact and normalized deterministic layers (dependency-free)

optional adapters (extras or an ecosystem package)
    fuzzy string similarity adapter
    probabilistic Fellegi–Sunter adapter
    MinHash/LSH blocking adapter
```

The first fuzzy adapter is RapidFuzz [1] and the first probabilistic adapter is Splink
[2]. Core stays dependency-free. The public contract is never tied to one library's
object types; adapters translate to and from it.

This plan owns:

* the match layers and their order;
* the scored, explained match result;
* review thresholds and the accept/review/reject bands;
* blocking/candidate-generation bounds;
* the linkage adapter boundary;
* the cross-run identity map payload.

This plan does **not** own:

* exact dedupe — `uniq` and `feed-monitoring.md` M5 keep it;
* the near-duplicate `simhash` module — `enrichment-modules.md` § 8 keeps the module; it
  is a single-field, single-stream specialization and may report its match through
  this plan's result shape when it flags a duplicate;
* domain match precedence and identity fields — `monthly-dashboard.md` § 6
  (`DeviceIdentity` precedence) is a consumer that specializes the layer order;
* embeddings and retrieval — `ai-inference.md` owns them; the semantic layer consumes
  riko-ai retrieval adapters;
* canonical identity encoding — `riko/coercion/_canonical.py`, per
  `execution-semantics.md`;
* state persistence — `FeedState`/`StateStore` from `execution-semantics.md`.

## 3. Match layers

Layers run in order; a pair settled by an earlier layer never reaches a later one.

```text
1. exact keys              stable source IDs, exact external identifiers
2. normalized deterministic  case/whitespace/punctuation/format-normalized fields
3. fuzzy string similarity   Levenshtein, Jaro-Winkler (adapter)
4. probabilistic             Fellegi–Sunter m/u weights (adapter)
5. semantic (optional)       embedding similarity via riko-ai retrieval adapters
```

Layers 1–2 are deterministic and built in. Layers 3–5 are optional adapters declared as
`Resource`s; a missing adapter fails clearly at prepare time. A consumer may select or
reorder layers but must name them; there is no implicit "fuzzy" default.

## 4. Match results

Every comparison yields a scored, explained result:

```python
class MatchResult(TypedDict):
    records: list[str]  # matched stable record IDs
    layer: str
    algorithm: str
    package: str | None
    package_version: str | None
    score: float
    threshold: float
    decision: Literal["match", "review", "non_match"]
    reason: str
```

Rules:

* a result always names its algorithm, package version, threshold, and the stable
  record IDs it matched — never only a boolean flag;
* scores are comparable only within one layer and algorithm;
* deterministic layers report `score=1.0` with a reason naming the matched key.

## 5. Review, never silent merge

Thresholds define three bands: accept, review, and reject. A result in the review band,
or any ambiguous result where one record matches several candidates, goes to manual
review and is never merged automatically. This generalizes the advisory-only rule in
`highergov-feed.md` (fuzzy similarity never remaps automatically) and the `ambiguous`
count in `monthly-dashboard.md` § 6.

Merging is a separate, explicit step over accepted results. A destructive merge in a
provider service is an Action/write under `effects.md`.

## 6. Blocking and candidate generation

Pairwise comparison is quadratic, so candidate generation is explicit and bounded:

* blocking keys (exact or normalized field prefixes) partition the input;
* MinHash/LSH blocking is an optional adapter with declared band/row parameters;
* every blocker declares `max_candidates`; exceeding it fails or reports truncation,
  never silently drops pairs;
* blocking choices and candidate counts are recorded in metadata.

## 7. Cross-run identity maps

A linkage that must stay stable across executions persists an identity map (stable
record ID → cluster ID) as a versioned, typed `FeedState` payload under the stateful
owner's `StateKey`, reusing `StateStore`, CAS, and `.checkpoint()`. There is no second
store.

Cluster IDs and record fingerprints come from the canonical encoding layer
(`canonicalize`/`digest` in `riko/coercion/_canonical.py`), never Python's `hash()`.

## 8. Non-goals

Do not add:

* automatic merging of review-band or ambiguous results;
* a vague similarity score without a documented algorithm and threshold;
* embedding models, vector stores, or retrieval indexes (riko-ai owns them);
* an unbounded all-pairs comparison;
* a linkage-specific state store or identity encoder;
* a hard dependency on RapidFuzz, Splink, or any numerical library in core.

## 9. Testing

Required tests include:

1. exact and normalized layers are deterministic and dependency-free;
2. each result names algorithm, package version, threshold, and matched record IDs;
3. a pair settled by an earlier layer never reaches a later one;
4. review-band and ambiguous results are routed to review, never merged;
5. blocking respects `max_candidates` and reports truncation;
6. a cross-run identity map round-trips through a persistent `StateStore` and resumes;
7. cluster IDs are stable across processes (canonical encoding, not `hash()`);
8. a missing optional adapter fails clearly at prepare time;
9. adapter results satisfy the same result contract as built-in layers.

## 10. Phases

```text
ER0  MatchResult contract + accept/review/reject bands
ER1  exact + normalized deterministic layers
ER2  blocking/candidate generation with bounds
ER3  cross-run identity map through StateStore
ER4  fuzzy string similarity adapter (RapidFuzz)
ER5  probabilistic Fellegi–Sunter adapter (Splink)
ER6  semantic layer over riko-ai retrieval adapters
```

## 11. Definition of done

1. One generic linkage contract exists; domain plans specialize it instead of
   restating it.
2. Every match is scored and explained with algorithm, version, threshold, and record
   IDs.
3. Ambiguous and below-threshold matches go to review, never auto-merge.
4. Candidate generation is bounded and inspectable.
5. Cross-run identity reuses `StateStore` and canonical encoding.
6. Core stays dependency-free; fuzzy, probabilistic, and semantic layers are optional
   adapters behind a library-neutral contract.

[1]: https://github.com/rapidfuzz/RapidFuzz "RapidFuzz"
[2]: https://github.com/moj-analytical-services/splink "Splink"
