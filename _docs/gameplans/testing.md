# Test-suite layering gameplan

> **Scope:** owns **P13** ("public/typing/internal test split",
> [PHASE_CHECKLISTS.md](../PHASE_CHECKLISTS.md) § P13 tracker, [MILESTONES.md](../MILESTONES.md)
> "P13"). Establishes the durable *ownership* rule for the four test layers and the concrete
> fix/remove/consolidate work to get there. The `tests/typing/{valid,invalid}/` split that P13
> also introduces is tracked in MILESTONES; this gameplan owns the *pytest/doctest* layering.
>
> **Provenance.** Audited the full test surface at a `features`-branch working state,
> commit `5c33e05` (pytest then collected `tests`, `riko`, `README.rst`, and `docs`, with both
> Python-module and `*.rst` doctests enabled). One item is **already done**: the standalone
> `tests/public/test_fluent_discovery.py` was dropped as part of P9A and its coverage folded into
> `public/test_collections.py` (`TestModuleNameEnum`) and `public/test_modules.py` — where that
> file is named below, read it as "the discovery coverage that now lives in those two files."
> Everything else in the audit still maps onto the current tree.

## 1. The ownership rule (the durable principle)

Consolidate aggressively, but **not by chasing test count**. One test owner per contract:

> **Doctests** own documented happy paths. **Public tests** own API-boundary behavior and edge
> cases. **Internal tests** own generator mechanics, drift guards, and failure modes.
> **Functional tests** own cross-layer fixture and CLI integration.

Because pytest executes doctests in Python modules, `README.rst`, and `docs/*.rst`, the
README/FAQ already exercise string-based `SyncPipe` construction and `list_modules()` filtering —
so new tests do not re-prove those string paths. The biggest net improvement is **making each
layer have one clear job**, not shrinking the suite.

## 2. Highest-priority findings (fix before deciding redundancy)

These are real test bugs — coverage that looks stronger than it is. Fix them first.

1. **`tests/functional/test_basics.py` — `_load()`/`_aload()` discard `value`/`check`.** Both
   accept `value`/`check` but hard-code the defaults when delegating:
   ```python
   def _load(self, items, pipe_name, value=0, check=1):
       ...
       _check_results(pydeps, items, pipe_name, value=0, check=1)  # ignores args
   ```
   So `self._load(items, pipe_name, 25, 0)` never verifies `< 25`/`== 25` — it always verifies the
   default `> 0`. Same bug in `_aload()`. A large part of the legacy functional suite is weaker than
   it looks. **Fix this before pruning any pipeline tests.**
2. **`tests/functional/test_pipeline.py` is not a test module.** It contains a generated
   `pipe_testpipe1()` implementation and no `test_*` functions. **Remove or relocate** it to the
   generated-pipeline fixture area.
3. **Typed module-name behavior is tested in three places** — the (now-removed)
   `test_fluent_discovery.py`, `internal/test_codegen_names.py`, and `TestModuleNameEnum` in
   `public/test_collections.py`. `TestModuleNameEnum` already owns normalization, constructor
   normalization, enum/string equivalence, `|`, and `.pipe()`. Discovery tests should own
   **discovery**, not generic enum acceptance.
4. **`internal/test_loop.py` has an exact behavioral duplicate.**
   `test_loop_count_all_flattens_embedded_results` and `test_loop_level_field_selects_child_input`
   invoke the same `_tokenizer_loop(... count="all", emit=True)` and expect the same output. The
   latter does not isolate the `field` behavior its name claims — give the parent both `title` and
   another candidate field so choosing `field="title"` changes the result.
5. **One resolver precedence test is ineffective.** `test_runtime_registration_shadows_entry_point`
   uses the same `marker` callable for both the entry-point definition and the runtime
   registration, so it passes regardless of which wins. Use two distinguishable callables.

## 2b. Regression batch from the branch audit

The [correctness-audit register](correctness-audit.md#8-open-defect-register--features-branch-audit)
found 17 confirmed defects in the non-module runtime, none of which fails a happy-path
test today. The register owns the *fixes*; this section owns the *coverage*, because the
register's shape is a coverage verdict: finite lists, local fixtures and file paths are
well covered, while **iterator exhaustion, unbounded sources, falsey values, nested
objects, real HTTP behaviour, binary formats, and sync/async parity** are where every
row landed.

Each of these is a **regression** test in § 6's sense — write it against the current
tree, watch it fail, then fix. They belong to the layer that owns the unit under test
(§ 1), not to one new file:

| Test | Layer | Row |
|---|---|---|
| ~~`Fetch(url, memoize=False)` returns the full body and closes the response~~ — **landed** as `tests/internal/test_io.py` (threaded local server; a fixture file cannot reach this branch) | internal | R1 |
| ~~`p(assign="x")` preserves the constructor `conf`~~ — **moved** to the split's `public/test_pipeline.py` exit tests ([MILESTONES § split](../MILESTONES.md)); writing it against the doomed `PyPipe.__call__` only pins an API being deleted | public | R2 |
| ~~keyed `join(count(), finite_other)` yields a first result~~ — **landed** as `tests/public/test_pipe_implementations.py` (keyed **and** natural; asserts bounded consumption, since the operator wrapper reads one item ahead) | public | R3 |
| `async_pipe` (`send`) yields its first item before the source is exhausted | public | R4 |
| `compile_pipe` handles ids `"class"`, `"foo bar"`, `"foo.bar"`, `"1st"`, `"café"` | internal | R5 |
| an unsupported object **nested** in a dict/list arg bypasses `repr_cache` and reaches the function unchanged | internal | R6 |
| ~~`gather_results([none(), one(), none()])` preserves all three positions~~ — **landed** as `tests/internal/test_streams.py::test_gather_results_preserves_none_positions`; the defect was fixed with the `MISSING` sentinel (correctness-audit R7) | internal | R7 |
| ~~`Reencoder.read(1)` returns one character and the remainder survives the next `read`~~ — **landed** as `tests/internal/test_io.py::test_reencode_read_honors_char_count_with_remainder`; fixed with a char/byte remainder buffer (correctness-audit R8) | internal | R8 |
| `fetchtable` reads a real `.xlsx` and `.sqlite` fixture, sync **and** async | functional | R9 |
| `fetchdata` detects the format of `…/export.json?token=x` | internal | R10 |
| a tz-aware `struct_time` (`+03:00`) produces the matching epoch | internal | R11 |
| `get_skip({"content": "none available"}, {"field": "content"})` follows field-presence semantics | internal | R12 |
| `listize=True` turns `0`/`False`/`""` into one-element lists | internal | R13 |
| a stalled async iterator is actually interrupted by `timeout` | internal | R14 |
| the same bytes decode identically across sync HTTP, async HTTP and async local file | functional | R15 |
| `has_header=False` closes the original source as well as the spool | internal | R16 |

Two rows want **characterization** tests rather than regressions, because the current
behaviour may be intended: `filter`'s lexicographic `greater`/`less` (R19) and
`convert_dag` on an empty module list (R17, not reproduced). Their docstrings must say
they should be *updated, not deleted*, when the decision is made.

## 3. File-by-file audit

| Test area | Recommendation | Main changes |
|---|---|---|
| `functional/test_basics.py` | **Keep, heavily refactor** | Fix `_load`/`_aload` first. Parametrize the three `augment_entries` fallback cases. Share expected payloads between sync/async Kazeeki tests. `fetchpage` vs `fetchpage_loop` should be parametrized or make the loop test assert loop-specific semantics. Move mocked `_io` and direct `augment_entries` unit tests to internal suites. Keep the legacy JSON/generated-pipeline regressions. |
| `functional/test_examples.py` | **Keep, consolidate** | Important because `examples/**` is not in pytest's doctest collection. Parametrize `simple1`, `simple2`, `split`, `wired`. `gigs`/`kazeeki` overlap functional fixtures elsewhere; make example tests smaller smoke contracts rather than duplicating huge expected records. |
| `functional/test_pipeline.py` | **Remove / relocate** | No pytest tests; generated pipeline implementation under a `test_*.py` filename. |
| `functional/test_script.py` | **Keep, strengthen helper** | CLI/subprocess coverage is distinct. Fix/remove the boolean-comparison path: `fd.readlines()` consumes the stream before `bool(fd.read())`, so that branch always sees empty text. Replace the `SequenceMatcher(...).blocks[0].size == 7` benchmark check with explicit containment of stable benchmark labels. Keep `convert-dag → compile` (validates CLI wiring, not just library functions). |
| `internal/test_codegen_names.py` | **Keep, consolidate** | Collapse three taxonomy partition tests into one golden mapping. Fold enum override into the existing parametrization. Remove `test_member_is_shared_object` (public discovery suite owns it). Keep byte drift, order independence, collisions, and provider behavior. **Execute** generated provider code rather than string-searching it. |
| `internal/test_compile.py` | **Keep nearly intact** | Clear distinct ownership: codegen/executor parity, byte-golden corpus, malformed pipelines, DAG behavior, compiler loop translation. Do not collapse into functional tests. Compiler-loop tests overlap `test_loop.py` in subject but test a different layer. |
| `internal/test_decorators.py` | **Keep, trim duplicate rows** | Main truth table is good. `test_lambda_infers_sync_without_isasync`/`test_lambda_needs_explicit_isasync` repeat rows already in `test_resolved_isasync`; retain only the end-to-end async execution test from that class. Keep diagnostics. |
| `internal/test_dotdict.py` | **Keep, parametrize** | Not duplicated by the `DotDict` doctests (which cover retrieval/conversion). Nine deletion tests → a compact `(source, key, expected)` table covering root/nested/deep, case variation, missing paths. |
| `internal/test_gen_config.py` | **Reduce 4 → 2** | Keep byte equality (`_CONFIGS.read_text() == render()`) and the `FetchTableObjconf → CsvObjconf` inheritance semantic. Delete `test_configs_structure_matches_generated` and `test_every_objconf_has_nonraw_source`: `render()` is built from `objconf_structure()`, so byte equality subsumes both. |
| `internal/test_inference.py` | **Keep, consolidate cases** | Good diagnostic matrix; parametrize call/annotation shapes. `_inference.py` doctests `map`/`sum`/unknown-call that pytest re-tests — since `_inference` is private, keep the pytest suite and remove those private doctest examples. |
| `internal/test_loop.py` | **Keep, remove one duplicate** | Rewrite `test_loop_level_field_selects_child_input` to actually isolate `field` (give the parent a second candidate field). Remove `test_loop_has_async_pipe`: the async tests below already prove the interface exists. |
| `internal/test_parsers.py` | **Keep** | Two focused namespace-regression tests with distinct layers. No redundant coverage. |
| `internal/test_resolver.py` | **Keep, strengthen precedence** | Fix runtime-vs-entry-point test (distinguishable callables). `test_composite_store_first_hit_wins` should put the same name in two stores with different objects; currently the first store is empty, so it proves fallback, not precedence. Public `register(... requires name)` duplicates registry-level validation; one layer suffices. Rename `test_pipeline_delegates_to_compiler` (it proves non-pipeline names route to the module registry). |
| `internal/test_streams.py` | **Keep** | Strong primitives: boundedness, ordering, shared budgets, validation, merge incrementality. Parametrize ordered/unordered empty-source tests if desired. |
| `public/test_collections.py` | **Keep, split responsibilities** | Doing too much (pub/sub, executors, resource ownership, chaining, parity, module enums). Keep `TestModuleNameEnum` here as the ModuleName owner; remove redundant enum/string equivalence. Share `_ENGINES` for sync/async loopability. Keep pub/sub identity/cleanup + pool ownership. `"hash"` basics exist in README doctests → concentrate on tuple/template/reverse-operator/error variants. |
| `public/test_context_modes.py` | **Keep** | Compact, contract-focused. Keep the ignored-legacy-kwargs test as compatibility coverage while `Context` still accepts `**kwargs`. |
| `public/test_modules.py` | **Split public from internal; remove doctest duplication** | Imports implementation objects despite living under `public`. Keep API errors + meaningful public filtering contracts; import from the **defining modules** (the stable `riko` facade is reserved for user-facing docs/examples — internal `riko/` and `tests/` files always import from a symbol's defining module). Move exact metadata derivation, `@operator` inference, direct `count_pipe`, and implementation constants to internal. Basic `list_modules()` type/loopable/subtype/metadata and `list_targets()` happy paths are already FAQ doctests. |
| `public/test_parallel.py` | **Keep** | Good boundary vs primitive mechanics: it leaves precise backpressure math to `internal/test_streams.py`. Keep result equivalence, ordering, early close, non-materialization. |
| `public/test_pipe_lifecycle.py` | **Keep as lifecycle owner** | Large but coherent; sync/async mirroring is intentional. Single owner of exhaustion/reiteration/partial-chain lifecycle behavior. Do not sacrifice readability for LOC. |
| `public/test_sync_async_parity.py` | **Keep output parity; delete lifecycle class** | `TestOutputParity` is valuable. Remove `TestLifecycleObservableParity`: reiteration and partial-chain are already tested for both engines in `test_pipe_lifecycle.py`, and this file's own docstring says lifecycle parity lives there. |
| `public/test_imports.py` | **Consolidate** | One stable-surface assertion + one extension-surface assertion replace per-name `hasattr` parametrization. Exact golden-set equality makes `test_no_private_names_in_public_all` redundant. Fold runtime disjointness into the surface test. Keep the `Context` identity shim. Strengthen or rename `test_no_leaked_public_functions` — it only detects functions while claiming the whole surface is exactly `__all__`. |

### Discovery coverage (post-P9A note)

The audit's `public/test_fluent_discovery.py` section is **already actioned**: the standalone file
was dropped in P9A and its coverage folded into `test_collections.py`/`test_modules.py`. Its durable
recommendations still apply to *those* files: own `Modules.Sources`/`Transforms`, `list_modules`,
and `describe_module`; prove the enum crosses the pipe boundary with a deterministic module
(`SyncPipe(Sources.ITEMBUILDER, conf={"attrs": …})` yielding the built item) rather than comparing
`.name`; keep the graceful `describe_module(unknown) is None` edge; drop assertions that only test
`StrEnum` (`str(x) == "fetch"`) or that are misnamed (`list(Sinks) == []` catalog state,
`str(Module.Sources.__name__)`).

## 4. Doctest audit

Different deletion rule from pytest, because doctests are executable documentation:

- **Public/built-in doctests stay** when they demonstrate a useful API behavior — overlap between a
  README journey and a module example is not inherently wasteful.
- **Private doctests need stronger justification.** If `_inference`/`_iterutils`/`_objectify` already
  have focused pytest coverage, move edge cases to pytest and leave at most a tiny descriptive
  example. `_inference.infer_from_source()` is the clearest candidate — its doctests repeat pytest
  cases.
- **The root `riko/__init__.py` doctest should go.** It re-teaches a normal `SyncPipe` workflow the
  README/module docs already own. The package initializer should describe the namespace.
- **FAQ doctests should own ordinary discovery examples** (`list_modules()` ordering/type/loopable/
  subtype/primary/metadata/export targets) — which is *why* several simple `public/test_modules.py`
  assertions can disappear. Once typed discovery is documented there, add `Modules.Sources`,
  `list_modules`, and `describe_module` happy paths to the FAQ.
- **`docs/INSTALLATION.rst`** doctest is worth keeping: a self-contained "imports + basic chaining"
  installation smoke test.
- `>>>` in `examples/**`, `_docs/**`, and `CLAUDE.md` are **not** collected today — which is exactly
  why `functional/test_examples.py` matters: it is what actually executes the example pipelines.

## 5. First-pass patch (conservative, mostly indisputable)

```text
FIX
- test_basics._load/_aload forward value/check correctly
- resolver precedence tests use distinguishable implementations
- loop field-selection test actually isolates field selection
- test_script output helper stops carrying ineffective comparison logic

REMOVE
- tests/functional/test_pipeline.py
- test_codegen_names::test_member_is_shared_object
- 2 redundant test_gen_config structural tests
- test_loop::test_loop_has_async_pipe
- one duplicate loop count/field test after rewriting the useful one
- test_sync_async_parity::TestLifecycleObservableParity
- redundant import-surface assertions
- private _inference doctests duplicated by test_inference

CONSOLIDATE
- augment_entries fallback tests
- sync/async Kazeeki expectations
- simple example pipelines
- DotDict deletion matrix
- codegen taxonomy tests
- export-surface tests
- ModuleName tests into one owner
```

**Do not** reduce `test_compile`, `test_parallel`, `test_streams`, or the core lifecycle tests just
to shrink the suite — they cover contracts hard to catch elsewhere.

**Shipped (first-pass patch).** The conservative FIX/REMOVE set has landed:

- `test_basics._load`/`_aload` now forward `value`/`check`; the two stale expected counts the
  live assertions exposed were corrected to the deterministic fixture truth (`feeddiscovery`
  25→15, `simplemath_1` 4→6).
- Resolver precedence tests use distinguishable callables: `test_runtime_registration_shadows_entry_point`
  now proves the runtime marker (not the entry-point one) wins, and `test_composite_store_first_hit_wins`
  puts a different object in the first two stores so it proves precedence, not fallback.
- `test_loop_level_field_selects_child_input` now isolates `field` (a parent carrying both
  `title` and `alt`, tokenizing on `alt`), so it is no longer a duplicate of
  `test_loop_count_all_flattens_embedded_results`.
- `test_script.assert_output_matches` dropped the dead/broken `bool` branch and the
  `SequenceMatcher` `partial` path; `test_benchmark` now asserts the stable benchmark labels
  directly (each label heads a line, robust to the right-justified name padding).
- Removed `test_loop_has_async_pipe`, `TestLifecycleObservableParity` (both engines already
  covered in `test_pipe_lifecycle.py`), and the two redundant `test_gen_config` structural tests
  (byte equality subsumes them).
- Trimmed `_inference.infer_from_source` doctests to one descriptive example; the map/sum/unknown
  edge cases live in `test_inference.py`.

**Shipped (§ 3 consolidation, first batch).**

- `test_dotdict.py` — nine deletion tests folded into one parametrized `(source, key, expected)`
  matrix (root/nested/deep, case variation, missing paths), one case per `pytest.param` id.
- `test_codegen_names.py` — the three taxonomy partition tests collapsed into a single golden
  partition (`test_taxonomy_partition_matches_golden`); the enum override case folded into the
  `test_enum_member_name` parametrization; the two provider tests now **execute** the generated
  source (`exec`) and assert on the resulting enum objects instead of string-searching it.
- `test_decorators.py` — dropped `test_lambda_infers_sync_without_isasync`/
  `test_lambda_needs_explicit_isasync` (duplicates of `TestIsasyncInferenceValid` rows); the
  class now owns only the end-to-end async-execution proof.
- `public/test_modules.py` split public↔internal: exact metadata derivation
  (`get_module_metadata` classification) + the `@operator` subtype inference moved to the new
  `internal/test_metadata.py`; the public file now owns only discovery-filtering combinations,
  API errors, and input test-flag scoping. (Internal tests import from defining modules per the
  established convention — not the `riko` facade.)
- `public/test_collections.py` deduped: the sync/async copies of
  `test_pipes_use_loopability_for_mapping` folded into one `_ENGINES`-parametrized parity test,
  and the redundant `test_enum_and_string_resolve_identically` dropped (equivalence is already
  proven by `test_normalize_module_name` + `test_constructor_stores_plain_string`).
- `public/test_imports.py` (the P13 exit test) consolidated **without weakening the contract**:
  the two per-name `hasattr` parametrizations collapsed into one single-assertion resolve check
  each (stable + extension); `test_no_private_names_in_public_all` removed and its guarantee folded
  into `test_partial_surface_matches_expected` (equal surfaces already get no-private free from
  golden-set equality; the partial `riko.modules`/`riko.exceptions` surfaces now assert it
  explicitly — and the modules check now also covers `riko.modules._names`); and
  `test_no_leaked_public_functions`'s overclaiming docstring corrected to state it guards
  *functions* specifically (classes/constants like `Context` are intentionally unexported).

**Remaining.** `tests/functional/test_pipeline.py` was removed. The rest of the § 3 CONSOLIDATE
work (the deeper `public/test_collections.py` responsibility split into focused files + trimming
chaining tests that README doctests already own, parametrize the `augment_entries` fallbacks +
example pipelines in `functional/`, and the `internal/test_inference.py` call/annotation-shape
parametrization) and the § 2b regression batch (new fixtures: `.xlsx`/`.sqlite`, threaded servers,
sync/async parity bytes) are not yet done.

## 6. Relationship to the P-track

- **P13 exit tests** (see [MILESTONES.md](../MILESTONES.md)) — `public/test_imports.py` (extended
  public/EXT `__all__`; no accidental internal exports) + `tests/typing/`. This gameplan supplies the
  *layering* half of P13; the `tests/typing/{valid,invalid}/` type-check split is MILESTONES' half.
- **Live status** (done/next/suite count) lives only in the
  [PHASE_CHECKLISTS.md](../PHASE_CHECKLISTS.md) tracker — do not restate it here.
